"""캡처 이미지에서 드래그한 부분만 OCR해서 텍스트로 뽑아 복사하는 창.
(스냅 도구의 '텍스트 선택'과 비슷하게 URL/숫자/문구 하나만 필요할 때 쓴다. 100% 로컬)"""
import re
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

import core
import config
import tablegrid
import urlfix
import urlrec


class TextPicker(tk.Toplevel):
    def __init__(self, master, img: Image.Image, scale: str = "4.0", sharp: bool = True,
                 url_tools: bool = True, lang: str = "ko"):
        """url_tools=False: 단축 URL 전용 도구(URL 추출·접속 확인·URL 보정)를 숨기고, 선택한 영역을 일반 텍스트로만 읽는다
        (텍스트 캡쳐하기 메뉴에서 쓴다). lang: OCR 언어 태그."""
        super().__init__(master)
        self.url_tools, self.lang = url_tools, lang
        self.title("이미지에서 텍스트 선택 — 드래그한 부분을 OCR해서 복사합니다")
        self.geometry("1200x800")
        try:
            self.state("zoomed")                       # 화면에 꽉 차게 (이미지를 많이 보이도록)
        except tk.TclError:
            pass
        self.img = img
        self._photo = None
        self._rect = None
        self.ocr_scale = tk.StringVar(value=scale)
        self.sharp = tk.BooleanVar(value=sharp)
        self.join = tk.BooleanVar(value=False)
        self.fix = tk.BooleanVar(value=True)
        self.verify_net = tk.BooleanVar(value=True)        # 상시 켜짐 (사용자 요청). 끄면 ID가 서버로 나가지 않는다
        self._last_box = None
        self.copy_mode = tk.StringVar(value="url")         # 'url' = URL만, 'full' = 전체
        self.which = tk.StringVar(value=urlrec.WHICH[0])
        self.skip_failed = tk.BooleanVar(value=False)
        self._recs, self._verified = [], {}
        self.auto_copy = tk.BooleanVar(value=True)
        self.zoom = tk.StringVar(value="100%")
        self._ui()
        self._render()

    def _ui(self):
        bar = ttk.Frame(self, padding=4); bar.pack(fill="x")
        ttk.Label(bar, text="OCR 배율").pack(side="left")
        ttk.Combobox(bar, textvariable=self.ocr_scale, values=["2.0", "3.0", "4.0"], width=4,
                     state="readonly").pack(side="left", padx=(2, 6))
        ttk.Checkbutton(bar, text="선명화", variable=self.sharp).pack(side="left")
        ttk.Checkbutton(bar, text="줄바꿈 이어붙이기(URL)" if self.url_tools else "줄바꿈을 공백으로 이어붙이기",
                        variable=self.join).pack(side="left", padx=6)
        if self.url_tools:
            ttk.Checkbutton(bar, text="URL 자동 보정", variable=self.fix).pack(side="left")
        ttk.Checkbutton(bar, text="선택하면 바로 복사", variable=self.auto_copy).pack(side="left")
        ttk.Label(bar, text="보기").pack(side="left", padx=(12, 2))
        z = ttk.Combobox(bar, textvariable=self.zoom, values=["50%", "75%", "100%", "150%", "200%"],
                         width=5, state="readonly")
        z.pack(side="left"); z.bind("<<ComboboxSelected>>", lambda _e: self._render())

        ttk.Button(bar, text="전체 선택 (이미지 전체 OCR)", command=self.run_all).pack(side="left", padx=(12, 0))
        if self.url_tools:
            bar2 = ttk.Frame(self, padding=(4, 0)); bar2.pack(fill="x")
            ttk.Button(bar2, text="① URL 추출·검증 (선택 영역, 없으면 전체)", command=self.run_urls).pack(side="left")
            ttk.Checkbutton(bar2, text=f"I/l 접속 확인 (단축 URL ID를 {config.SHORT_HOST}으로 전송)",
                            variable=self.verify_net).pack(side="left", padx=8)
            ttk.Button(bar2, text="선택 해제(전체로)", command=self._clear_sel).pack(side="left")
            bar3 = ttk.Frame(self, padding=(4, 2)); bar3.pack(fill="x")
            ttk.Label(bar3, text="② 복사 형식").pack(side="left")
            ttk.Radiobutton(bar3, text="URL만", value="url", variable=self.copy_mode,
                            command=self._render_recs).pack(side="left", padx=(6, 0))
            c = ttk.Combobox(bar3, textvariable=self.which, values=list(urlrec.WHICH), width=9, state="readonly")
            c.pack(side="left", padx=(2, 8)); c.bind("<<ComboboxSelected>>", lambda _e: self._render_recs())
            ttk.Radiobutton(bar3, text="전체 (순번 | 원본 | 단축 | 확인필요)", value="full", variable=self.copy_mode,
                            command=self._render_recs).pack(side="left")
            ttk.Checkbutton(bar3, text="접속 확인 실패 행 제외", variable=self.skip_failed,
                            command=self._render_recs).pack(side="left", padx=10)
            ttk.Label(bar3, text="(형식을 바꾸면 재인식 없이 바로 다시 복사됩니다)", foreground="gray").pack(side="left")
        else:
            bar2 = ttk.Frame(self, padding=(4, 0)); bar2.pack(fill="x")
            ttk.Button(bar2, text="선택 해제", command=self._clear_sel).pack(side="left")
            ttk.Label(bar2, text="이미지에서 드래그한 부분만 읽어 아래 상자에 넣고 복사합니다. "
                                 "여러 번 드래그하면 마지막 결과로 바뀝니다.", foreground="gray").pack(side="left", padx=8)

        # 아래쪽 영역(텍스트 상자)을 먼저 배치해야 창이 작아져도 잘리지 않는다
        bot = ttk.LabelFrame(self, text="인식된 텍스트 (수정 가능)", padding=4)
        bot.pack(side="bottom", fill="x", padx=4, pady=4)
        self.txt = tk.Text(bot, height=6, wrap="word")
        tys = ttk.Scrollbar(bot, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=tys.set)
        side = ttk.Frame(bot); side.pack(side="right", padx=6)
        ttk.Button(side, text="복사", command=self.copy).pack(fill="x")
        ttk.Button(side, text="전체 선택(텍스트)", command=lambda: self.txt.tag_add("sel", "1.0", "end")).pack(fill="x", pady=2)
        self.msg = ttk.Label(side, text="", foreground="#444"); self.msg.pack()
        tys.pack(side="right", fill="y"); self.txt.pack(side="left", fill="x", expand=True)

        mid = ttk.Frame(self); mid.pack(side="top", fill="both", expand=True)
        xs_frame = ttk.Frame(mid); xs_frame.pack(side="bottom", fill="x")
        self.cv = tk.Canvas(mid, bg="#888", highlightthickness=0, cursor="crosshair")
        ys = ttk.Scrollbar(mid, orient="vertical", command=self.cv.yview)
        xs = ttk.Scrollbar(xs_frame, orient="horizontal", command=self.cv.xview)
        self.cv.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.pack(fill="x"); ys.pack(side="right", fill="y")
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", self._up)
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(-3 * (e.delta // 120), "units"))
        self.cv.bind("<Shift-MouseWheel>", lambda e: self.cv.xview_scroll(-3 * (e.delta // 120), "units"))

    # ------------------------------------------------------------ 화면
    def _clear_sel(self):
        self._last_box = None
        if self._rect:
            self.cv.delete(self._rect); self._rect = None
        self.msg.config(text="선택 해제됨")

    def _z(self) -> float:
        return int(self.zoom.get().rstrip("%")) / 100

    def _render(self):
        z = self._z()
        im = self.img if z == 1 else self.img.resize((max(1, int(self.img.width * z)),
                                                      max(1, int(self.img.height * z))))
        self._photo = ImageTk.PhotoImage(im)
        self.cv.delete("all")
        self.cv.create_image(0, 0, image=self._photo, anchor="nw")
        self.cv.configure(scrollregion=(0, 0, im.width, im.height))
        self._rect = None

    def _down(self, e):
        self._p0 = (self.cv.canvasx(e.x), self.cv.canvasy(e.y))
        if self._rect:
            self.cv.delete(self._rect)
        self._rect = self.cv.create_rectangle(*self._p0, *self._p0, outline="red", width=2)

    def _move(self, e):
        # 가장자리 근처로 드래그하면 자동 스크롤 (긴 이미지의 아래쪽까지 한 번에 선택)
        h, w = self.cv.winfo_height(), self.cv.winfo_width()
        if e.y > h - 25:
            self.cv.yview_scroll(2, "units")
        elif e.y < 25:
            self.cv.yview_scroll(-2, "units")
        if e.x > w - 25:
            self.cv.xview_scroll(2, "units")
        elif e.x < 25:
            self.cv.xview_scroll(-2, "units")
        self.cv.coords(self._rect, *self._p0, self.cv.canvasx(e.x), self.cv.canvasy(e.y))

    def run_urls(self):
        """선택한 영역(없으면 이미지 전체)에서 레코드별 원본 URL/단축 URL을 뽑아 엑셀 3열 TSV로 복사한다.
        '접속 확인'을 켜면 I/l 후보를 단축 URL 서버로 확인해 확정한다."""
        from tkinter import messagebox
        b = self._last_box or (0, 0, self.img.width, self.img.height)
        x1, y1 = max(0, b[0]), max(0, b[1])
        x2, y2 = min(self.img.width, b[2]), min(self.img.height, b[3])
        crop = self.img.crop((x1, y1, x2, y2))
        self.msg.config(text="URL용 OCR 중…"); self.update()
        try:
            words = tablegrid.ocr_tall(crop, scale=4.0, sharp=True,
                                       progress=lambda s: (self.msg.config(text="URL용 " + s), self.update()))
        except Exception as ex:
            self.msg.config(text="OCR 실패"); messagebox.showerror("OCR 실패", str(ex)); return
        recs = urlrec.extract(words, crop, tablegrid.row_boundaries(crop))
        if not recs:
            self.msg.config(text="URL 없음")
            messagebox.showinfo("URL 추출", "URL을 찾지 못했습니다.\n원본 URL이 시작되는 왼쪽 끝부터 선택하거나 전체 선택을 쓰세요.")
            return
        verified = {}
        if self.verify_net.get() and urlrec.confirm_send(len([r for r in recs if r["id"] and r["origin"]])):
            verified = urlrec.verify_all(recs, pump=self.update,
                                         progress=lambda s: (self.msg.config(text=s), self.update()))
        self._recs, self._verified = recs, verified
        self._render_recs(popup=True)

    def _render_recs(self, popup: bool = False):
        """보관 중인 추출·검증 결과를 현재 복사 형식으로 텍스트 상자에 보여주고 복사한다.
        (재OCR·재접속 없이 형식만 바꿔 다시 복사할 수 있다)"""
        from tkinter import messagebox
        if not self._recs:
            self.msg.config(text="먼저 'URL 추출·검증'을 누르세요"); return
        recs = self._recs
        if self.skip_failed.get() and self._verified:
            recs = [r for r in recs if self._verified.get(id(r)) not in ("불일치", "접속 불가")]
        if not recs:
            self.msg.config(text="복사할 행이 없습니다"); return
        tsv, info, nflag = urlrec.format_records(recs, self._verified, self.copy_mode.get(), self.which.get())
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", tsv.rstrip("\r\n"))
        self.clipboard_clear(); self.clipboard_append(tsv); self.update()
        self.msg.config(text=f"{len(recs)}건 복사 ✔ (확인 필요 {nflag})")
        if popup:
            messagebox.showinfo("URL 추출", info)

    def run_all(self):
        """이미지 전체를 OCR한다 (스크롤/배율 조정 없이 전체 텍스트가 필요할 때)."""
        return self.run((0, 0, self.img.width, self.img.height))

    def _up(self, e):
        x0, y0 = self._p0
        x1, y1 = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        z = self._z()
        box = (int(min(x0, x1) / z), int(min(y0, y1) / z), int(max(x0, x1) / z), int(max(y0, y1) / z))
        if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:
            self._last_box = box
            self.run(box)

    # ------------------------------------------------------------ OCR
    def run(self, box) -> str:
        """box=(x1,y1,x2,y2) (원본 이미지 좌표) 부분만 OCR해서 텍스트 상자에 넣는다."""
        x1, y1 = max(0, box[0]), max(0, box[1])
        x2, y2 = min(self.img.width, box[2]), min(self.img.height, box[3])
        crop = self.img.crop((x1, y1, x2, y2))
        pad = 16                                           # 가장자리에 걸린 글자 인식률을 위해 여백
        padded = Image.new("RGB", (crop.width + 2 * pad, crop.height + 2 * pad), crop.getpixel((0, 0)))
        padded.paste(crop, (pad, pad))
        self.msg.config(text="OCR 중…"); self.update()
        try:
            if self.url_tools:
                words = tablegrid.ocr_tall(padded, scale=float(self.ocr_scale.get()), sharp=self.sharp.get(),
                                           lang=self.lang)
            else:                                            # 일반 텍스트: 여러 설정으로 읽어 줄마다 가장 좋은 결과를 쓴다
                import ocrplus
                words = ocrplus.read_words(padded, scale=float(self.ocr_scale.get()), sharp=self.sharp.get(),
                                           lang=self.lang,
                                           progress=lambda s: (self.msg.config(text=s), self.update()))
        except Exception as ex:
            self.msg.config(text="OCR 실패"); self.txt.delete("1.0", "end"); self.txt.insert("1.0", str(ex))
            return ""
        # 단축 URL만 선택한 경우: 깨진 접두어('http:〃Short.example')를 바로잡고, 접속 확인이 켜져 있으면 I/l까지 확정한다.
        # (일반 OCR 원문을 그대로 복사하면 정규화도 접속 확인도 거치지 않는다)
        if self.url_tools:
            recs = urlrec.extract(words, padded, [])
            if recs and all(not r["origin"] for r in recs) and any(r["id"] for r in recs):
                return self._short_only(recs)
        if not self.url_tools:      # 일반 텍스트: 열(카드·단)을 나눠 읽고, 영문 속 0/1 오인식을 보정한다
            import page_text
            text = page_text.compose_text(words, "한 줄로" if self.join.get() else "줄 그대로", True, True,
                                        bounds=ocrplus.last_bounds)
            lines = []
        else:
            lines = [" ".join(w[0] for w in line) for line in core.cluster_rows(words)]
            text = tablegrid._join_lines(lines) if self.join.get() else "\n".join(lines)
        if self.url_tools and self.join.get() and self.fix.get() and re.match(r"(?i)^h?t?tps?[:/]", text):
            text = urlfix.fix_origin_url(text)                  # 공백 제거 + www/zf_user/utm_* 등 보정
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", text)
        if self.auto_copy.get():
            self.copy(quiet=True)
        else:
            self.msg.config(text="")
        return text

    def _short_only(self, recs: list) -> str:
        """선택 영역이 단축 URL뿐일 때: 'http://short.example/s/ID' 형식으로 정리하고 접속 확인(켜져 있으면)한다."""
        verified = {}
        if self.verify_net.get() and urlrec.confirm_send(len(recs)):
            self.msg.config(text="단축 URL 접속 확인 중…"); self.update()
            verified = urlrec.verify_all(recs, pump=self.update)
        text = "\n".join(r["short"] for r in recs if r["short"])
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", text)
        ok = sum(1 for r in recs if verified.get(id(r)) in ("확정됨", "확인됨"))
        todo = [r for r in recs if r["short"] and verified.get(id(r)) not in ("확정됨", "확인됨")]
        if verified:
            info = f"단축 URL {len(recs)}개 · 접속 확인 {ok}/{len(recs)}"
            if todo:
                info += f" · 확인 필요 {len(todo)}개(ID 대조)"
        else:
            amb = sum(1 for r in recs if r["ambiguous"])
            info = f"단축 URL {len(recs)}개 · 접속 확인 꺼짐" + (f" · I/l 모호 {amb}개" if amb else "")
        if self.auto_copy.get():
            self.clipboard_clear(); self.clipboard_append(text); self.update()
        self.msg.config(text=info)
        return text

    def copy(self, quiet: bool = False):
        t = self.txt.get("1.0", "end").rstrip("\n")
        self.clipboard_clear(); self.clipboard_append(t); self.update()
        self.msg.config(text="복사됨 ✔" if t else "")
