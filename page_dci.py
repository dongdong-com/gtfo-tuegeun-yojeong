"""운영 > Data&Url캡쳐 > DCI 테이블 캡처.
화면에 보이는 표(결제 목록처럼 행/열이 있는 화면)를 캡처 → OCR → 항목과 값이 엑셀의 각 행/열에 들어가도록
탭 구분 표로 만들어 붙여넣기/저장한다. 스크롤 캡처, 이미지 복사 등 공통 기능은 단축URL 캡처와 같다.

단축URL 캡처와 다른 점
 - 넓은 화면은 가로 타일로 나눠 지정한 배율(기본 3.0)대로 OCR한다 (표 글자가 작아도 읽힘)
 - 검색 폼/제목/표가 섞인 화면에서도 세로 여백으로 블록을 나누고 블록마다 열을 따로 계산한다
 - '가장 큰 표'를 자동 선택하거나, 블록 목록에서 원하는 표를 고를 수 있다
 - 행 구분선이 보이면 '구분선 사이 = 한 행'으로 만든다 (셀 안에서 여러 줄로 줄바꿈되는 표)
 - 날짜/시간(2026-11-05 14:58:20) 형식 복원, mem—idx → mem_idx 같은 글자 보정
 - AI 보정(로컬 Gemma 4 E2B):
     · 칸 그림 읽기: 글자가 든 칸을 한 칸씩 잘라(작은 그림일수록 정확) 여러 배율로 읽고, 같은 답이 나올 때만 바꾼다
     · 띄어쓰기 보정: 칸이 좁아 줄바꿈된 단어('자 기소개서')를 텍스트만 보고 이어 붙인다 (글자는 그대로)"""
import difflib
import re
import time
import tkinter as tk
from collections import Counter
from tkinter import messagebox, ttk

from PIL import Image, ImageOps

import tablegrid
from page_vdi import VdiTablePage

AUTO = "자동 (가장 큰 표)"
ALL = "모든 블록 (위에서부터 차례로)"
AI_LABEL = "AI로 보정 (칸 그림 읽기)"
CELL_PROMPT = "이 이미지에 보이는 글자를 그대로 한 줄로 적어라. 줄이 두 줄이면 이어서 적어라. 설명 없이 글자만."
READ_TARGETS = (30, 46, 64)      # 글자 높이를 이 픽셀 수로 키운다(예: 10px 글자 → 3배, 4.6배, 6.4배; 최대 8배). 첫 읽기가 OCR 값과 같으면 끝, 다르면 두 번째, 두 번이 다르면 세 번째 다수결
                                 # (시간: 읽기 1회 0.5~1.5초 — 그림이 크고 답이 길수록 느림. 대부분의 칸은 1회로 끝나게 해서 시간을 줄였다)


def _norm_digits(s: str) -> str:
    """공백·콤마·구분기호를 뺀 값. 이게 같으면 '서식만 바뀐' 변경이다."""
    return re.sub(r"[\s,.\-:/]", "", s)


def _letters(s: str) -> str:
    return re.sub(r"\s", "", s)


def _is_text_cell(s: str) -> bool:
    """글자(한글/영문)가 든 칸. 날짜·금액·번호처럼 숫자와 기호뿐인 칸은 OCR이 대체로 맞아 AI에게 맡기지 않는다."""
    return bool(re.search(r"[가-힣A-Za-z]", s))


def _accept(old: str, new: str) -> bool:
    """AI가 읽은 값이 OCR 값과 어느 정도 닮았을 때만 쓴다 (엉뚱한 문장을 지어내는 것 방지)."""
    a, b = _letters(old), _letters(new)
    if not b or not a:
        return False
    if not (0.5 <= len(b) / len(a) <= 1.8):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.45


def _garbage(s: str) -> bool:
    """이상한 글자(한자·특수문자)가 절반 이상인 칸 — 썸네일 그림이 만든 잡글자. AI도 읽을 글자가 없어 시간만 쓰므로 건너뛴다."""
    import ocrplus
    ch = [c for c in s if not c.isspace()]
    return bool(ch) and sum(1 for c in ch if not ocrplus._is_valid(c)) * 2 >= len(ch)


def _cell_prompt(cands: list[str]) -> str:
    """같은 열의 다른 행에서 OCR이 읽은 비슷한 값들이 있으면 후보로 보여 준다. 후보가 여럿이면 '진짜 단어'를 고르게 되어 정확해진다
    (시험: 노훋/노푿/노출 → 노출). 후보가 하나뿐이면 그 틀린 값을 따라 하므로 후보 없이 읽게 한다."""
    if len(cands) < 2:
        return CELL_PROMPT
    return ("이 이미지에 보이는 글자를 적어라. OCR이 읽은 후보: " + " / ".join(cands) +
            ". 후보 중 이미지와 같은 것이 있으면 그것을 그대로, 없으면 이미지에 보이는 대로 적어라. 글자만 한 줄로 출력해라.")


def _vote(reads: list[str]):
    """읽은 값들 중 2번 이상 나온 값. 없으면 None."""
    norm = [" ".join(r.split()) for r in reads if r and r.strip()]
    if not norm:
        return None
    v, n = Counter(norm).most_common(1)[0]
    return v if n >= 2 else None


class DciTablePage(VdiTablePage):
    TITLE = "DCI 테이블 캡처"
    URL_TOOLS = False
    OCR_TILE = True
    FLAG_CELLS = True
    DEFAULT_SCALE = "3.0"
    INTRO = "표가 보이는 영역을 지정하세요. 자동으로 스크롤하며 캡처한 뒤 행/열로 나눠 엑셀에 붙여넣을 수 있게 만듭니다."
    HINT = ("※ 표가 포함된 영역을 지정하세요(검색 폼이 섞여 있어도 표를 자동으로 찾습니다). 캡처 중 마우스를 움직이지 마세요"
            "(매 스크롤마다 영역 중앙으로 되돌립니다). ESC = 중단.")

    def _init_extra(self):
        self.block_sel = tk.StringVar(value=AUTO)
        self.fix_cells = tk.BooleanVar(value=True)
        self.blocks: list = []
        self.cell_boxes: list | None = None      # 표의 칸마다 이미지 위치 (x0, y0, x1, y1) — AI가 칸 그림을 자를 때 쓴다
        self.row_bands: list | None = None       # 행마다 세로 범위 (구분선 사이) — 단어 상자는 위치가 수~16px 어긋나므로 칸 그림은 이 범위로 자른다
        self.ai_flags: dict = {}                 # (행, 열) → 값: 엑셀에서 노란색으로 표시할 칸 (AI가 숫자를 바꿨거나 판단이 갈린 칸)
        self.ai_only_flagged = tk.BooleanVar(value=False)
        self.precise = tk.BooleanVar(value=True)
        self._ai_cancel = None
        self._ai_backup = None

    def _extra_bar(self, bar, bar2):
        ttk.Checkbutton(bar, text="보정(날짜·고유번호·반복값)", variable=self.fix_cells,
                        command=self.rebuild).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(bar, text="여러 줄 셀 합치기(행 구분선 기준)", variable=self.merge_lines,
                        command=self.rebuild).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(bar2, text="정밀 OCR(여러 설정, 느림)", variable=self.precise).pack(side="left", padx=(8, 0))
        ttk.Label(bar2, text="대상 표").pack(side="left", padx=(14, 4))
        self.cb_block = ttk.Combobox(bar2, textvariable=self.block_sel, values=[AUTO, ALL], width=44,
                                     state="readonly")
        self.cb_block.pack(side="left")
        self.cb_block.bind("<<ComboboxSelected>>", lambda _e: self.rebuild())
        bar3 = ttk.Frame(bar.master); bar3.pack(fill="x", pady=(4, 0))
        self.btn_ai = ttk.Button(bar3, text=AI_LABEL, command=self.ai_fix)
        self.btn_ai.pack(side="left")
        self.btn_sp = ttk.Button(bar3, text="AI 띄어쓰기 보정", command=self.ai_spacing)
        self.btn_sp.pack(side="left", padx=6)
        self.btn_undo = ttk.Button(bar3, text="AI 보정 되돌리기", command=self.ai_undo, state="disabled")
        self.btn_undo.pack(side="left")
        ttk.Checkbutton(bar3, text="확인 필요(노란) 칸만", variable=self.ai_only_flagged).pack(side="left", padx=(8, 0))
        ttk.Label(bar3, text="로컬 AI · 서로 다른 칸 1개당 약 2~3초 · 연노랑=글자 수정 / 주황=숫자 수정 / 분홍=판단 갈림(확인)",
                  foreground="gray").pack(side="left", padx=8)

    def _ocr_words(self, img, progress=None):
        """정밀 OCR(기본 켬): 여러 배율/선명화로 읽어 줄마다 가장 좋은 결과를 쓴다(ocrplus). 끄면 한 번만 읽어 빠르다."""
        if not self.precise.get():
            return super()._ocr_words(img, progress)
        import ocrplus
        return ocrplus.read_words(img, scale=float(self.ocr_scale.get()), sharp=self.ocr_sharp.get(),
                                  lang=self._ocr_lang(), progress=progress, min_alnum=1)

    def _make_table(self):
        self.ai_flags = {}                          # 표를 다시 만들면 AI 보정 표시는 지운다
        self._ai_backup = None
        try:
            self.btn_undo.config(state="disabled")
        except Exception:
            pass
        self.cell_boxes = None
        self.row_bands = None
        if self.merge_lines.get() and self.bounds and self.block_sel.get() != ALL:
            return self._make_record_table()
        boxes_blocks: list = []
        self.blocks = tablegrid.list_blocks(self.words, self.gap.get(), boxes_blocks)
        labels = [AUTO]
        for i, g in enumerate(self.blocks, 1):
            first = next((c for c in g[0] if c), "") if g else ""
            labels.append(f"블록 {i}: {len(g)}행×{max(len(r) for r in g)}열 — {first[:16]}")
        labels.append(ALL)
        self.cb_block["values"] = labels
        sel = self.block_sel.get()
        if sel not in labels:                       # 다시 인식해서 블록이 바뀌었으면 자동으로 되돌린다
            sel = AUTO
            self.block_sel.set(AUTO)
        if not self.blocks:
            return [], "표를 찾지 못함"

        def fix(g):          # 블록마다 따로 보정한다 (다른 블록의 값과 비교하면 안 되므로)
            g = tablegrid.fix_columns(tablegrid.fix_cells(g)) if self.fix_cells.get() else g
            return tablegrid.blank_picture_columns(g)[0]       # 썸네일 같은 그림 열의 잡글자는 비운다

        if sel == AUTO:
            bi = max(range(len(self.blocks)), key=lambda i: len(self.blocks[i]) * max(len(r) for r in self.blocks[i]))
            g = self.blocks[bi]
            lo, hi = tablegrid.trim_range(g)
            table, mode = fix(g[lo:hi]), "자동 선택"
            if bi < len(boxes_blocks):
                self.cell_boxes = boxes_blocks[bi][lo:hi]
        elif sel == ALL:
            table = []
            for g in self.blocks:
                if table:
                    table.append([])
                table.extend(fix(g))
            mode = "모든 블록"
        else:
            idx = labels.index(sel) - 1
            table, mode = fix(self.blocks[idx]), f"블록 {idx + 1}"
            if idx < len(boxes_blocks):
                self.cell_boxes = boxes_blocks[idx]
        n = len(tablegrid.uncertain_cells(table)) if sel != ALL else 0
        extra = f" · 확인 필요 셀 {n}개(복사하면 엑셀에서 노란색)" if n else ""
        return table, f"{mode} · 블록 {len(self.blocks)}개 중{extra}"

    def _make_record_table(self):
        """행 구분선(왼쪽 가장자리 배경색 변화)이 규칙적으로 보이면 '구분선 사이 = 한 행'으로 만든다.
        셀 안에서 2~3줄로 줄바꿈되는 표(상품 제목, 날짜+시간, 조회/판매/리뷰+버튼)를 줄 단위로 읽으면
        한 행이 여러 블록으로 쪼개져 일부 행만 남기 때문이다."""
        boxes: list = []
        table = tablegrid.build_table(self.words, self.gap.get(), self.bounds, boxes_out=boxes)
        if self.fix_cells.get():
            table = tablegrid.fix_columns(tablegrid.fix_cells(table))
        self.cell_boxes = boxes
        import bisect
        groups = sorted({bisect.bisect(self.bounds, w[2]) for w in self.words})       # build_table의 행 순서(그룹 번호순)
        bands = []
        for k in groups:
            if 1 <= k <= len(self.bounds) - 1:
                bands.append((self.bounds[k - 1], self.bounds[k]))                    # 행 구분선 사이 = 그 행의 세로 범위
            else:
                ys = [w[2] for w in self.words if bisect.bisect(self.bounds, w[2]) == k]
                bands.append((min(ys) - 8, max(ys) + 8))
        self.row_bands = bands if len(bands) == len(table) else None
        table, pic = tablegrid.blank_picture_columns(table)
        n = len(tablegrid.uncertain_cells(table))
        extra = f" · 확인 필요 셀 {n}개(복사하면 엑셀에서 노란색)" if n else ""
        if pic:
            extra += f" · 그림(썸네일) 열 {len(pic)}개의 잡글자를 비움"
        return table, f"행 구분선 {len(self.bounds) - 1}개 기준(여러 줄 셀 합침){extra}"

    # ------------------------------------------------------------------ AI 공통
    def _extra_flags(self, table) -> set:
        return {(r, c) for (r, c), v in self.ai_flags.items()
                if r < len(table) and c < len(table[r]) and table[r][c].strip() == v}

    def _write_tagged(self, new, tags: dict):
        """표를 텍스트 상자에 쓰고 바뀐 칸을 색으로 표시한다. tags = {태그이름: [(행, 열), …]}"""
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", tablegrid.to_tsv(new))
        self.txt.tag_configure("aisoft", background="#FEEC95")     # 글자만 바뀜
        self.txt.tag_configure("aihard", background="#FFB36B")     # 숫자·날짜가 바뀜
        self.txt.tag_configure("aiuns", background="#FFC4D6")      # AI 읽기가 갈려 판단 못 함 (확인 필요)
        for tag, cells in tags.items():
            for r, c in cells:
                start = sum(len(x) + 1 for x in new[r][:c])
                self.txt.tag_add(tag, f"{r + 1}.{start}", f"{r + 1}.{start + len(new[r][c])}")

    def _busy(self, btn, label: str):
        btn.config(text=label)

    # ------------------------------------------------------------------ AI 보정: 칸 그림 읽기
    def _cell_region(self, r: int, c: int, boxes):
        """칸 그림을 자를 범위. OCR 단어 상자는 설정마다 가로로 수십 px, 세로로 16px까지 어긋나(`이관`의 '관'이 잘려 `이권`으로 읽힘)
        글자를 자를 수 있으므로, 가로는 '그 열 전체의 글자 범위', 세로는 '그 행의 범위'로 넉넉히 자른다.
        (행 구분선이 없으면 같은 행 칸들의 세로 범위 ±글자 높이)"""
        xs0 = min(b[0] for row in boxes for b in [row[c]] if b)
        xs1 = max(b[2] for row in boxes for b in [row[c]] if b)
        if self.row_bands and r < len(self.row_bands):
            y0, y1 = self.row_bands[r]
        else:
            row = [b for b in boxes[r] if b]
            h = max(b[3] - b[1] for b in row) if row else 12
            y0, y1 = min(b[1] for b in row) - h, max(b[3] for b in row) + h
        return (xs0 - 8, y0 + 1, xs1 + 8, y1 - 1)

    def _cell_crop(self, box, target: int):
        x0, y0, x1, y1 = box
        pad = 0
        cr = self.img.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)),
                            min(self.img.width, int(x1 + pad)), min(self.img.height, int(y1 + pad))))
        g = cr.convert("L")
        import numpy as np
        if float(np.asarray(g).mean()) < 165:                    # 어두운 바탕(초록 버튼의 흰 글자 등)은 반전해서 읽힌다 ('이관'을 '이권'으로 읽던 것)
            cr = ImageOps.invert(cr.convert("RGB"))
        cr = ImageOps.expand(cr, border=10, fill="white")
        hh = sorted(w[3] for w in self.words)[len(self.words) // 2] if self.words else 12
        s = max(1.0, min(8.0, target / max(hh, 6.0)))              # 크롭이 열 전체×행 전체라 커졌으므로 '글자 높이' 기준으로 키운다
        long = max(cr.size)
        if long * s > 1100:                                          # 너무 큰 그림은 느리다
            s = max(1.0, 1100 / long)
        if s > 1.05:
            cr = cr.resize((int(cr.width * s), int(cr.height * s)), Image.LANCZOS)
        return cr

    def ai_fix(self):
        """글자가 든 칸을 한 칸씩 그림으로 잘라 로컬 AI가 읽게 한다. (표 전체를 한 번에 읽히면 작은 글자·넓은 표에서 틀리고 느리다)
        - 같은 칸 값(예: 판매자·승인상태가 모든 행에서 같음)은 한 번만 읽어 모든 행에 적용한다
        - 두 번 읽어 같으면 확정, 다르면 한 번 더 읽어 다수결. 다수가 없으면 바꾸지 않고 분홍으로 '확인 필요' 표시
        - AI 값이 OCR 값과 너무 다르면(지어낸 문장) 버린다. 숫자·날짜가 바뀐 칸은 주황(엑셀에서 노란색)"""
        import aillm
        if self._ai_cancel is not None:                          # 실행 중이면 중단
            self._ai_cancel.set()
            return
        if self.img is None:
            messagebox.showinfo("AI 보정", "먼저 표를 캡처하세요."); return
        table = self._table()
        if len(table) < 1:
            messagebox.showinfo("AI 보정", "보정할 표 데이터가 없습니다."); return
        if self.block_sel.get() == ALL:
            messagebox.showinfo("AI 보정", "'모든 블록' 상태에서는 쓸 수 없습니다.\n대상 표에서 보정할 표 하나를 고르세요."); return
        boxes = self.cell_boxes
        if (boxes is None or len(boxes) != len(table)
                or any(len(boxes[r]) != len(table[r]) for r in range(len(table)))):
            messagebox.showinfo("AI 보정", "표 모양이 바뀌어 칸의 이미지 위치를 맞출 수 없습니다.\n"
                                         "'OCR 다시'로 표를 새로 만든 뒤 AI 보정을 누르세요."); return
        only = tablegrid.uncertain_cells(table) if self.ai_only_flagged.get() else None
        groups: dict = {}                                        # (열, 값) → [(행, 열)…]  같은 칸 값은 한 번만 읽는다
        col_vals: dict = {}                                      # 열 → 그 열의 글자 칸 값들 (후보 만들기용)
        for r, row in enumerate(table):
            for c, v in enumerate(row):
                s = v.strip()
                if not s or not boxes[r][c] or not _is_text_cell(s) or _garbage(s):
                    continue
                col_vals.setdefault(c, Counter())[s] += 1
                if only is not None and (r, c) not in only:
                    continue
                groups.setdefault((c, s), []).append((r, c))
        if not groups:
            messagebox.showinfo("AI 보정", "보정할 칸이 없습니다." + ("\n(확인 필요한 글자 칸이 없는 표입니다)" if only is not None else "")); return
        est = len(groups) * 2.5
        if est > 150 and not messagebox.askyesno("AI 보정", f"서로 다른 글자 칸 {len(groups)}개를 하나씩 읽습니다.\n"
                                                           f"약 {est / 60:.1f}분 걸립니다. 진행할까요?\n"
                                                           "(실행 중 같은 버튼이 'AI 중단'이 됩니다)"):
            return
        self.status.set("AI 준비 중…"); self.update()
        msg = aillm.check()
        if msg:
            self.status.set("AI 사용 불가"); messagebox.showwarning("AI 보정", msg); return
        jobs = []                                                # 스레드에서 tk를 건드리지 않도록 그림을 미리 자른다
        for (c, s), cells in groups.items():
            r0, c0 = cells[0]
            peers = [v for v, _n in col_vals.get(c, Counter()).most_common()
                     if v != s and difflib.SequenceMatcher(None, _letters(s), _letters(v)).ratio() >= 0.5][:4]
            region = self._cell_region(r0, c0, boxes)
            jobs.append(((c, s), cells, {tg: self._cell_crop(region, tg) for tg in READ_TARGETS},
                         _cell_prompt([s] + peers)))
        self._ai_backup = self.txt.get("1.0", "end").rstrip("\n")
        t0 = time.time()
        self._busy(self.btn_ai, "AI 중단")

        def work(cancel, emit):
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def read_kind(job):
                key, cells, crops, prompt = job
                if cancel.is_set():
                    return None
                reads = []
                old = " ".join(key[1].split())
                try:
                    for tg in READ_TARGETS:
                        reads.append(aillm.chat(prompt, crops[tg], cancel=cancel, num_predict=120, prep=False))
                        a0 = " ".join(reads[0].split())
                        if len(reads) == 1 and a0 == old:
                            break                                # 첫 번째가 OCR 값과 같으면 맞는 것으로 보고 끝 (대부분의 칸 — 시간 절약)
                        if len(reads) == 2 and a0 == " ".join(reads[1].split()):
                            break                                # 두 번이 같으면 세 번째는 읽지 않는다
                except aillm.AIError:
                    return None
                return (key, cells, reads)

            out, done = [], 0
            # 동시에 2개씩 읽는다: 이 PC(GPU 없음)에서 16회 읽기 16.6초 → 11.4초(1.45배). 3개 이상은 더 빨라지지 않는다.
            with ThreadPoolExecutor(2) as ex:
                futs = [ex.submit(read_kind, j) for j in jobs]
                for f in as_completed(futs):
                    done += 1
                    emit(f"AI 칸 읽기 {done}/{len(jobs)} · {time.time() - t0:.0f}초")
                    res = f.result()
                    if res is not None:
                        out.append(res)
                    if cancel.is_set():
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
            return out

        def finish():
            self._ai_cancel = None
            self._busy(self.btn_ai, AI_LABEL)

        def on_done(res):
            finish()
            new = [list(r) for r in table]
            tags = {"aisoft": [], "aihard": [], "aiuns": []}
            flags = {}
            same = 0
            for (c, old), cells, reads in res:
                val = old if (len(reads) == 1 and " ".join(reads[0].split()) == " ".join(old.split())) else _vote(reads)
                if val is None or not _accept(old, val):
                    for r, cc in cells:                          # 판단이 갈리거나 엉뚱함 → 바꾸지 않고 확인 필요
                        tags["aiuns"].append((r, cc)); flags[(r, cc)] = new[r][cc].strip()
                    continue
                if " ".join(val.split()) == " ".join(old.split()):
                    same += 1
                    continue
                digits_changed = re.sub(r"\D", "", old) != re.sub(r"\D", "", val)      # 숫자 열이 달라졌을 때만 '숫자 수정'(주황)
                for r, cc in cells:
                    new[r][cc] = val
                    if digits_changed:
                        tags["aihard"].append((r, cc)); flags[(r, cc)] = val
                    else:
                        tags["aisoft"].append((r, cc))
            self._write_tagged(new, tags)
            self.ai_flags = flags
            self.btn_undo.config(state="normal")
            self.status.set(
                f"AI 보정 완료 · {time.time() - t0:.0f}초 · 읽은 칸 종류 {len(res)}개 · 글자 수정 {len(tags['aisoft'])}칸(연노랑)"
                f" · 숫자 수정 {len(tags['aihard'])}칸(주황) · 판단 갈림 {len(tags['aiuns'])}칸(분홍) · 그대로 맞음 {same}종류"
                " — 주황·분홍은 확인 후 사용하세요")

        def on_error(ex):
            finish()
            self.status.set(f"AI 보정 실패: {ex}")

        self._ai_cancel = aillm.run_async(self, work, lambda s: self.status.set(s), on_done, on_error)

    # ------------------------------------------------------------------ AI 띄어쓰기 보정
    @staticmethod
    def _apply_spacing(old: str, new: str):
        """new의 띄어쓰기만 old의 글자에 입힌다. 글자 수(공백 제외)가 다르면 None. (AI가 오타를 고쳐 쓰거나 글자를 바꿔도 글자는 OCR 원문 그대로 둔다)"""
        a = [c for c in old if not c.isspace()]
        if len(a) != sum(1 for c in new if not c.isspace()):
            return None
        out, i = [], 0
        for ch in new:
            if ch.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
            else:
                out.append(a[i]); i += 1
        return "".join(out).strip()

    def ai_spacing(self):
        """칸이 좁아 글자가 줄바꿈된 셀('자 기소개서', '경력기 술서')의 띄어쓰기를 로컬 AI가 바로잡는다.
        글자는 건드리지 않고 공백만 바꾸며(OCR 원문 글자 그대로), 텍스트만 보내므로 빠르다(수 초)."""
        import aillm
        if self._ai_cancel is not None:
            self._ai_cancel.set()
            return
        table = self._table()
        targets = []                                              # (행, 열, 문자열): 한글이 들어 있고 공백이 있는 6자 이상 칸
        for r, row in enumerate(table):
            for c, v in enumerate(row):
                s = v.strip()
                if len(s) >= 6 and " " in s and re.search(r"[가-힣]", s):
                    targets.append((r, c, s))
        if not targets:
            messagebox.showinfo("AI 띄어쓰기 보정", "보정할 칸(공백이 있는 긴 한글 칸)이 없습니다."); return
        self.status.set("AI 준비 중…"); self.update()
        msg = aillm.check()
        if msg:
            self.status.set("AI 사용 불가"); messagebox.showwarning("AI 띄어쓰기 보정", msg); return
        self._ai_backup = self.txt.get("1.0", "end").rstrip("\n")
        t0 = time.time()
        self._busy(self.btn_sp, "AI 중단")

        def work(cancel, emit):
            results = {}
            for b in range(0, len(targets), 20):
                if cancel.is_set():
                    break
                part = targets[b:b + 20]
                emit(f"AI 띄어쓰기 보정 {b + 1}~{b + len(part)}/{len(targets)} · {time.time() - t0:.0f}초")
                lines = "\n".join(f"[{i}] {s}" for i, (_r, _c, s) in enumerate(part))
                prompt = ("아래는 표의 칸 글자를 OCR로 읽은 것이다. 칸이 좁아 글자가 줄바꿈될 때 단어 중간에 공백이 끼거나('자 기소개서', "
                          "'경력기 술서'), 띄어 써야 할 곳이 붙어 있을 수 있다. 한국어 맞춤법에 맞게 공백만 고쳐서 각 줄을 '[번호] 문장' "
                          "형식 그대로 모두 출력해라. 글자(한글·영문·숫자)는 바꾸거나 빼거나 더하지 마라. 설명 금지.\n\n" + lines)
                ans = aillm.chat(prompt, None, cancel=cancel, num_predict=len(lines) * 3 + 100)
                for ln in ans.splitlines():
                    m = re.match(r"^\[(\d+)\]\s*(.*)$", ln.strip())
                    if m and int(m.group(1)) < len(part):
                        r, c, old = part[int(m.group(1))]
                        results[(r, c)] = (old, m.group(2))
            return results

        def finish():
            self._ai_cancel = None
            self._busy(self.btn_sp, "AI 띄어쓰기 보정")

        def on_done(res):
            finish()
            new = [list(r) for r in table]
            soft = []
            for (r, c), (old, ans) in res.items():
                fixed = self._apply_spacing(old, ans)
                if fixed and fixed != old:
                    new[r][c] = fixed
                    soft.append((r, c))
            self._write_tagged(new, {"aisoft": soft})
            self.btn_undo.config(state="normal")
            self.status.set(f"AI 띄어쓰기 보정 완료 · {time.time() - t0:.0f}초 · 공백만 바꾼 칸 {len(soft)}개(연노랑) — 글자는 그대로입니다")

        def on_error(ex):
            finish()
            self.status.set(f"AI 띄어쓰기 보정 실패: {ex}")

        self._ai_cancel = aillm.run_async(self, work, lambda s: self.status.set(s), on_done, on_error)

    def ai_undo(self):
        if self._ai_backup is None:
            return
        self.txt.delete("1.0", "end"); self.txt.insert("1.0", self._ai_backup)
        self.ai_flags = {}
        self._ai_backup = None
        self.btn_undo.config(state="disabled")
        self.status.set("AI 보정 이전(OCR 원문)으로 되돌렸습니다")
