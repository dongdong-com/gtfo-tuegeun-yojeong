"""정산 > 포스티니 > PG(이니시스) 수수료 정산.
세금계산서(공급가액/세액) + 통합정산내역(1~15일 / 16~말일 수수료·부가세)을 캡처해
설정(config.STORE_IDS)에 적은 상점들의 수수료 정산 전표를 만든다."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import core
import ui_common

FIELDS = ["supply", "tax", "pre_fee", "pre_vat", "post_fee", "post_vat"]
HEADERS = ["세금계산서\n공급가액", "세금계산서\n세액", "선급금(1~15일)\n수수료", "선급금(1~15일)\n부가세",
           "미지급금(16~말일)\n수수료", "미지급금(16~말일)\n부가세", "검증"]


class FeeSettlePage(ttk.Frame):
    TITLE = "PG(이니시스) 수수료 정산"
    COPY_COLS = (0, 7)   # 행번호~활동센터

    def __init__(self, master, ctx):
        super().__init__(master)
        self.ctx = ctx
        self.ym = tk.StringVar(value="2026년 10월")
        self.v = {mid: {k: tk.StringVar() for k in FIELDS} for mid in core.STORE_ORDER}
        self.chk = {mid: tk.StringVar() for mid in core.STORE_ORDER}
        self.chk_lbl = {}
        self.x = {k: tk.StringVar() for k in ("mid", "ym", "supply", "tax")}
        self.x["mid"].set(core.STORE_ORDER[0])
        self.log = tk.StringVar()
        self._ui()

    # ---------------------------------------------------------- UI
    def _ui(self):
        top = ttk.Frame(self, padding=6); top.pack(fill="x")
        ttk.Label(top, text="정산월(적요 표기)").pack(side="left")
        e = ttk.Entry(top, textvariable=self.ym, width=12); e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda _e: self.refresh())
        ttk.Label(top, text="※ " + " / ".join(i[-3:] for i in core.STORE_ORDER) + f" {len(core.STORE_ORDER)}개 상점 모두 처리", foreground="gray").pack(side="left", padx=10)

        cap = ttk.LabelFrame(self, text="① 캡처 (로컬 OCR) — 상점별로 조회 후 표의 헤더+데이터 행만 좁게 드래그", padding=6)
        cap.pack(fill="x", padx=6)
        ttk.Button(cap, text="세금계산서 캡처 (발행내역조회)", command=self.cap_tax).pack(side="left")
        ttk.Button(cap, text="통합정산내역 캡처 (정산일 1~15 / 16~말일 두 행)", command=self.cap_settle).pack(side="left", padx=6)
        ttk.Label(cap, textvariable=self.log, foreground="gray").pack(side="left", padx=8)

        grid = ttk.LabelFrame(self, text="② 값 확인/수정 (원 단위, 상점별)", padding=6)
        grid.pack(fill="x", padx=6, pady=6)
        ttk.Label(grid, text="상점ID").grid(row=0, column=0, padx=4)
        for j, h in enumerate(HEADERS, 1):
            ttk.Label(grid, text=h, justify="center").grid(row=0, column=j, padx=4, pady=2)
        for i, mid in enumerate(core.STORE_ORDER, 1):
            ttk.Label(grid, text=mid).grid(row=i, column=0, padx=4, pady=2, sticky="w")
            for j, k in enumerate(FIELDS, 1):
                en = ttk.Entry(grid, textvariable=self.v[mid][k], width=13, justify="right")
                en.grid(row=i, column=j, padx=3)
                en.bind("<KeyRelease>", lambda _e: self.refresh())
            lbl = ttk.Label(grid, textvariable=self.chk[mid], width=20)
            lbl.grid(row=i, column=7, padx=4)
            self.chk_lbl[mid] = lbl
        ttk.Label(grid, text="검증: 세금계산서 (공급가액+세액) = 통합정산내역 한 달 (수수료+부가세) 합계",
                  foreground="gray").grid(row=4, column=0, columnspan=8, sticky="w", pady=(4, 0))

        ex = ttk.LabelFrame(self, text="선택: 기타 수수료 (계좌성명조회 등 → 미지급금-거래처, 귀속부서/활동센터 없음)", padding=6)
        ex.pack(fill="x", padx=6)
        ttk.Label(ex, text="상점ID").pack(side="left")
        ttk.Combobox(ex, textvariable=self.x["mid"], values=core.STORE_ORDER, width=12,
                     state="readonly").pack(side="left", padx=4)
        for k, label, w in (("ym", "귀속월", 12), ("supply", "공급가액", 10), ("tax", "세액", 10)):
            ttk.Label(ex, text=label).pack(side="left", padx=(8, 0))
            en = ttk.Entry(ex, textvariable=self.x[k], width=w); en.pack(side="left", padx=4)
            en.bind("<KeyRelease>", lambda _e: self.refresh())
        ttk.Label(ex, text="(공급가액/세액 비우면 제외)", foreground="gray").pack(side="left", padx=6)

        bot = ttk.LabelFrame(self, text="분개 미리보기 (엑셀/영림원으로 나갈 내용)", padding=6)
        bot.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("no", "acct", "kind", "dr", "cr", "desc")
        self.tree = ttk.Treeview(bot, columns=cols, show="headings", height=9)
        for c, t, w in zip(cols, ("행", "계정과목", "비용구분", "차변", "대변", "적요"), (40, 130, 70, 90, 90, 480)):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        bar = ttk.Frame(bot); bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="전체 비우기", command=self.clear).pack(side="left")
        ttk.Button(bar, text="엑셀로 저장", command=self.save).pack(side="right")
        ttk.Button(bar, text="클립보드 복사 (영림원용: 행번호~활동센터)", command=self.copy).pack(side="right", padx=6)
        self.refresh()

    # ---------------------------------------------------------- 캡처
    def cap_tax(self):
        res = ui_common.capture_rows(self, "tax")
        if res is None:
            return
        rows, _text = res
        if not rows:
            messagebox.showwarning("인식 실패", "세금계산서 행을 찾지 못했습니다.\n발행내역조회 표(헤더+데이터 행)만 좁게 다시 캡처하세요.")
            return
        msgs = []
        for r in rows:
            if r["mid"] not in self.v:
                msgs.append(f"{r['mid']}: 알 수 없는 상점ID (무시)"); continue
            self.v[r["mid"]]["supply"].set(str(r["supply"]))
            self.v[r["mid"]]["tax"].set(str(r["tax"]))
            self.ym.set(r["ym"])
            ok = r["supply"] + r["tax"] == r["total"]
            msgs.append(f"{r['mid']}: 공급가액 {r['supply']:,} / 세액 {r['tax']:,}"
                        + ("" if ok else "  ⚠ 합계 불일치(OCR 확인)")
                        + (f" 🔧자동보정 {r['fix']}" if r.get("fix") else ""))
        self.log.set(" | ".join(msgs)); self.refresh()
        self._warn_fixes(rows)

    @staticmethod
    def _warn_fixes(rows):
        """OCR 숫자 혼동을 합계 검증으로 자동 보정한 경우, 화면과 대조하도록 알린다."""
        fixes = [f"{r['mid']} {r.get('period', '')}: {r['fix']}" for r in rows if r.get("fix")]
        if fixes:
            messagebox.showwarning("자동 보정됨 — 화면과 확인",
                                   "OCR이 한 자리를 잘못 읽어 합계 검증 기준으로 자동 보정했습니다.\n"
                                   "이니시스 화면의 값과 맞는지 확인하세요.\n\n" + "\n".join(fixes))

    def cap_settle(self):
        res = ui_common.capture_rows(self, "settle")
        if res is None:
            return
        rows, _text = res
        if not rows:
            messagebox.showwarning("인식 실패", "정산 행을 찾지 못했습니다.\n통합정산내역 표(헤더+데이터 행)만 좁게 다시 캡처하세요.")
            return
        msgs = []
        for r in rows:
            if r["mid"] not in self.v:
                msgs.append(f"{r['mid']}: 알 수 없는 상점ID (무시)"); continue
            half = "pre" if int(r["period"][3:5]) <= 15 else "post"   # 정산일 시작일 기준
            self.v[r["mid"]][f"{half}_fee"].set(str(r["fee"]))
            self.v[r["mid"]][f"{half}_vat"].set(str(r["vat"]))
            self.ym.set(r["ym"])
            msgs.append(f"{r['mid']} {r['period']} → {'선급금' if half == 'pre' else '미지급금'}"
                        + ("" if core.settle_ok(r) else " ⚠ 합계 불일치(OCR 확인)")
                        + (f" 🔧자동보정 {r['fix']}" if r.get("fix") else ""))
        self.log.set(" | ".join(msgs)); self.refresh()
        self._warn_fixes(rows)

    # ---------------------------------------------------------- 데이터
    @staticmethod
    def _n(sv) -> int:
        s = sv.get().replace(",", "").strip()
        return int(s) if s else 0

    def stores(self):
        out = []
        for mid in core.STORE_ORDER:
            out.append(core.FeeStore(mid, **{k: self._n(self.v[mid][k]) for k in FIELDS}))
        return out

    def extras(self):
        try:
            return [core.ExtraFee(self.x["mid"].get(), ym=self.x["ym"].get().strip(),
                                  supply=self._n(self.x["supply"]), tax=self._n(self.x["tax"]))]
        except ValueError:
            return []

    def rows(self):
        return core.build_fee_rows(self.stores(), self.ym.get().strip(), self.extras())

    def refresh(self):
        try:
            stores = self.stores()
        except ValueError:
            return
        for s in stores:
            if s.empty():
                self.chk[s.mid].set("")
                continue
            d = s.diff()
            self.chk[s.mid].set("✔ 일치" if d == 0 else f"⚠ 차이 {d:,}원")
            self.chk_lbl[s.mid].configure(foreground="green" if d == 0 else "red")
        self.tree.delete(*self.tree.get_children())
        try:
            rows = self.rows()
        except ValueError:
            return
        for r in rows:
            dr = f"{core._val(r[3]):,}" if r[3] is not None else ""
            cr = f"{core._val(r[4]):,}" if r[4] is not None else ""
            self.tree.insert("", "end", values=(r[0], r[1], r[2] or "", dr, cr, r[5]))

    def _bad_checks(self):
        return [s.mid for s in self.stores() if not s.empty() and s.diff() != 0]

    def _confirm(self):
        bad = self._bad_checks()
        if bad:
            return messagebox.askyesno("금액 불일치", f"{', '.join(bad)}: 세금계산서 합계와 정산내역 합계가 다릅니다.\n그래도 진행할까요?")
        return True

    # ---------------------------------------------------------- 출력
    def clear(self):
        for mid in self.v:
            for sv in self.v[mid].values():
                sv.set("")
        for sv in self.x.values():
            if sv is not self.x["mid"]:
                sv.set("")
        self.log.set(""); self.refresh()

    def save(self):
        rows = self.rows()
        if not rows or not self._confirm():
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                           initialfile="분개_PG수수료정산.xlsx")
        if out:
            core.save_fee_excel(self.ctx.template.get(), out, rows)
            messagebox.showinfo("저장", f"저장했습니다.\n{out}")

    def copy(self):
        rows = self.rows()
        if not rows or not self._confirm():
            return
        first, last = self.COPY_COLS
        self.clipboard_clear()
        self.clipboard_append(core.clipboard_text(rows, first, last)); self.update()
        messagebox.showinfo("복사", "클립보드에 복사했습니다.\n영림원 그리드에서 Ctrl+V 하세요.")
