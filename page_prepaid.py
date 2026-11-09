"""정산 > 포스티니 > 선급금/미지급금 처리 (PG 결제대금 입금 + 수수료 선급/미지급 분개)."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core
import ui_common


class PrepaidPage(ttk.Frame):
    TITLE = "선급금/미지급금 처리"
    # 구분 표시값 -> 내부 키
    SECTIONS = {"매월 8일 미지급금": "미지급금", "매월 22일 선급금": "선급금"}
    # 영림원 붙여넣기: 행번호~활동센터까지만 (관계회사·관리항목 제외, Invalid column index 방지)
    COPY_COLS = (0, 7)

    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx                       # ctx.template: 공용 양식 경로(StringVar)
        self.entries: list[core.Entry] = []
        self.section = tk.StringVar(value="매월 8일 미지급금")
        self.vendor = tk.StringVar(value="운세사주")
        self.ym = tk.StringVar(value="2026년 09월")
        self.f = {k: tk.StringVar() for k in ("mid", "period", "deposit", "sales", "fee", "vat")}
        self.msg = tk.StringVar()
        self.queue = []
        self._ui()

    # ---------------------------------------------------------- UI
    def _ui(self):
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Label(top, text="구분").pack(side="left")
        ttk.Combobox(top, textvariable=self.section, values=list(self.SECTIONS),
                     width=18, state="readonly").pack(side="left", padx=4)
        ttk.Label(top, text="거래처").pack(side="left")
        ttk.Entry(top, textvariable=self.vendor, width=12).pack(side="left", padx=4)
        ttk.Label(top, text="수수료 귀속월").pack(side="left")
        ttk.Entry(top, textvariable=self.ym, width=12).pack(side="left", padx=4)

        mid = ttk.Frame(self, padding=6); mid.pack(fill="x")
        left = ttk.LabelFrame(mid, text="① 캡처 → OCR 결과 (로컬)", padding=6)
        left.pack(side="left", fill="both", expand=True)
        ttk.Button(left, text="화면 영역 캡처 (OCR)", command=self.capture).pack(anchor="w")
        ttk.Label(left, text="※ 이니시스 통합정산내역조회 '조회내역' 표의 헤더+데이터 행만 좁게 드래그 (합계 행 제외).",
                  foreground="gray").pack(anchor="w")
        self.txt = tk.Text(left, height=11, width=46); self.txt.pack(fill="both", expand=True, pady=4)
        ttk.Button(left, text="텍스트에서 다시 추출", command=self.reparse).pack(anchor="w")

        right = ttk.LabelFrame(mid, text="② 값 확인/수정 (원 단위 숫자)", padding=6)
        right.pack(side="left", fill="y", padx=(8, 0))
        for i, (k, label) in enumerate([("mid", "상점ID"), ("period", "정산기간"),
                                        ("deposit", "입금액(예치금)"), ("sales", "결제금액(미수금)"),
                                        ("fee", "수수료"), ("vat", "부가세")]):
            ttk.Label(right, text=label).grid(row=i, column=0, sticky="e", pady=2)
            e = ttk.Entry(right, textvariable=self.f[k], width=24); e.grid(row=i, column=1, padx=4)
            e.bind("<KeyRelease>", lambda _e: self._validate())
        self.lbl = ttk.Label(right, textvariable=self.msg, wraplength=240)
        self.lbl.grid(row=6, column=0, columnspan=2, pady=6)
        ttk.Button(right, text="③ 목록에 추가", command=self.add).grid(row=7, column=0, columnspan=2, sticky="ew")

        bot = ttk.LabelFrame(self, text="분개 미리보기 (엑셀/영림원으로 나갈 내용)", padding=6)
        bot.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("no", "acct", "dr", "cr", "desc")
        self.tree = ttk.Treeview(bot, columns=cols, show="headings", height=9)
        for c, t, w in zip(cols, ("행", "계정과목", "차변", "대변", "적요"), (40, 120, 90, 90, 560)):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        bar = ttk.Frame(bot); bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="선택 건 삭제", command=self.delete).pack(side="left")
        ttk.Button(bar, text="전체 비우기", command=self.clear).pack(side="left", padx=4)
        ttk.Button(bar, text="엑셀로 저장", command=self.save).pack(side="right")
        ttk.Button(bar, text="클립보드 복사 (영림원용: 행번호~활동센터)", command=self.copy).pack(side="right", padx=6)

    # ---------------------------------------------------------- 동작
    def capture(self):
        res = ui_common.capture_rows(self, "settle")
        if res is None:
            return
        rows, text = res
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", text)
        self.queue = rows
        if not rows:
            self.msg.set("정산 행을 찾지 못했습니다. 표(헤더+데이터 행)만 좁게 다시 캡처하세요.")
            self.lbl.configure(foreground="red")
            return
        self.load_next()

    def reparse(self):
        self.queue = core.parse_rows(self.txt.get("1.0", "end"))
        if not self.queue:
            self.msg.set("정산 행을 찾지 못했습니다. 표(헤더+데이터 행)만 좁게 다시 캡처하세요.")
            self.lbl.configure(foreground="red")
            return
        self.load_next()

    def load_next(self):
        """캡처에서 읽힌 행을 한 건씩 폼에 올려 검수한다."""
        if not self.queue:
            return
        d = self.queue.pop(0)
        for k in ("mid", "period", "deposit", "sales", "fee", "vat"):
            self.f[k].set(str(d[k]))
        self.ym.set(d["ym"])
        self._validate()
        if d.get("fix"):
            self.msg.set(f"🔧 자동보정: {d['fix']} (화면과 확인하세요)")
            self.lbl.configure(foreground="darkorange")
        if self.queue:
            self.msg.set(self.msg.get() + f"  (다음 대기 {len(self.queue)}건)")

    def _entry(self):
        g = lambda k: self.f[k].get().replace(",", "").strip()
        return core.Entry(g("mid"), self.f["period"].get().strip(),
                          int(g("deposit") or 0), int(g("sales") or 0),
                          int(g("fee") or 0), int(g("vat") or 0))

    def _validate(self):
        try:
            diff = self._entry().check()
        except ValueError:
            self.msg.set("숫자만 입력하세요"); return False
        ok = diff == 0
        self.msg.set("✔ 결제금액 = 입금액 + 수수료 + 부가세 일치" if ok
                     else f"⚠ 불일치: 차이 {diff:,}원 → OCR 오류 의심, 값 확인")
        self.lbl.configure(foreground="green" if ok else "red")
        return ok

    def add(self):
        try:
            e = self._entry()
        except ValueError:
            messagebox.showerror("오류", "금액은 숫자로 입력하세요"); return
        if not e.mid:
            messagebox.showerror("오류", "상점ID를 입력하세요"); return
        if e.check() != 0 and not messagebox.askyesno(
                "금액 불일치", f"결제금액이 입금+수수료+부가세와 {e.check():,}원 다릅니다. 그래도 추가할까요?"):
            return
        self.entries.append(e); self.refresh(); self.load_next()

    def settings(self):
        return core.Settings(self.SECTIONS[self.section.get()], self.vendor.get().strip(), self.ym.get().strip())

    def rows(self):
        return core.build_rows(self.entries, self.settings())

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.rows():
            dr = "" if r[3] is None else f"{core._val(r[3]):,}"
            cr = "" if r[4] is None else f"{core._val(r[4]):,}"
            self.tree.insert("", "end", values=(r[0], r[1], dr, cr, r[5]))

    def delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0]) // 3
        del self.entries[idx]; self.refresh()

    def clear(self):
        self.entries.clear(); self.refresh()

    def save(self):
        if not self.entries:
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                           initialfile=f"분개_{self.SECTIONS[self.section.get()]}.xlsx")
        if out:
            core.save_excel(self.ctx.template.get(), out, self.rows(), self.settings())
            messagebox.showinfo("저장", f"저장했습니다.\n{out}")

    def copy(self):
        if not self.entries:
            return
        first, last = self.COPY_COLS
        self.clipboard_clear()
        self.clipboard_append(core.clipboard_text(self.rows(), first, last)); self.update()
        messagebox.showinfo("복사", "클립보드에 복사했습니다.\n영림원 그리드에서 Ctrl+V 하세요.")
