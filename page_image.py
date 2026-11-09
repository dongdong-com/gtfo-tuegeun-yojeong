"""운영 > AI캡쳐하기 > 이미지 캡쳐하기.
화면 영역/스크롤 캡처·이미지 파일·클립보드 이미지를 가져와서, 이 PC의 로컬 AI(Gemma 4 E2B)가 이미지를 보고
'프롬프트(텍스트)'를 만들어 준다. 이미지 생성 AI용 / 화면(UI) 구현용 / 설명(대체 텍스트) / 직접 지시.
이미지와 결과는 이 PC 밖으로 나가지 않는다. (캡처·가져오기·PNG 저장 등 공통 기능은 텍스트 캡쳐하기 페이지와 같다)"""
import time
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image

import aillm
from page_text import TextExtractPage

KINDS = list(aillm.IMAGE_PROMPTS.keys())


class ImagePromptPage(TextExtractPage):
    TITLE = "이미지 캡쳐하기"
    INTRO = ("화면 영역·스크롤 캡처, 이미지 파일, 클립보드 이미지를 가져온 뒤 '프롬프트 만들기'를 누르세요. "
             "이 PC의 로컬 AI가 이미지를 보고 프롬프트(텍스트)를 만듭니다.")

    def _init_extra(self):
        super()._init_extra()
        self.kind = tk.StringVar(value=KINDS[0])
        self.out_lang = tk.StringVar(value="한국어")
        self.custom = tk.StringVar()
        self.with_ocr = tk.BooleanVar(value=True)          # 작은 글자를 AI가 지어내지 않도록 OCR 글자를 참고로 함께 준다 (+4초)
        self._ai_cancel = None

    # ---------------------------------------------------------- UI
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
        ttk.Label(src, text="※ 캡처 중에는 마우스를 움직이지 마세요(ESC = 중단). 이미지와 결과는 이 PC 밖으로 나가지 않습니다.",
                  foreground="gray").grid(row=2, column=0, columnspan=8, sticky="w", pady=(4, 0))

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=6)
        pv = ttk.LabelFrame(mid, text="이미지 (축소)", padding=4)
        pv.pack(side="left", fill="y")
        self.cv = tk.Canvas(pv, width=300, height=340, bg="#E3EFFD", highlightthickness=0)
        sb = ttk.Scrollbar(pv, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="y"); sb.pack(side="left", fill="y")

        rt = ttk.LabelFrame(mid, text="② 만들어진 프롬프트 (직접 수정 가능)", padding=4)
        rt.pack(side="left", fill="both", expand=True, padx=(8, 0))
        r1 = ttk.Frame(rt); r1.pack(fill="x")
        ttk.Label(r1, text="만들 것").pack(side="left")
        ttk.Combobox(r1, textvariable=self.kind, values=KINDS, width=24, state="readonly").pack(side="left", padx=(4, 8))
        ttk.Label(r1, text="답 언어").pack(side="left")
        ttk.Combobox(r1, textvariable=self.out_lang, values=["한국어", "English"], width=8,
                     state="readonly").pack(side="left", padx=(4, 8))
        self.btn_ai = ttk.Button(r1, text="프롬프트 만들기", command=self.make_prompt)
        self.btn_ai.pack(side="left", padx=4)
        r2 = ttk.Frame(rt); r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="직접 지시").pack(side="left")
        ttk.Entry(r2, textvariable=self.custom, width=52).pack(side="left", padx=(4, 8))
        ttk.Checkbutton(r2, text="이미지 속 글자(OCR)도 참고로 전달", variable=self.with_ocr).pack(side="left")
        ttk.Label(rt, text="※ '직접 지시'를 고르면 위 입력칸의 지시문으로 이미지를 해석합니다(예: 이 표를 마크다운으로 바꿔줘). "
                           "이 PC의 CPU로 돌리므로 10~40초 걸립니다. AI 결과는 틀릴 수 있으니 확인 후 사용하세요.",
                  foreground="gray", wraplength=640, justify="left").pack(fill="x", pady=(4, 0))
        self.txt = tk.Text(rt, wrap="word", height=14, undo=True, font=("맑은 고딕", 10))
        ys = ttk.Scrollbar(rt, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True, pady=4)

        out = ttk.Frame(self, padding=6); out.pack(fill="x")
        ttk.Label(out, textvariable=self.status, foreground="#5A4A4F").pack(anchor="w")
        row = ttk.Frame(out); row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="프롬프트 복사", command=self.copy_text).pack(side="left")
        ttk.Button(row, text="텍스트 파일(.txt)로 저장", command=self.save_txt).pack(side="left", padx=4)
        ttk.Button(row, text="PNG 저장", command=self.save_png).pack(side="right")
        ttk.Button(row, text="인쇄…", command=self.print_image).pack(side="right", padx=4)
        ttk.Button(row, text="이미지 복사", command=self.copy_image).pack(side="right", padx=4)

    # ---------------------------------------------------------- 가져오기 (OCR 없이 이미지만 보관)
    def reocr(self):
        """스크롤/영역 캡처가 끝나면 불리는 훅 — 이 페이지는 OCR을 하지 않고 안내만 갱신한다. False = 호출한 쪽이 상태문구를 덮어쓰지 않음."""
        if self.img is not None:
            self.status.set(f"이미지 {self.img.width}×{self.img.height}px · '프롬프트 만들기'를 누르세요")
        return False

    def _load(self, img: Image.Image, label: str):
        self.img = img.convert("RGB")
        self._preview()
        self.status.set(f"{label} {self.img.width}×{self.img.height}px · '프롬프트 만들기'를 누르세요")

    # ---------------------------------------------------------- 프롬프트 만들기
    def make_prompt(self):
        if self._ai_cancel is not None:                              # 실행 중이면 중단
            self._ai_cancel.set()
            return
        if self.img is None:
            messagebox.showinfo("프롬프트 만들기", "먼저 이미지를 가져오세요."); return
        try:
            prompt = aillm.image_prompt(self.kind.get(), self.out_lang.get(), self.custom.get())
        except aillm.AIError as ex:
            messagebox.showinfo("프롬프트 만들기", str(ex)); return
        self.status.set("AI 준비 중…"); self.update()
        msg = aillm.check()
        if msg:
            self.status.set("AI 사용 불가"); messagebox.showwarning("프롬프트 만들기", msg); return
        img, use_ocr, t0, lang = self.img, self.with_ocr.get(), time.time(), self._ocr_lang()   # tk 변수는 스레드 밖에서 읽는다
        self.btn_ai.config(text="중단")
        self.txt.delete("1.0", "end")

        def work(cancel, emit):
            p = prompt
            if use_ocr:
                import ocrplus
                import page_text
                emit("")
                words = ocrplus.read_words(img, lang=lang)
                ref = page_text.compose_text(words, "줄 그대로", True, True, True, ocrplus.last_bounds)
                if ref.strip():
                    p += "\n\n[참고: OCR이 읽은 이미지 속 글자 — 틀릴 수 있으니 이미지를 우선해라]\n" + ref
            return aillm.chat(p, img, on_token=emit, cancel=cancel, num_predict=1500)

        def show(s):
            self.txt.delete("1.0", "end"); self.txt.insert("1.0", s)
            self.status.set(f"AI가 쓰는 중… {time.time() - t0:.0f}초 · {len(s)}자")

        def finish():
            self._ai_cancel = None
            self.btn_ai.config(text="프롬프트 만들기")

        def on_done(res):
            finish()
            res = aillm.clean_answer(res)
            self.txt.delete("1.0", "end"); self.txt.insert("1.0", res)
            self.status.set(f"프롬프트 완성 · {time.time() - t0:.0f}초 · {len(res)}자 — 확인 후 사용하세요")
            if res and self.auto_copy.get():
                self.clipboard_clear(); self.clipboard_append(res); self.update()
                self.status.set(self.status.get() + " · 클립보드에 복사됨 ✔")

        def on_error(ex):
            finish()
            self.status.set(f"프롬프트 만들기 실패: {ex}")

        self._ai_cancel = aillm.run_async(self, work, show, on_done, on_error)
