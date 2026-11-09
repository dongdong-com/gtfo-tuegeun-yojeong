"""운영 > Data&Url캡쳐 > 단축URL 캡처.
영역을 지정하면 자동으로 아래로 스크롤하며 캡처해 한 장으로 이어붙이고,
표 데이터(OCR)는 엑셀에 붙여넣거나 저장, 이미지는 엑셀에 그림으로 붙여넣을 수 있다.
VDI/원격 화면은 UI 요소에 접근할 수 없으므로 화면 픽셀만 사용한다.

단축URL 전용 도구(URL 추출·접속 확인, 텍스트 선택)는 URL_TOOLS 로 켜고 끈다.
page_dci.DciTablePage 가 이 클래스를 상속해 일반 표 → 엑셀 행/열 기능으로 쓴다."""
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import capture_tip
import clipfmt
import scrollcap
import config
import tablegrid
import ui_common
import shortverify
import urlrec
from text_picker import TextPicker


class VdiTablePage(ttk.Frame):
    TITLE = "단축URL 캡처"
    URL_TOOLS = True          # 단축URL 전용 도구(레코드 병합, URL 복사, 접속 확인, 텍스트 선택) 표시
    OCR_TILE = False          # 넓은 이미지를 가로 타일로 나눠 지정 배율대로 읽을지 (일반 표 페이지에서 켬)
    FLAG_CELLS = False        # 복사할 때 불확실한 셀을 엑셀에서 노란색으로 표시할지 (일반 표 페이지에서 켬)
    DEFAULT_SCALE = "4.0"     # 작은 URL/영문 글자는 4.0배+선명화가 가장 정확
    INTRO = "영역을 지정하면 자동으로 스크롤하며 캡처합니다."
    HINT = ("※ 시작 위치(영역 위쪽)부터 끝까지 캡처합니다. 영역이 화면보다 짧아도 끝에서 아래쪽 내용을 자동으로 이어붙입니다. "
            "캡처 중 마우스를 움직이지 마세요(매 스크롤마다 영역 중앙으로 되돌립니다). ESC = 중단.")

    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.img: Image.Image | None = None
        self.words: list = []
        self._photo = None
        self.mode = tk.StringVar(value="마우스 휠")
        self.notches = tk.IntVar(value=2)
        self.delay = tk.IntVar(value=1000)
        self.max_steps = tk.IntVar(value=100)
        self.to_top = tk.BooleanVar(value=True)
        self.click_focus = tk.BooleanVar(value=False)
        self.include_tail = tk.BooleanVar(value=True)
        self.gap = tk.DoubleVar(value=1.0)
        self.fix_dots = tk.BooleanVar(value=False)
        self.merge_lines = tk.BooleanVar(value=True)
        self.verify_net = tk.BooleanVar(value=True)       # 상시 켜짐 (사용자 요청). 끄면 ID가 서버로 나가지 않는다
        self.bounds: list = []
        self.ocr_scale = tk.StringVar(value=self.DEFAULT_SCALE)
        self.ocr_sharp = tk.BooleanVar(value=True)
        self.with_image = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value=self.INTRO)
        self._init_extra()
        self._ui()

    def _init_extra(self):
        """하위 페이지가 추가 변수를 만드는 자리 (UI를 만들기 전에 호출된다)."""

    def _prepare_for_ocr(self, img):
        """OCR에 넣기 전에 이미지를 가공하는 자리 (좌표는 바뀌면 안 된다). 하위 페이지가 바꿔 쓴다."""
        return img

    def _ocr_lang(self) -> str:
        """OCR 언어 태그. 하위 페이지(텍스트 캡쳐하기)가 선택한 언어로 바꿔 쓴다."""
        return "ko"

    def _extra_flags(self, table) -> set:
        """복사할 때 엑셀에서 노란색으로 표시할 셀을 하위 페이지가 더하는 자리 (예: AI가 숫자를 바꾼 셀)."""
        return set()

    def _extra_bar(self, bar, bar2):
        """하위 페이지가 표 옵션 줄(bar, bar2)에 컨트롤을 더하는 자리."""

    # ---------------------------------------------------------- UI
    def _ui(self):
        top = ttk.LabelFrame(self, text="① 스크롤 캡처", padding=6)
        top.pack(fill="x", padx=6, pady=6)
        btns = ttk.Frame(top); btns.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ttk.Button(btns, text="영역 지정 + 자동 스크롤 캡처", command=self.start).pack(fill="x")
        ttk.Button(btns, text="영역 지정 캡처 (스크롤 없음)", command=self.snap).pack(fill="x", pady=(4, 0))
        opts = [("스크롤", ttk.Combobox(top, textvariable=self.mode, values=["마우스 휠", "PageDown 키"],
                                      width=11, state="readonly")),
                ("휠 칸 수/회", ttk.Spinbox(top, from_=1, to=20, textvariable=self.notches, width=4)),
                ("스크롤 후 대기(ms)", ttk.Spinbox(top, from_=100, to=5000, increment=100, textvariable=self.delay, width=6)),
                ("최대 횟수", ttk.Spinbox(top, from_=1, to=500, textvariable=self.max_steps, width=5))]
        for i, (label, w) in enumerate(opts):
            ttk.Label(top, text=label).grid(row=0, column=1 + 2 * i, padx=(6, 2))
            w.grid(row=0, column=2 + 2 * i)
        ttk.Checkbutton(top, text="시작 전 맨 위로 이동", variable=self.to_top).grid(row=1, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Checkbutton(top, text="시작 전 영역 중앙 클릭(포커스)", variable=self.click_focus).grid(row=1, column=4, columnspan=3, sticky="w")
        ttk.Checkbutton(top, text="끝에서 영역 아래쪽 내용도 포함", variable=self.include_tail).grid(row=1, column=7, columnspan=3, sticky="w")
        ttk.Label(top, text=self.HINT, foreground="gray").grid(row=2, column=0, columnspan=9, sticky="w", pady=(4, 0))

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=6)
        pv = ttk.LabelFrame(mid, text="캡처 이미지 (축소)", padding=4)
        pv.pack(side="left", fill="y")
        self.cv = tk.Canvas(pv, width=300, height=330, bg="#E3EFFD", highlightthickness=0)
        sb = ttk.Scrollbar(pv, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="y"); sb.pack(side="left", fill="y")

        rt = ttk.LabelFrame(mid, text="② 표 데이터 (탭 구분 — 직접 수정 가능, 엑셀에 그대로 붙여넣기)", padding=4)
        rt.pack(side="left", fill="both", expand=True, padx=(8, 0))
        bar = ttk.Frame(rt); bar.pack(fill="x")
        ttk.Label(bar, text="열 간격 민감도").pack(side="left")
        sc = ttk.Scale(bar, from_=0.3, to=3.0, variable=self.gap, length=120)
        sc.pack(side="left", padx=4)
        sc.bind("<ButtonRelease-1>", lambda _e: self.rebuild())       # 놓으면 바로 열 다시 나눔
        ttk.Checkbutton(bar, text="숫자 점→콤마", variable=self.fix_dots, command=self.rebuild).pack(side="left", padx=6)
        if self.URL_TOOLS:
            ttk.Checkbutton(bar, text="여러 줄 셀 합치기", variable=self.merge_lines, command=self.rebuild).pack(side="left")
        bar2 = ttk.Frame(rt); bar2.pack(fill="x", pady=(4, 0))               # 폭이 좁아도 잘리지 않게 두 줄로
        ttk.Label(bar2, text="OCR 배율").pack(side="left")
        ttk.Combobox(bar2, textvariable=self.ocr_scale, values=["1.5", "2.0", "3.0", "4.0"], width=4,
                     state="readonly").pack(side="left", padx=(4, 0))
        ttk.Checkbutton(bar2, text="선명화", variable=self.ocr_sharp).pack(side="left", padx=8)
        ttk.Button(bar2, text="OCR 다시", command=self.reocr).pack(side="left")
        self._extra_bar(bar, bar2)
        self.txt = tk.Text(rt, wrap="none", height=14, undo=True, font=("Consolas", 10))
        xs = ttk.Scrollbar(rt, orient="horizontal", command=self.txt.xview)
        ys = ttk.Scrollbar(rt, orient="vertical", command=self.txt.yview)
        self.txt.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        ys.pack(side="right", fill="y"); xs.pack(side="bottom", fill="x")
        self.txt.pack(fill="both", expand=True, pady=4)

        out = ttk.Frame(self, padding=6); out.pack(fill="x")
        row0 = ttk.Frame(out); row0.pack(fill="x")
        ttk.Label(row0, textvariable=self.status, foreground="#5A4A4F").pack(side="left")
        if self.URL_TOOLS:
            ttk.Checkbutton(row0, text=f"I/l 접속 확인 (단축 URL ID를 {config.SHORT_HOST}으로 전송)",
                            variable=self.verify_net).pack(side="right")
        row1 = ttk.Frame(out); row1.pack(fill="x", pady=(4, 0))
        ttk.Button(row1, text="표 데이터 복사 (엑셀 붙여넣기)", command=self.copy_table).pack(side="left")
        ttk.Button(row1, text="이미지 복사 (엑셀에 그림으로)", command=self.copy_image).pack(side="left", padx=4)
        if self.URL_TOOLS:
            ttk.Button(row1, text="URL 복사 (원본↔단축, 엑셀 열)", command=self.copy_urls).pack(side="left")
            ttk.Button(row1, text="이미지에서 텍스트 선택…", command=self.pick_text).pack(side="left", padx=4)
        ttk.Button(row1, text="PNG 저장", command=self.save_png).pack(side="right")
        ttk.Button(row1, text="인쇄…", command=self.print_image).pack(side="right", padx=4)
        ttk.Button(row1, text="엑셀로 저장", command=self.save_xlsx).pack(side="right", padx=4)
        ttk.Checkbutton(row1, text="이미지 시트 포함", variable=self.with_image).pack(side="right")

    # ---------------------------------------------------------- 캡처
    def start(self):
        root = self.winfo_toplevel()
        root.withdraw(); root.update(); time.sleep(0.25)
        cursor = scrollcap.get_cursor()
        info = img = None
        logs: list[str] = []
        tip = None
        try:
            box = ui_common.select_region(root)
            if box:
                time.sleep(0.3)
                p = scrollcap.Params(
                    mode="pagedown" if self.mode.get().startswith("Page") else "wheel",
                    notches=max(1, self.notches.get()), delay=max(0.1, self.delay.get() / 1000),
                    max_steps=max(1, self.max_steps.get()), to_top=self.to_top.get(),
                    click_focus=self.click_focus.get(), include_tail=self.include_tail.get())
                try:                                 # 마우스 옆 안내 말풍선 (캡처 이미지에는 찍히지 않음). 실패해도 캡처는 계속
                    tip = capture_tip.CaptureTip(root)
                    tip.install_grab_hook(scrollcap)
                except Exception:
                    tip = None

                def pump():
                    root.update()
                    if tip:
                        tip.tick()

                def log(s):
                    logs.append(s)
                    if tip:
                        tip.on_log(s)

                img, info = scrollcap.capture_scroll(box, p, pump=pump, log=log)
        except Exception as ex:                      # 캡처 중 오류도 창은 복구해야 한다
            if tip:
                tip.close()
            root.deiconify(); messagebox.showerror("캡처 실패", str(ex)); return
        finally:
            if tip:
                tip.close()
            scrollcap.set_cursor(*cursor)
            root.deiconify()
        if img is None:
            return
        self.img = img
        self._preview()
        self.status.set(f"캡처 {info['frames']}장 → {img.width}×{img.height}px · {info['reason']} · OCR 중…")
        self.update()
        log_path = self._save_scroll_log(logs)
        if info["reason"].startswith("스크롤이 반응"):
            tail = "\n".join(logs[-8:])
            messagebox.showwarning("스크롤이 되지 않았습니다",
                                   info["reason"] + "\n\n지금 화면(스크롤 전)만 캡처되었습니다.\n\n[진단 로그]\n" + tail +
                                   f"\n\n전체 로그: {log_path}")
        head = self.status.get().split(" · OCR")[0]
        if info["steps"] > 0:
            head = head.replace(f"{info['frames']}장", f"{info['frames']}장({info['method']})", 1)
        self.status.set(head + " · OCR 중…")
        if self.reocr():
            self.status.set(head + f" · {self._rows()}행 인식")
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass

    def _save_scroll_log(self, logs: list) -> str:
        """스크롤 캡처 진단 로그를 GTFO 폴더의 scroll_capture.log 에 저장한다 (마지막 실행 1회분).
        스크롤이 안 될 때 이 파일 내용을 보면 원인(창 활성화, 입력 전달 여부)을 알 수 있다."""
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scroll_capture.log")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {self.TITLE}\n" + "\n".join(logs) + "\n")
        except OSError:
            pass
        return path

    def snap(self):
        """영역만 지정해서 현재 화면을 한 장 캡처한다 (스크롤 없음). 이후 처리는 스크롤 캡처와 같다."""
        root = self.winfo_toplevel()
        root.withdraw(); root.update(); time.sleep(0.25)
        img = None
        try:
            box = ui_common.select_region(root)
            if box:
                time.sleep(0.3)
                img = scrollcap._grab(box)
        except Exception as ex:
            root.deiconify(); messagebox.showerror("캡처 실패", str(ex)); return
        finally:
            root.deiconify()
        if img is None:
            return
        self.img = img
        self._preview()
        self.status.set(f"캡처 {img.width}×{img.height}px · OCR 중…")
        self.update()
        if self.reocr():
            self.status.set(f"캡처 {img.width}×{img.height}px · {self._rows()}행 인식")
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass

    def pick_text(self):
        if self.img is None:
            messagebox.showinfo("텍스트 선택", "먼저 화면을 캡처하세요."); return
        TextPicker(self.winfo_toplevel(), self.img, self.ocr_scale.get() if self.ocr_scale.get() in ("3.0", "4.0") else "4.0",
                   True)

    def copy_urls(self):
        """레코드별로 원본 URL / 단축 URL을 조립해 엑셀 2열(+확인필요 열)로 복사한다.
        URL은 4.0배율+선명화 OCR이 가장 정확하므로 다른 설정으로 읽었다면 URL용으로 한 번 더 읽는다."""
        if self.img is None:
            messagebox.showinfo("URL 복사", "먼저 화면을 캡처하세요."); return
        words = self.words
        if getattr(self, "_ocr_cfg", None) != (4.0, True):
            self.status.set("URL용 OCR 중…"); self.update()
            try:
                words = tablegrid.ocr_tall(self.img, scale=4.0, sharp=True,
                                           progress=lambda s: (self.status.set("URL용 " + s), self.update()))
            except Exception as ex:
                messagebox.showerror("OCR 실패", str(ex)); return
        bounds = self.bounds if self.merge_lines.get() else None
        recs = urlrec.extract(words, self.img, bounds)
        if not recs:
            messagebox.showinfo("URL 복사", "URL을 찾지 못했습니다."); return
        verified = {}
        if self.verify_net.get() and urlrec.confirm_send(len([r for r in recs if r["id"] and r["origin"]])):
            verified = urlrec.verify_all(recs, pump=self.update,
                                         progress=lambda s: (self.status.set(s), self.update()))
        tsv, msg, nflag = urlrec.format_records(recs, verified)
        self.clipboard_clear(); self.clipboard_append(tsv); self.update()
        self.status.set(f"URL {len(recs)}건 복사 (확인 필요 {nflag}건)")
        messagebox.showinfo("URL 복사", msg)

    def _ocr_words(self, img, progress=None):
        return tablegrid.ocr_tall(img, progress=progress, scale=float(self.ocr_scale.get()),
                                  sharp=self.ocr_sharp.get(), tile=self.OCR_TILE, lang=self._ocr_lang())

    def reocr(self):
        """저장된 캡처 이미지를 현재 OCR 배율/선명화 설정으로 다시 인식한다 (재캡처 불필요)."""
        if self.img is None:
            return False
        self.bounds = tablegrid.row_boundaries(self.img)
        try:
            self.words = self._ocr_words(self._prepare_for_ocr(self.img),
                                         progress=lambda s: (self.status.set(s), self.update()))
            self._ocr_cfg = (float(self.ocr_scale.get()), bool(self.ocr_sharp.get()))
        except Exception as ex:
            messagebox.showerror("OCR 실패", str(ex)); return False
        self.rebuild()
        return True

    def _preview(self):
        w = 300
        scale = w / self.img.width if self.img.width > w else 1.0
        th = self.img.resize((int(self.img.width * scale), max(1, int(self.img.height * scale))))
        self._photo = ImageTk.PhotoImage(th)
        self.cv.delete("all")
        self.cv.create_image(0, 0, image=self._photo, anchor="nw")
        self.cv.configure(scrollregion=(0, 0, th.width, th.height))

    def rebuild(self):
        """저장된 OCR 단어로 열 간격만 바꿔 표를 다시 만든다 (재캡처 불필요)."""
        if not self.words:
            return
        table, mode = self._make_table()
        if self.fix_dots.get():
            table = tablegrid.fix_dot_thousands(table)
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", tablegrid.to_tsv(table))
        self.status.set(f"{len(table)}행 × {max((len(r) for r in table), default=0)}열 ({mode})")

    def _make_table(self):
        """OCR 단어 → (표, 설명). 하위 페이지가 바꿔 쓴다."""
        bounds = self.bounds if self.merge_lines.get() else None
        table = tablegrid.build_table(self.words, self.gap.get(), bounds)
        if self.URL_TOOLS:      # 깨진 단축 URL 접두어('http:〃Short.example')와 '복사하기' 버튼 글자를 정리 (I/l 확정은 URL 복사가 한다)
            table = [[urlrec.normalize_short_text(c) for c in row] for row in table]
        return table, ("레코드 단위" if bounds else "줄 단위")

    def _rows(self):
        return len([l for l in self.txt.get("1.0", "end").splitlines() if l.strip()])

    def _table(self):
        return tablegrid.from_tsv(self.txt.get("1.0", "end").rstrip("\n"))

    # ---------------------------------------------------------- 출력
    def copy_table(self):
        t = self._table()
        if not t:
            return
        # 텍스트(탭 구분) + HTML 서식을 함께 넣는다. 엑셀이 날짜의 초를 숨기거나 앞자리 0을 지우지 않게 한다.
        flags = (tablegrid.uncertain_cells(t) | self._extra_flags(t)) if self.FLAG_CELLS else set()
        try:
            clipfmt.set_clipboard(tablegrid.to_tsv(t, "\r\n") + "\r\n", clipfmt.table_html(t, flags))
        except Exception:
            self.clipboard_clear(); self.clipboard_append(tablegrid.to_tsv(t, "\r\n") + "\r\n"); self.update()
        msg = (f"표 {len(t)}행을 복사했습니다.\n엑셀에서 Ctrl+V 하세요.\n"
               "(날짜/시간은 초까지 표시되는 날짜 값으로, 앞이 0인 숫자는 텍스트로 붙습니다)")
        if flags:
            msg += (f"\n\n확인이 필요한 셀 {len(flags)}개는 엑셀에서 연노랑 배경으로 표시됩니다.\n"
                    "(이상한 글자, 형식이 깨진 날짜, 길이가 다른 고유번호)")
        messagebox.showinfo("복사", msg)

    def print_image(self):
        """캡처 이미지를 인쇄한다: 옵션 창(맞춤 방식·용지 방향·바닥글) → 미리보기 또는 프린터 선택 후 인쇄."""
        if self.img is None:
            messagebox.showinfo("인쇄", "먼저 화면을 캡처하거나 이미지를 가져오세요."); return
        import printing
        printing.PrintDialog(self.winfo_toplevel(), self.img, f"퇴근요정 - {self.TITLE}")

    def copy_image(self):
        if self.img is None:
            return
        try:
            scrollcap.copy_image_to_clipboard(self.img)
        except Exception as ex:
            messagebox.showerror("복사 실패", str(ex)); return
        messagebox.showinfo("복사", "이미지를 복사했습니다.\n엑셀에서 Ctrl+V 하면 그림으로 붙습니다.")

    def save_xlsx(self):
        t = self._table()
        if not t:
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                           initialfile="VDI_테이블.xlsx")
        if out:
            tablegrid.save_xlsx(out, t, self.img if self.with_image.get() else None)
            messagebox.showinfo("저장", f"저장했습니다.\n{out}")

    def save_png(self):
        if self.img is None:
            return
        out = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")],
                                           initialfile="VDI_캡처.png")
        if out:
            self.img.save(out)
            messagebox.showinfo("저장", f"저장했습니다.\n{out}")
