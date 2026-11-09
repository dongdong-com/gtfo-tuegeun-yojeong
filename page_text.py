"""운영 > 텍스트 캡쳐하기.
이미지 안의 글자, 또는 텍스트 선택·복사가 막힌 웹페이지/원격(VDI) 화면의 글자를 화면 픽셀에서 읽어 텍스트로 뽑는다.

가져오기: 화면 영역 캡처 / 영역 지정 + 자동 스크롤 캡처(긴 페이지) / 이미지 파일 열기 / 클립보드 이미지 붙여넣기
정리:     줄 그대로 · 문단으로 합치기 · 한 줄로, 다단(2단 이상) 읽기 순서, 공백 정리, 어두운 배경 자동 반전
출력:     클립보드 복사(OCR 직후 자동), .txt 저장, 이미지의 원하는 영역만 다시 읽기
모두 이 PC에서만 처리한다 (Windows 내장 OCR)."""
import re
import statistics
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageGrab, ImageOps

import core
from page_vdi import VdiTablePage
from text_picker import TextPicker

LINE_MODES = ("줄 그대로", "문단으로 합치기", "한 줄로")
AUTO_LANG = "자동 (Windows 사용자 언어)"
_SENTENCE_END = re.compile(r"[.!?。…\"')\]」』]$")


def _line_records(words: list, multicol: bool, bounds=None):
    """OCR 단어 → 읽는 순서의 줄 목록 [{text, y, x0, x1}]. multicol이면 세로 여백으로 열을 나눠 열마다 위→아래로 읽는다.
    bounds: 이미지에서 이미 찾은 열 경계 [(x0, x1), …] (ocrplus). 있으면 단어 위치로 다시 추정하지 않고 이걸 쓴다."""
    if not words:
        return []
    hh = statistics.median(w[3] for w in words)
    groups = [words]
    if multicol and bounds and len(bounds) >= 2:
        cols = [[w for w in words if lo <= w[1] + w[4] / 2 < hi] for lo, hi in bounds]
        cols = [c for c in cols if c]
        if len(cols) >= 2:
            groups = cols
    elif multicol:
        cols = _split_columns(words, hh)
        if cols:
            groups = cols
    out = []
    for gi, g in enumerate(groups):
        for line in core.cluster_rows(g):
            parts = [line[0][0]]
            for a, b in zip(line, line[1:]):
                gap = b[1] - (a[1] + a[4])
                parts.append(("   " if gap > 2.5 * hh else " ") + b[0])        # 큰 간격(탭처럼 벌어진 칸)은 공백 3칸으로 남긴다
            out.append({"text": "".join(parts), "y": sum(w[2] for w in line) / len(line),
                        "x0": min(w[1] for w in line), "x1": max(w[1] + w[4] for w in line), "col": gi})
    return out


def _split_columns(words: list, hh: float):
    """단어들의 x 범위에서 세로로 넓게 빈 구간을 찾아 열로 나눈다. 열이 아니라고 판단되면 None.
    조건: 빈 구간 폭이 글자 높이의 4배(또는 전체 폭의 3%) 이상이고, 각 열에 단어가 10% 이상 있어야 한다."""
    x_min = int(min(w[1] for w in words))
    x_max = int(max(w[1] + w[4] for w in words)) + 1
    width = x_max - x_min
    if width < 200:
        return None
    cover = np.zeros(width + 1, dtype=bool)
    for w in words:
        cover[int(w[1]) - x_min:int(w[1] + w[4]) - x_min + 1] = True
    gap_min = max(4 * hh, 0.03 * width)
    cuts, run = [], 0
    for x in range(width + 1):
        if not cover[x]:
            run += 1
        else:
            if run >= gap_min and x - run > 0:
                cuts.append(x_min + x - run // 2)                              # 빈 구간의 가운데
            run = 0
    if not cuts:
        return None
    bounds = [-1e9] + cuts + [1e9]
    cols = [[w for w in words if bounds[i] <= w[1] + w[4] / 2 < bounds[i + 1]] for i in range(len(bounds) - 1)]
    cols = [c for c in cols if c]
    if len(cols) < 2 or any(len(c) < 0.10 * len(words) for c in cols):
        return None
    return cols


def fix_english_digits(text: str) -> str:
    """영문 소문자 단어 속에서 숫자로 잘못 읽힌 0/1을 보수적으로 되돌린다 (한국어 OCR 엔진은 영어 단어의 o/l을 숫자로 읽곤 한다).
      · 소문자 사이의 0→o, 1→l  (w0rld→world, hel1o→hello, bl0g→blog)
      · 소문자 1~2자 뒤의 00→oo (t00→too, z00→zoo)
    숫자가 섞인 정상 값(H2O, mp3, ver10, 2026-11-05)과 숫자만의 값은 건드리지 않는다."""
    def fix(m):
        w = m.group(0)
        if w.isdigit() or not re.search(r"[a-z]", w) or re.search(r"[2-9]", w):
            return w
        if re.fullmatch(r"[a-z]{1,2}00", w):
            return w[:-2] + "oo"
        w = re.sub(r"(?<=[a-z])0(?=[a-z])", "o", w)
        return re.sub(r"(?<=[a-z])1(?=[a-z])", "l", w)
    return re.sub(r"[A-Za-z0-9]+", fix, text)


def compose_text(words: list, mode: str = "줄 그대로", tidy: bool = True, multicol: bool = False,
                 fix_en: bool = True, bounds=None) -> str:
    """OCR 단어를 읽는 순서·줄바꿈 방식에 맞춰 텍스트로 만든다."""
    text = _compose(words, mode, tidy, multicol, bounds)
    return fix_english_digits(text) if fix_en else text


def _compose(words: list, mode: str, tidy: bool, multicol: bool, bounds=None) -> str:
    lines = _line_records(words, multicol, bounds)
    if not lines:
        return ""
    texts = [re.sub(r" {2,}", " ", l["text"]).strip() if tidy else l["text"].rstrip() for l in lines]
    if mode == "한 줄로":
        out = " ".join(t for t in texts if t)
        return re.sub(r" {2,}", " ", out) if tidy else out
    if mode == "문단으로 합치기":
        gaps = [b["y"] - a["y"] for a, b in zip(lines, lines[1:]) if b["col"] == a["col"] and b["y"] > a["y"]]
        pitch = statistics.median(gaps) if gaps else 0
        max_w = max(l["x1"] - l["x0"] for l in lines) or 1
        paras, cur = [], []
        for i, (rec, t) in enumerate(zip(lines, texts)):
            if not t:
                continue
            if cur:
                prev = lines[i - 1]
                new_col = rec["col"] != prev["col"]
                big_gap = pitch and (rec["y"] - prev["y"]) > 1.35 * pitch      # 문단 사이 여백은 보통 줄 간격의 1.5배 이상
                short_end = (prev["x1"] - prev["x0"]) < 0.6 * max_w and bool(_SENTENCE_END.search(texts[i - 1]))
                if new_col or big_gap or short_end:
                    paras.append(cur); cur = []
            cur.append(t)
        if cur:
            paras.append(cur)
        merged = []
        for p in paras:
            s = p[0]
            for t in p[1:]:
                if s.endswith("-") and t[:1].islower():                       # 영어 단어가 줄 끝에서 하이픈으로 나뉜 경우
                    s = s[:-1] + t
                else:
                    s += " " + t
            merged.append(s)
        return "\n\n".join(merged)
    out, blank = [], 0                                                         # 줄 그대로 (열이 바뀌면 빈 줄 하나)
    for i, t in enumerate(texts):
        if i and lines[i]["col"] != lines[i - 1]["col"]:
            out.append("")
        out.append(t)
    return "\n".join(out)


class TextExtractPage(VdiTablePage):
    TITLE = "텍스트 캡쳐하기"
    URL_TOOLS = False
    OCR_TILE = True
    DEFAULT_SCALE = "3.0"
    INTRO = ("화면 영역이나 이미지에서 글자를 읽어 텍스트로 뽑습니다. 영역 캡처·스크롤 캡처·이미지 파일·클립보드 이미지를 "
             "쓸 수 있습니다.")

    # ---------------------------------------------------------- 변수/UI
    def _init_extra(self):
        self.langs = core.ocr_languages()
        self.lang_sel = tk.StringVar()
        self.line_mode = tk.StringVar(value=LINE_MODES[0])
        self.tidy = tk.BooleanVar(value=True)
        self.multicol = tk.BooleanVar(value=True)             # 카드/단이 나란히 있어도 섞이지 않게 기본 켬
        self.col_bounds = None
        self.fix_en = tk.BooleanVar(value=True)
        self.auto_invert = tk.BooleanVar(value=True)
        self.auto_copy = tk.BooleanVar(value=True)
        self.inverted = False
        self.lang_labels = [AUTO_LANG] + [f"{name} ({tag})" for tag, name in self.langs]
        self.lang_sel.set(self.lang_labels[1] if len(self.lang_labels) > 1 else AUTO_LANG)

    def _ocr_words(self, img, progress=None):
        """여러 배율/선명화로 읽어 줄마다 가장 좋은 결과를 쓴다 (ocrplus). 아주 큰 이미지는 설정 수가 자동으로 줄어든다."""
        import ocrplus
        words = ocrplus.read_words(img, scale=float(self.ocr_scale.get()), sharp=self.ocr_sharp.get(),
                                   lang=self._ocr_lang(), progress=progress)
        self.col_bounds = ocrplus.last_bounds
        return words

    def _ocr_lang(self) -> str:
        m = re.search(r"\(([^()]+)\)$", self.lang_sel.get())
        return m.group(1) if m and self.lang_sel.get() != AUTO_LANG else "auto"

    def _prepare_for_ocr(self, img):
        """어두운 배경(다크 모드 웹페이지 등)의 밝은 글자는 OCR이 잘 못 읽으므로, 평균 밝기가 낮으면 반전해서 읽는다."""
        self.inverted = False
        if self.auto_invert.get():
            g = np.asarray(img.convert("L"), dtype=np.float32)
            if float(np.median(g)) < 110:
                self.inverted = True
                return ImageOps.invert(img.convert("RGB"))
        return img

    def _ui(self):
        src = ttk.LabelFrame(self, text="① 가져오기", padding=6)
        src.pack(fill="x", padx=6, pady=6)
        ttk.Button(src, text="화면 영역 캡처 (스크롤 없음)", command=self.snap).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(src, text="영역 지정 + 자동 스크롤 캡처", command=self.start).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(src, text="이미지 파일 열기…", command=self.open_image).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(src, text="클립보드 이미지 붙여넣기", command=self.paste_image).grid(row=0, column=3)
        sc = ttk.Frame(src); sc.grid(row=1, column=0, columnspan=8, sticky="w", pady=(6, 0))
        ttk.Label(sc, text="스크롤 캡처:", foreground="gray").pack(side="left")
        ttk.Combobox(sc, textvariable=self.mode, values=["마우스 휠", "PageDown 키"], width=11,
                     state="readonly").pack(side="left", padx=(6, 2))
        ttk.Label(sc, text="휠 칸").pack(side="left", padx=(6, 2))
        ttk.Spinbox(sc, from_=1, to=20, textvariable=self.notches, width=4).pack(side="left")
        ttk.Label(sc, text="대기(ms)").pack(side="left", padx=(6, 2))
        ttk.Spinbox(sc, from_=100, to=5000, increment=100, textvariable=self.delay, width=6).pack(side="left")
        ttk.Label(sc, text="최대").pack(side="left", padx=(6, 2))
        ttk.Spinbox(sc, from_=1, to=500, textvariable=self.max_steps, width=5).pack(side="left")
        ttk.Checkbutton(sc, text="맨 위로", variable=self.to_top).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(sc, text="영역 중앙 클릭", variable=self.click_focus).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(sc, text="끝 아래쪽 포함", variable=self.include_tail).pack(side="left", padx=(6, 0))
        ttk.Label(src, text="※ 캡처 중에는 마우스를 움직이지 마세요(ESC = 중단). 글자가 작으면 OCR 배율을 올리세요. "
                            "모든 처리는 이 PC에서만 합니다.", foreground="gray").grid(
            row=2, column=0, columnspan=8, sticky="w", pady=(4, 0))

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=6)
        pv = ttk.LabelFrame(mid, text="이미지 (축소)", padding=4)
        pv.pack(side="left", fill="y")
        self.cv = tk.Canvas(pv, width=300, height=340, bg="#E3EFFD", highlightthickness=0)
        sb = ttk.Scrollbar(pv, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="y"); sb.pack(side="left", fill="y")

        rt = ttk.LabelFrame(mid, text="② 추출된 텍스트 (직접 수정 가능)", padding=4)
        rt.pack(side="left", fill="both", expand=True, padx=(8, 0))
        r1 = ttk.Frame(rt); r1.pack(fill="x")
        ttk.Label(r1, text="OCR 언어").pack(side="left")
        ttk.Combobox(r1, textvariable=self.lang_sel, values=self.lang_labels, width=22, state="readonly").pack(side="left", padx=(4, 8))
        ttk.Label(r1, text="배율").pack(side="left")
        ttk.Combobox(r1, textvariable=self.ocr_scale, values=["1.5", "2.0", "3.0", "4.0"], width=4,
                     state="readonly").pack(side="left", padx=(4, 0))
        ttk.Checkbutton(r1, text="선명화", variable=self.ocr_sharp).pack(side="left", padx=8)
        ttk.Checkbutton(r1, text="어두운 배경 자동 반전", variable=self.auto_invert).pack(side="left")
        ttk.Button(r1, text="OCR 다시", command=self.reocr).pack(side="left", padx=8)
        r2 = ttk.Frame(rt); r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="줄바꿈").pack(side="left")
        c = ttk.Combobox(r2, textvariable=self.line_mode, values=list(LINE_MODES), width=14, state="readonly")
        c.pack(side="left", padx=(4, 8)); c.bind("<<ComboboxSelected>>", lambda _e: self.rebuild())
        ttk.Checkbutton(r2, text="공백 정리", variable=self.tidy, command=self.rebuild).pack(side="left")
        ttk.Checkbutton(r2, text="다단(2단 이상) 읽기", variable=self.multicol, command=self.rebuild).pack(side="left", padx=8)
        ttk.Checkbutton(r2, text="영문 단어 속 0/1 보정", variable=self.fix_en, command=self.rebuild).pack(side="left")
        ttk.Checkbutton(r2, text="OCR 직후 자동 복사", variable=self.auto_copy).pack(side="left", padx=8)
        if len(self.langs) <= 1:
            ttk.Label(rt, text="※ 이 PC에는 OCR 언어가 한국어뿐입니다(영어 글자도 함께 읽습니다). 다른 언어는 Windows 설정 > "
                               "시간 및 언어 > 언어에서 해당 언어(OCR 포함)를 설치하면 목록에 나타납니다.",
                      foreground="gray", wraplength=640, justify="left").pack(fill="x", pady=(4, 0))
        r3 = ttk.Frame(rt); r3.pack(fill="x", pady=(4, 0))
        self.btn_ai = ttk.Button(r3, text="AI로 보정 (로고·작은 글자·오인식)", command=self.ai_fix)
        self.btn_ai.pack(side="left")
        self.btn_undo = ttk.Button(r3, text="AI 보정 되돌리기", command=self.ai_undo, state="disabled")
        self.btn_undo.pack(side="left", padx=6)
        ttk.Label(r3, text="이 PC의 로컬 AI(Gemma 4 E2B)가 이미지를 보고 고칩니다 · 10~30초 · 바뀐 줄은 노란색",
                  foreground="gray").pack(side="left")
        self.txt = tk.Text(rt, wrap="word", height=14, undo=True, font=("맑은 고딕", 10))
        self.txt.tag_configure("chg", background="#FEEC95")
        ys = ttk.Scrollbar(rt, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True, pady=4)

        out = ttk.Frame(self, padding=6); out.pack(fill="x")
        ttk.Label(out, textvariable=self.status, foreground="#5A4A4F").pack(anchor="w")
        row = ttk.Frame(out); row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="텍스트 복사", command=self.copy_text).pack(side="left")
        ttk.Button(row, text="이미지에서 영역만 다시 읽기…", command=self.pick_region).pack(side="left", padx=4)
        ttk.Button(row, text="텍스트 파일(.txt)로 저장", command=self.save_txt).pack(side="left")
        ttk.Button(row, text="PNG 저장", command=self.save_png).pack(side="right")
        ttk.Button(row, text="인쇄…", command=self.print_image).pack(side="right", padx=4)
        ttk.Button(row, text="이미지 복사", command=self.copy_image).pack(side="right", padx=4)

    # ---------------------------------------------------------- 가져오기
    def _load(self, img: Image.Image, label: str):
        self.img = img.convert("RGB")
        self._preview()
        self.status.set(f"{label} {self.img.width}×{self.img.height}px · OCR 중…")
        self.update()
        if self.reocr():
            self.status.set(f"{label} {self.img.width}×{self.img.height}px · {self._rows()}줄 · "
                            f"{len(self.txt.get('1.0', 'end').strip())}자" + (" · 어두운 배경이라 반전해서 읽음" if self.inverted else ""))

    def open_image(self):
        path = filedialog.askopenfilename(title="이미지 파일 선택",
                                          filetypes=[("이미지", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            im = Image.open(path)
            im = ImageOps.exif_transpose(im)                       # 휴대폰 사진의 회전 정보 반영
            self._load(im, path.replace("/", "\\").split("\\")[-1])
        except Exception as ex:
            messagebox.showerror("이미지 열기 실패", str(ex))

    def paste_image(self):
        try:
            clip = ImageGrab.grabclipboard()
        except Exception as ex:
            messagebox.showerror("클립보드 읽기 실패", str(ex)); return
        if isinstance(clip, Image.Image):
            self._load(clip, "클립보드 이미지")
        elif isinstance(clip, list) and clip:                        # 탐색기에서 이미지 파일을 복사한 경우
            try:
                self._load(ImageOps.exif_transpose(Image.open(clip[0])), str(clip[0]).split("\\")[-1])
            except Exception as ex:
                messagebox.showinfo("클립보드", f"복사된 파일을 이미지로 열 수 없습니다.\n{ex}")
        else:
            messagebox.showinfo("클립보드", "클립보드에 이미지가 없습니다.\n"
                                          "Win+Shift+S 로 화면을 캡처하거나 이미지를 복사한 뒤 다시 눌러 주세요.")

    # ---------------------------------------------------------- 텍스트 만들기
    def rebuild(self):
        """저장된 OCR 단어로 줄바꿈/공백/다단 설정만 바꿔 텍스트를 다시 만든다 (재인식 없음)."""
        if not self.words:
            return
        text = compose_text(self.words, self.line_mode.get(), self.tidy.get(), self.multicol.get(), self.fix_en.get(),
                            getattr(self, "col_bounds", None))
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        n = len([l for l in text.splitlines() if l.strip()])
        self.status.set(f"{n}줄 · {len(text.strip())}자" + (" · 어두운 배경이라 반전해서 읽음" if self.inverted else ""))
        if self.auto_copy.get() and text.strip():
            self.clipboard_clear(); self.clipboard_append(text); self.update()
            self.status.set(self.status.get() + " · 클립보드에 복사됨 ✔")

    # ---------------------------------------------------------- AI 보정
    def ai_fix(self):
        """현재 텍스트(OCR 초안)와 이미지를 로컬 AI에게 보여 주고, 틀린 글자·빠진 글자를 고친 결과를 받는다.
        결과는 원문을 대체하되 바뀐 줄을 노란색으로 표시하고, '되돌리기'로 원문을 복구할 수 있다."""
        import aillm
        if getattr(self, "_ai_cancel", None) is not None:            # 실행 중이면 중단
            self._ai_cancel.set()
            return
        if self.img is None:
            messagebox.showinfo("AI 보정", "먼저 이미지를 가져오세요."); return
        draft = self.txt.get("1.0", "end").rstrip("\n")
        if not draft.strip():
            messagebox.showinfo("AI 보정", "보정할 텍스트가 없습니다. 먼저 OCR 결과를 만드세요."); return
        self.status.set("AI 준비 중…"); self.update()
        msg = aillm.check()
        if msg:
            self.status.set("AI 사용 불가"); messagebox.showwarning("AI 보정", msg); return
        self._ai_backup = draft
        img, t0 = self.img, time.time()
        self.btn_ai.config(text="AI 중단")

        def work(cancel, emit):
            return aillm.chat(aillm.correct_prompt(draft), img, on_token=emit, cancel=cancel,
                              num_predict=max(300, len(draft) * 3))

        def on_token(s):
            self.status.set(f"AI가 읽는 중… {time.time() - t0:.0f}초 · {len(s)}자")

        def finish():
            self._ai_cancel = None
            self.btn_ai.config(text="AI로 보정 (로고·작은 글자·오인식)")

        def on_done(res):
            finish()
            fixed = aillm.clean_answer(res)
            if not fixed:
                self.status.set("AI가 빈 결과를 돌려줬습니다. 원문을 유지합니다."); return
            old = set(l.strip() for l in draft.splitlines())
            self.txt.delete("1.0", "end")
            n = 0
            for line in fixed.splitlines():
                changed = line.strip() not in old and line.strip() != ""
                self.txt.insert("end", line + "\n", ("chg",) if changed else ())
                n += changed
            self.btn_undo.config(state="normal")
            self.status.set(f"AI 보정 완료 · {time.time() - t0:.0f}초 · 바뀐/추가된 줄 {n}개(노란색) — 확인 후 사용하세요")
            if self.auto_copy.get():
                self.clipboard_clear(); self.clipboard_append(fixed); self.update()

        def on_error(ex):
            finish()
            self.status.set(f"AI 보정 실패: {ex}")

        self._ai_cancel = aillm.run_async(self, work, on_token, on_done, on_error)

    def ai_undo(self):
        b = getattr(self, "_ai_backup", None)
        if b is None:
            return
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", b)
        self.btn_undo.config(state="disabled")
        self.status.set("AI 보정 이전(OCR 원문)으로 되돌렸습니다")

    # ---------------------------------------------------------- 출력
    def copy_text(self):
        t = self.txt.get("1.0", "end").rstrip("\n")
        if not t:
            return
        self.clipboard_clear(); self.clipboard_append(t); self.update()
        self.status.set(f"{len(t)}자를 클립보드에 복사했습니다 ✔")

    def save_txt(self):
        t = self.txt.get("1.0", "end").rstrip("\n")
        if not t:
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("텍스트", "*.txt")], initialfile="추출_텍스트.txt")
        if out:
            with open(out, "w", encoding="utf-8-sig", newline="\r\n") as f:      # 메모장/엑셀에서 한글이 안 깨지게 BOM 포함
                f.write(t + "\n")
            messagebox.showinfo("저장", f"저장했습니다.\n{out}")

    def pick_region(self):
        if self.img is None:
            messagebox.showinfo("영역 다시 읽기", "먼저 이미지를 가져오세요."); return
        scale = self.ocr_scale.get() if self.ocr_scale.get() in ("2.0", "3.0", "4.0") else "3.0"
        TextPicker(self.winfo_toplevel(), self._prepare_for_ocr(self.img), scale, self.ocr_sharp.get(),
                   url_tools=False, lang=self._ocr_lang())
