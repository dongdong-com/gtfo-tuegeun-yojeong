"""캡처 이미지 인쇄: 쪽 나누기 + Windows 인쇄 미리보기/인쇄 대화상자(.NET PrintDocument를 PowerShell로 호출).

- 폭에 맞춰 여러 쪽: 이미지를 용지 폭에 맞추고, 쪽 경계는 글자가 없는 가로줄에서 잘라 글자가 쪽 사이에 갈라지지 않게 한다
- 한 쪽에 맞춤: 이미지 전체를 한 장에 (비율 유지)
- 용지 방향 자동: 가로로 넓은 이미지는 가로 용지
- 쪽 아래에 '퇴근요정 · 날짜 시각 · 쪽/전체'를 작게 넣을 수 있다
추가 패키지 없이 Windows 기본 기능만 쓴다. 인쇄할 내용은 이 PC의 프린터로만 간다."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import tablegrid

A4_RATIO = (210 - 25.4) / (297 - 25.4)          # 여백 0.5인치를 뺀 A4 인쇄 영역의 폭/높이
TARGET_W = 1600                                    # 인쇄용 쪽 그림의 폭(px). 더 작은 이미지는 부드럽게 키워 선명하게 인쇄한다 (최대 3배)
FOOTER_FRAC = 0.035

_PS = r'''
param([string]$ListFile, [switch]$Landscape, [switch]$Direct, [string]$Title)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$files = Get-Content -LiteralPath $ListFile -Encoding UTF8 | Where-Object { $_.Trim() }
$imgs = @(); foreach ($f in $files) { $imgs += [System.Drawing.Image]::FromFile($f) }
$script:idx = 0
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.DocumentName = $Title
$doc.DefaultPageSettings.Landscape = [bool]$Landscape
$doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(50, 50, 50, 50)
$doc.add_BeginPrint({ $script:idx = 0 })
$doc.add_PrintPage({
    param($s, $e)
    $img = $imgs[$script:idx]
    $b = $e.MarginBounds
    $k = [Math]::Min($b.Width / $img.Width, $b.Height / $img.Height)
    $w = [int]($img.Width * $k); $h = [int]($img.Height * $k)
    $e.Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $e.Graphics.DrawImage($img, $b.Left + [int](($b.Width - $w) / 2), $b.Top, $w, $h)
    $script:idx++
    $e.HasMorePages = ($script:idx -lt $imgs.Count)
})
try {
    if ($Direct) {
        $pd = New-Object System.Windows.Forms.PrintDialog
        $pd.Document = $doc; $pd.AllowSomePages = $true; $pd.UseEXDialog = $true
        $pd.PrinterSettings.MinimumPage = 1; $pd.PrinterSettings.MaximumPage = $imgs.Count
        $pd.PrinterSettings.FromPage = 1; $pd.PrinterSettings.ToPage = $imgs.Count
        if ($pd.ShowDialog() -eq 'OK') { $doc.Print() }
    } else {
        $dlg = New-Object System.Windows.Forms.PrintPreviewDialog
        $dlg.Document = $doc; $dlg.UseAntiAlias = $true; $dlg.WindowState = 'Maximized'; $dlg.Text = $Title
        $dlg.TopMost = $true
        [void]$dlg.ShowDialog()
    }
} finally { foreach ($i in $imgs) { $i.Dispose() } }
'''


def _cut_near_end(ink: np.ndarray, lo: int, hi: int) -> int:
    """ink[lo:hi]에서 글자가 없는 가로 띠들 중 '충분히 넓은 것 가운데 가장 아래쪽'의 한가운데에서 자른다 (쪽을 최대한 채우면서 글자 줄 사이에서 자름).
    빈 띠가 하나도 없으면 hi에서 자른다."""
    seg = ink[lo:hi]
    if len(seg) == 0:
        return hi
    base = float(seg.min())
    tol = max(0.5, 0.03 * (float(seg.max()) - base))
    blank = seg <= base + tol
    runs, i = [], 0
    while i < len(blank):
        if blank[i]:
            j = i
            while j < len(blank) and blank[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        return hi
    widest = max(b - a for a, b in runs)
    good = [r for r in runs if (r[1] - r[0]) >= 0.7 * widest]
    a, b = good[-1]
    return lo + (a + b) // 2 + 1


def _font(size: int):
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def choose_landscape(img: Image.Image, mode: str, orient: str) -> bool:
    if orient == "가로":
        return True
    if orient == "세로":
        return False
    return img.width > 1.25 * img.height            # 자동: 가로로 넓은 이미지는 가로 용지


def paginate(img: Image.Image, mode: str = "폭에 맞춰 여러 쪽", landscape: bool = False, footer: bool = True,
             stamp: str = "") -> list[Image.Image]:
    """이미지를 쪽 그림 목록으로 만든다 (각 쪽은 용지 인쇄 영역과 같은 비율의 흰 바탕 + 아래 바닥글)."""
    img = img.convert("RGB")
    ratio = (1 / A4_RATIO) if landscape else A4_RATIO       # 폭/높이
    scale = 1.0
    if img.width < TARGET_W:
        scale = min(3.0, TARGET_W / img.width)
    W = max(int(round(img.width * scale)), 600)
    foot_h = int(W * FOOTER_FRAC / ratio) if footer else 0
    body_h = int(round(W / ratio)) - foot_h
    pages_src: list[Image.Image] = []
    if mode.startswith("한"):                                 # 한 쪽에 맞춤: 전체를 비율 유지로 본문 영역에 넣는다
        k = min(W / img.width, body_h / img.height)
        pages_src.append(img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS))
    else:                                                      # 폭에 맞춤: 용지 폭에 맞추고 본문 높이마다 잘라 여러 쪽
        big = img.resize((W, max(1, int(img.height * W / img.width))), Image.LANCZOS) if W != img.width else img
        if big.height <= body_h * 1.1:                          # 한 쪽에 거의 들어가면 쪽을 나누지 않고 맞춘다
            k = min(1.0, body_h / big.height)
            pages_src.append(big.resize((max(1, int(big.width * k)), max(1, int(big.height * k))), Image.LANCZOS) if k < 1 else big)
        else:
            g = np.asarray(big.convert("L"), dtype=np.float32)
            ink = np.abs(g - np.median(g)).mean(axis=1)           # 행별 '글자량': 글자가 없는 줄에서 자른다
            y = 0
            while y < big.height:
                end = min(big.height, y + body_h)
                if end < big.height:
                    end = _cut_near_end(ink, y + int(body_h * 0.85), end)
                pages_src.append(big.crop((0, y, W, end)))
                y = end
    total = len(pages_src)
    f = _font(max(12, int(W * 0.011)))
    out = []
    for i, p in enumerate(pages_src, 1):
        canvas = Image.new("RGB", (W, body_h + foot_h), "white")
        canvas.paste(p, ((W - p.width) // 2, 0))
        if footer:
            d = ImageDraw.Draw(canvas)
            text = f"퇴근요정 · {stamp} · {i}/{total}" if stamp else f"퇴근요정 · {i}/{total}"
            tw = d.textlength(text, font=f)
            d.text((W - tw - int(W * 0.01), body_h + (foot_h - f.size) // 2), text, fill=(140, 140, 140), font=f)
        out.append(canvas)
    return out


def _launch(pages: list[Image.Image], landscape: bool, direct: bool, title: str):
    """쪽 그림을 임시 폴더에 저장하고 PowerShell(STA)로 미리보기/인쇄 대화상자를 연다. 끝나면 임시 파일을 지운다."""
    tmp = tempfile.mkdtemp(prefix="gtfo_print_")
    paths = []
    for i, p in enumerate(pages, 1):
        fp = os.path.join(tmp, f"page_{i:03d}.png")
        p.save(fp)
        paths.append(fp)
    lst = os.path.join(tmp, "pages.txt")
    with open(lst, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(paths))
    ps1 = os.path.join(tmp, "print.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    args = ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", ps1,
            "-ListFile", lst, "-Title", title]
    if landscape:
        args.append("-Landscape")
    if direct:
        args.append("-Direct")
    proc = subprocess.Popen(args, creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup():
        proc.wait()
        time.sleep(1.0)
        shutil.rmtree(tmp, ignore_errors=True)
    threading.Thread(target=cleanup, daemon=True).start()
    return proc


class PrintDialog(tk.Toplevel):
    """인쇄 옵션 창: 맞춤 방식 / 용지 방향 / 바닥글 → '미리보기' 또는 '프린터 선택해 바로 인쇄'."""

    def __init__(self, master, img: Image.Image, title: str = "퇴근요정 캡처"):
        super().__init__(master)
        self.img, self.title_text = img, title
        self.title("인쇄")
        self.resizable(False, False)
        self.transient(master)
        self.mode = tk.StringVar(value="폭에 맞춰 여러 쪽")
        self.orient = tk.StringVar(value="자동")
        self.footer = tk.BooleanVar(value=True)
        f = ttk.Frame(self, padding=12); f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"이미지 {img.width}×{img.height}px", foreground="gray").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="맞춤 방식").grid(row=1, column=0, sticky="w", pady=(8, 0))
        for i, m in enumerate(("폭에 맞춰 여러 쪽", "한 쪽에 맞춤")):
            ttk.Radiobutton(f, text=m, variable=self.mode, value=m, command=self._info).grid(row=1, column=1 + i, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(f, text="용지 방향").grid(row=2, column=0, sticky="w", pady=(6, 0))
        for i, m in enumerate(("자동", "세로", "가로")):
            ttk.Radiobutton(f, text=m, variable=self.orient, value=m, command=self._info).grid(row=2, column=1 + i, sticky="w", padx=6, pady=(6, 0))
        ttk.Checkbutton(f, text="쪽 아래에 날짜·쪽번호 넣기", variable=self.footer).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.info = ttk.Label(f, text="", foreground="#5A4A4F"); self.info.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row = ttk.Frame(f); row.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(row, text="미리보기…", command=lambda: self.go(False)).pack(side="left")
        ttk.Button(row, text="프린터 선택해 바로 인쇄…", command=lambda: self.go(True)).pack(side="left", padx=6)
        ttk.Button(row, text="닫기", command=self.destroy).pack(side="left")
        self._info()
        self.update_idletasks()
        try:
            self.geometry(f"+{master.winfo_rootx() + 120}+{master.winfo_rooty() + 120}")
        except Exception:
            pass
        self.grab_set()

    def _pages(self):
        ls = choose_landscape(self.img, self.mode.get(), self.orient.get())
        stamp = time.strftime("%Y-%m-%d %H:%M")
        return paginate(self.img, self.mode.get(), ls, self.footer.get(), stamp), ls

    def _info(self):
        try:
            ls = choose_landscape(self.img, self.mode.get(), self.orient.get())
            pages, _ = self._pages()
            self.info.config(text=f"{'가로' if ls else '세로'} 용지 A4 기준 {len(pages)}쪽")
        except Exception:
            self.info.config(text="")

    def go(self, direct: bool):
        try:
            pages, ls = self._pages()
            _launch(pages, ls, direct, self.title_text)
        except Exception as ex:
            messagebox.showerror("인쇄", f"인쇄 창을 열지 못했습니다.\n{ex}", parent=self)
            return
        self.destroy()
