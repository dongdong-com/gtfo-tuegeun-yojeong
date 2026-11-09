"""OCR 단어 좌표 → 행/열 표(2차원 리스트) 변환, 엑셀 저장/클립보드용 가공."""
import io
import re
import statistics
from collections import Counter
from itertools import combinations

import numpy as np
import openpyxl
from PIL import Image

import core


def _best_cut(ink: np.ndarray, lo: int, hi: int) -> int:
    """ink[lo:hi] 안에서 '가장 넓게 비어 있는 구간'의 한가운데를 자를 위치(끝 인덱스)로 돌려준다.
    단순히 가장 비어 있는 첫 줄에서 자르면 숫자 사이의 1~2px 틈(예: 31541|4303)에서 잘려 번호가 갈라진다.
    열 사이 여백은 수십 px이라 가장 넓은 빈 구간을 고르면 글자 중간을 자르지 않는다."""
    seg = ink[lo:hi]
    n = len(seg)
    if n == 0:
        return hi
    base = float(seg.min())
    tol = max(0.5, 0.03 * (float(seg.max()) - base))
    blank = seg <= base + tol
    best_len = best_start = i = 0
    while i < n:
        if blank[i]:
            j = i
            while j < n and blank[j]:
                j += 1
            if j - i > best_len:
                best_len, best_start = j - i, i
            i = j
        else:
            i += 1
    return lo + best_start + best_len // 2 + 1


def ocr_tall(img: Image.Image, chunk_h: int = 1000, progress=None, scale: float = 2.0,
             sharp: bool = False, tile: bool = False, lang: str = "ko") -> list:
    """세로로 긴 이미지를 글자가 없는 가로줄에서 잘라 조각별로 OCR하고 좌표를 합친다.
    (OCR 엔진의 최대 이미지 크기 제한 때문. 배율이 클수록 조각을 짧게 자른다)
    tile=True: 폭이 넓은 이미지는 글자가 없는 세로줄에서도 잘라 가로로 나눠 읽는다.
      엔진 크기 제한 때문에 넓은 이미지는 배율이 자동으로 깎이는데(예: 폭 1659px → 4.0배가 1.45배로),
      타일로 나누면 지정한 배율 그대로 읽을 수 있어 작은 글자의 인식률이 크게 오른다."""
    chunk = int(2300 / scale)
    chunk_h = min(chunk_h, chunk)
    g = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = g.shape
    ink = np.abs(g - np.median(g)).mean(axis=1)           # 행별 '글자량'
    words, y = [], 0
    while y < h:
        end = min(h, y + chunk_h)
        if end < h:                                         # 뒤쪽 40% 안에서 가장 넓게 비어 있는 곳의 중앙에서 자른다
            lo = y + int(chunk_h * 0.6)
            end = _best_cut(ink, lo, end)
        if progress:
            progress(f"OCR {y}/{h}px")
        xs = [0, w]
        if tile and w > chunk:                              # 같은 방식으로 세로줄 기준 타일 분할
            sub = g[y:end]
            inkx = np.abs(sub - np.median(sub)).mean(axis=0)
            xs, x = [0], 0
            while x < w:
                xe = min(w, x + chunk)
                if xe < w:
                    lo = x + int(chunk * 0.6)
                    xe = _best_cut(inkx, lo, xe)
                xs.append(xe)
                x = xe
        for x0, x1 in zip(xs[:-1], xs[1:]):
            for t, wx, yc, hh, ww in core.ocr_words(img.crop((x0, y, x1, end)), scale, sharp, lang):
                words.append((t, wx + x0, yc + y, hh, ww))
        y = end
    return words


def row_boundaries(img: Image.Image, min_jump: float = 3.0) -> list[float]:
    """표 왼쪽 가장자리의 배경색이 바뀌는 지점(줄무늬/구분선)을 레코드 경계 y좌표로 돌려준다.
    셀 안에서 여러 줄로 줄바꿈되는 표를 한 레코드=한 행으로 묶는 데 쓴다.
    영역을 표 왼쪽 끝에 맞춰 지정해야 잘 잡힌다. 경계가 2개 미만이면 빈 리스트(=줄 단위 모드)."""
    g = np.asarray(img.convert("L"), dtype=np.float32)
    if g.shape[0] < 4 or g.shape[1] < 4:
        return []
    strip = np.median(g[:, 2:min(14, g.shape[1])], axis=1)
    ys = np.where(np.abs(np.diff(strip)) > min_jump)[0]
    bounds: list[list[int]] = []
    for y in ys:                                  # 가까운 변화(구분선 위·아래 가장자리)는 하나로 합친다
        if bounds and y - bounds[-1][-1] <= 4:
            bounds[-1].append(int(y))
        else:
            bounds.append([int(y)])
    out = [sum(b) / len(b) + 0.5 for b in bounds]
    return out if _regular(out) else []


def _regular(bounds: list[float]) -> bool:
    """경계가 '같은 간격으로 반복되는 레코드 줄무늬'처럼 보이는지 검사한다.
    사이드바/머리글/푸터의 배경색 변화 몇 개를 레코드 경계로 착각하면 페이지 전체가 한 덩어리로 합쳐지기 때문."""
    if len(bounds) < 3:
        return False
    gaps = np.diff(bounds)
    m = float(np.median(gaps))
    return m >= 18 and float(np.mean(np.abs(gaps - m) <= 0.25 * m)) >= 0.7


_NO_SPACE_END = "-/?&=_"


def _join_lines(lines: list[str]) -> str:
    """줄바꿈된 셀의 줄들을 합친다. URL처럼 기호로 끝나는 줄 뒤에는 공백을 넣지 않는다."""
    out = ""
    for s in lines:
        if not s:
            continue
        out += s if (not out or out[-1] in _NO_SPACE_END) else " " + s
    return out


def _bbox(ws: list):
    """단어 목록의 바깥 상자 (x0, y0, x1, y1). 없으면 None. 단어는 (글자, x, y가운데, 높이, 폭)."""
    if not ws:
        return None
    return (min(w[1] for w in ws), min(w[2] - w[3] / 2 for w in ws),
            max(w[1] + w[4] for w in ws), max(w[2] + w[3] / 2 for w in ws))


def build_table(words: list, gap_factor: float = 1.0, bounds: list | None = None,
                boxes_out: list | None = None) -> list[list[str]]:
    """단어들을 행으로 묶고, 모든 행에서 공통으로 비어 있는 세로 띠를 열 경계로 삼는다.
    gap_factor: 열 경계로 볼 최소 간격 = gap_factor × 글자 높이 중앙값 (작을수록 열이 잘게 나뉨).
    bounds: 레코드 경계 y좌표(row_boundaries). 주면 경계 사이의 모든 줄을 한 행으로 합친다."""
    if not words:
        return []
    gap = gap_factor * statistics.median(w[3] for w in words)
    if bounds:
        import bisect
        groups: dict[int, list] = {}
        for w in words:
            groups.setdefault(bisect.bisect(bounds, w[2]), []).append(w)
        rows = [groups[k] for k in sorted(groups)]
        merge = True
    else:
        rows, merge = core.cluster_rows(words), False
    cols: list[list[float]] = []
    for s, e in sorted((w[1], w[1] + w[4]) for w in words):
        if cols and s - cols[-1][1] < gap:
            cols[-1][1] = max(cols[-1][1], e)
        else:
            cols.append([s, e])
    def col_of(w):
        cx = w[1] + w[4] / 2
        idx = next((i for i, (s, e) in enumerate(cols) if s <= cx <= e), None)
        if idx is None:
            idx = min(range(len(cols)), key=lambda i: abs((cols[i][0] + cols[i][1]) / 2 - cx))
        return idx

    table, boxes = [], []
    for r in rows:
        per = [[] for _ in cols]
        for w in r:
            per[col_of(w)].append(w)
        boxes.append([_bbox(c) for c in per])
        if merge:                                   # 레코드 안의 줄(위→아래)을 칸별로 이어붙인다
            # 줄은 '칸 안에서' 따로 묶는다 (레코드 전체에서 묶으면 썸네일 잡글자 같은 이웃 칸의 단어가 y로 이어져
            # 서로 다른 줄이 한 줄로 합쳐지고 칸 안의 글자 순서가 뒤바뀐다)
            table.append([_join_lines([" ".join(x[0] for x in ln) for ln in core.cluster_rows(c)]) if c else ""
                          for c in per])
        else:
            table.append([" ".join(x[0] for x in c) for c in per])
    keep = [i for i in range(len(cols)) if any(row[i] for row in table)]
    if boxes_out is not None:                       # 칸마다 이미지 위치(바깥 상자) — AI가 칸 그림만 잘라 읽을 때 쓴다
        boxes_out[:] = [[row[i] for i in keep] for row in boxes]
    return [[row[i] for i in keep] for row in table]


def split_blocks(rows: list[list]) -> list[list[list]]:
    """행(단어 목록)들을 세로 간격이 크게 벌어진 곳에서 블록(검색 폼 / 표 / 제목 …)으로 나눈다."""
    if not rows:
        return []
    ys = [sum(w[2] for w in r) / len(r) for r in rows]
    hh = statistics.median(w[3] for r in rows for w in r)
    gaps = [ys[i] - ys[i - 1] for i in range(1, len(rows))]          # gaps[i-1] = 행 i-1 → i 사이
    blocks = [[rows[0]]]
    for i in range(1, len(rows)):
        g = gaps[i - 1]
        nb = [gaps[j] for j in (i - 2, i) if 0 <= j < len(gaps)]    # 앞뒤 이웃 간격
        # 이웃 간격보다 확연히 넓고(×1.6) 글자 높이에 비해서도 충분히 큰(×4) 곳만 구역 경계로 본다.
        # → 일정한 행 간격의 표는 쪼개지지 않고, 폼/제목/표 사이의 큰 여백에서만 나뉜다.
        brk = bool(nb) and g > 1.6 * min(nb) and g > 4 * hh
        if brk:
            blocks.append([rows[i]])
        else:
            blocks[-1].append(rows[i])
    return blocks


_ODD_SYMBOLS = set("|~•*;『』“”`^<>{}[]\\=+_@#$ø")


def _weird_token(t: str) -> bool:
    """그림(썸네일)에서 OCR이 지어낸 글자 같은 단어: 한자, 한글+숫자/영문이 한 단어에 섞임, 이상한 기호."""
    hangul = any("가" <= c <= "힣" for c in t)
    if any("一" <= c <= "鿿" or "ぁ" <= c <= "ヿ" for c in t):
        return True
    if re.fullmatch(r"[\d,.\-]*\d[원월일년시분초개명건회층호번위점%]+", t):      # 26년, 10월, 5,000원 같은 정상 단위는 제외
        return False
    latin = [c for c in t if c.isascii() and c.isalpha()]
    if hangul and any(c.isdigit() for c in t):
        return True
    if hangul and latin and not all(c.isupper() for c in latin):            # DATA동기화(대문자 영문)는 정상, 니t젤은 이상
        return True
    return any(c in _ODD_SYMBOLS for c in t)


def picture_columns(table: list[list[str]]) -> set[int]:
    """썸네일 같은 '그림 열'을 찾는다: 비어 있지 않은 칸이 3개 이상이고 그 75% 이상이 '지어낸 글자'(_weird_token이 절반 이상)인 열.
    머리글 행(제목 글자)은 판단에서 뺀다. 상품코드처럼 영문·숫자뿐인 열, 제목처럼 정상 한글 열은 해당되지 않는다."""
    if not table:
        return set()
    start = 1 if _has_header(table[0]) else 0
    out = set()
    for ci in range(max(len(r) for r in table)):
        cells = [r[ci].strip() for r in table[start:] if ci < len(r) and r[ci].strip()]
        if len(cells) < 3:
            continue
        bad = sum(1 for s in cells if sum(_weird_token(t) for t in s.split()) * 2 >= len(s.split()))
        if bad >= 0.75 * len(cells):
            out.add(ci)
    return out


def blank_picture_columns(table: list[list[str]]) -> tuple[list[list[str]], set[int]]:
    """그림 열의 칸을 비운다(머리글 행은 유지). 열 자체는 남겨 엑셀 열 위치가 바뀌지 않게 한다."""
    cols = picture_columns(table)
    if not cols:
        return table, cols
    start = 1 if _has_header(table[0]) else 0
    return [[("" if (ci in cols and ri >= start) else v) for ci, v in enumerate(row)]
            for ri, row in enumerate(table)], cols


def trim_range(grid: list[list[str]]) -> tuple[int, int]:
    """trim_sparse가 남기는 행 범위 [lo, hi). (행 좌표를 표와 맞출 때 쓴다)"""
    if len(grid) < 3:
        return 0, len(grid)
    cnt = [sum(1 for c in r if c) for r in grid]
    ref = statistics.median(sorted(cnt, reverse=True)[:min(3, len(cnt))])
    lo, hi = 0, len(grid)
    while lo < hi and cnt[lo] < 0.5 * ref:
        lo += 1
    while hi > lo and cnt[hi - 1] < 0.5 * ref:
        hi -= 1
    return (lo, hi) if hi > lo else (0, len(grid))


def trim_sparse(grid: list[list[str]]) -> list[list[str]]:
    """표 앞/뒤에 붙은 제목·도구줄처럼 칸이 거의 비어 있는 행을 떼어낸다 (머리글보다 훨씬 적은 칸)."""
    lo, hi = trim_range(grid)
    return grid[lo:hi]


def _grid(rows: list[list], gap_factor: float, hh: float, boxes_out: list | None = None) -> list[list[str]]:
    """블록 하나를 행/열 표로. 열 경계는 '단어가 충분히 많은 행'(머리글·데이터 행)에서만 계산해서
    제목 같은 짧은 줄이 열을 합쳐 버리지 않게 한다. boxes_out을 주면 칸마다 이미지 위치(바깥 상자)를 채운다."""
    counts = sorted((len(r) for r in rows), reverse=True)
    ref = statistics.median(counts[:min(3, len(counts))])
    dense = [r for r in rows if len(r) >= 0.5 * ref] or rows
    gap = gap_factor * hh
    cols: list[list[float]] = []
    for s, e in sorted((w[1], w[1] + w[4]) for r in dense for w in r):
        if cols and s - cols[-1][1] < gap:
            cols[-1][1] = max(cols[-1][1], e)
        else:
            cols.append([s, e])
    table, boxes = [], []
    for r in rows:
        cells = [[] for _ in cols]
        for w in r:
            cx = w[1] + w[4] / 2
            idx = next((i for i, (s, e) in enumerate(cols) if s <= cx <= e), None)
            if idx is None:
                idx = min(range(len(cols)), key=lambda i: abs((cols[i][0] + cols[i][1]) / 2 - cx))
            cells[idx].append(w)
        table.append([_join_cell(c, hh) for c in cells])
        boxes.append([_bbox(c) for c in cells])
    keep = [i for i in range(len(cols)) if any(row[i] for row in table)]
    if boxes_out is not None:
        boxes_out[:] = [[row[i] for i in keep] for row in boxes]
    return [[row[i] for i in keep] for row in table]


def _join_cell(ws: list, hh: float) -> str:
    """한 셀 안의 단어들을 잇는다. '순수 숫자' 조각끼리 글자 간격 수준으로 붙어 있으면(OCR이 번호를 둘로 쪼갠 경우)
    공백 없이 붙인다. 날짜/시간('2026-11-05' + '14:58:20')처럼 정상적인 띄어쓰기는 그대로 둔다."""
    if not ws:
        return ""
    ws = sorted(ws, key=lambda w: w[1])
    out = ws[0][0]
    for a, b in zip(ws, ws[1:]):
        gap = b[1] - (a[1] + a[4])
        if gap < 0.2 * hh and a[0].isdigit() and b[0].isdigit():
            out += b[0]
        else:
            out += " " + b[0]
    return out


_NUM_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1",
                                 "S": "5", "B": "8"})
_STRICT_DT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_DATEISH = re.compile(r"^\d{4}\D\d{2}")
_ODD_CHARS = re.compile(r"[^\x00-\x7f가-힣ㄱ-ㆎ]")      # ASCII/한글 밖의 글자(石, 黴, 『 …)


def _digit_col_len(vals: list[str], min_n: int = 3):
    """열이 '고유번호(숫자만, 길이 일정)' 열이면 그 길이를, 아니면 None. (표본이 min_n개 미만이면 판단하지 않는다)"""
    ne = [v for v in vals if v.strip()]
    digs = [v for v in ne if v.isdigit() and len(v) >= 6]
    if len(digs) >= min_n and len(digs) >= 0.5 * len(ne):
        L, n = Counter(len(v) for v in digs).most_common(1)[0]
        if n >= 0.7 * len(digs):                 # 길이가 거의 같을 때만 '고유번호'로 본다 (mem_idx처럼 들쭉날쭉하면 제외)
            return L
    return None


def fix_columns(table: list[list[str]]) -> list[list[str]]:
    """같은 열의 다른 값들과 비교해서 OCR 오류를 바로잡는다 (머리글 1행 + 데이터 행이 3개 이상일 때).
     1) 고유번호 열: 숫자 조각으로 갈라진 값('31541 4295')을 열의 일반적인 길이(9자리)로 합친다
     2) 같은 값이 반복되는 열(예: '주문서비스'): 공백만 다른 값('주문서 비스')을 대표 값으로
     3) 날짜 열 쌍: 거의 항상 같은 두 열(재무연동날짜=신청일)에서 한쪽만 깨졌으면 다른 쪽 값으로
    다른 열과 비교할 근거가 없으면 건드리지 않는다."""
    if len(table) < 4:
        return table
    hdr = _has_header(table[0])
    head = [table[0]] if hdr else []
    body = [list(r) for r in (table[1:] if hdr else table)]
    ncol = max(len(r) for r in table)
    for r in body:
        r.extend([""] * (ncol - len(r)))
    for ci in range(ncol):
        vals = [r[ci] for r in body]
        ne = [v for v in vals if v.strip()]
        if len(ne) < 3:
            continue
        # 숫자 열(값의 70% 이상이 숫자/콤마/점)이면, 숫자 자리에 끼어든 숫자 닮은 글자를 숫자로 되돌린다.
        # 예: '9,9O0' → '9,900', '2I530' → '21530'. 글자가 절반 이상이면 진짜 글자로 보고 건드리지 않는다.
        pure = [v for v in ne if re.fullmatch(r"[\d,.\-]+", v)]
        fixable = {}
        for v in ne:
            if v not in pure and sum(c.isdigit() for c in v) >= 0.5 * len(v):
                v2 = v.translate(_NUM_CONFUSABLE)
                if re.fullmatch(r"[\d,.\-]+", v2):
                    fixable[v] = v2
        # 순수 숫자가 절반 이상이고, '고칠 수 있는 값'까지 합치면 80% 이상일 때만 숫자 열로 본다
        if len(ne) >= 3 and len(pure) >= 0.5 * len(ne) and len(pure) + sum(1 for v in ne if v in fixable) >= 0.8 * len(ne):
            for r in body:
                if r[ci] in fixable:
                    r[ci] = fixable[r[ci]]
        L = _digit_col_len(vals)
        if L:
            for r in body:
                v = r[ci]
                if re.fullmatch(r"\d+( \d+)+", v) and len(v.replace(" ", "")) == L:
                    r[ci] = v.replace(" ", "")
        v0, c0 = Counter(ne).most_common(1)[0]
        if c0 >= 3 and c0 >= 0.6 * len(ne) and not v0.isdigit():
            key = v0.replace(" ", "")
            for r in body:
                if r[ci] != v0 and r[ci].replace(" ", "") == key:
                    r[ci] = v0
    dtcols = [ci for ci in range(ncol) if sum(1 for r in body if _STRICT_DT.match(r[ci])) >= 3]
    for a, b in combinations(dtcols, 2):
        both = [(r[a], r[b]) for r in body if _STRICT_DT.match(r[a]) and _STRICT_DT.match(r[b])]
        if len(both) >= 3 and sum(x == y for x, y in both) >= 0.8 * len(both):
            for r in body:
                va, vb = r[a], r[b]
                if _STRICT_DT.match(va) and vb.strip() and not _STRICT_DT.match(vb):
                    r[b] = va
                elif _STRICT_DT.match(vb) and va.strip() and not _STRICT_DT.match(va):
                    r[a] = vb
    return head + body


def _has_header(row: list[str]) -> bool:
    """첫 행이 머리글인지: 머리글은 숫자가 든 칸이 적다 (스크롤로 머리글이 잘려 데이터 행이 첫 행일 수도 있음)."""
    cells = [c for c in row if c.strip()]
    if not cells:
        return True
    return sum(1 for c in cells if re.search(r"\d", c)) / len(cells) < 0.4


def uncertain_cells(table: list[list[str]]) -> set[tuple[int, int]]:
    """OCR이 틀렸을 가능성이 높은 셀 (행, 열) 집합. 엑셀에서 노란 배경으로 표시해 확인할 수 있게 한다.
     - 한글/영문/숫자/흔한 기호 밖의 이상한 글자가 섞인 셀
     - 날짜처럼 시작했지만 'YYYY-MM-DD hh:mm:ss' 형식이 아닌 셀
     - 고유번호 열인데 길이가 다르거나 숫자가 아닌 셀"""
    out: set[tuple[int, int]] = set()
    if len(table) < 2:
        return out
    ncol = max((len(r) for r in table), default=0)
    start = 1 if _has_header(table[0]) else 0
    lens = {}
    for ci in range(ncol):
        vals = [r[ci] if ci < len(r) else "" for r in table[start:]]
        lens[ci] = _digit_col_len(vals, min_n=6) if len(table) >= 4 else None    # 경고는 표본이 충분할 때만
    for ri, r in enumerate(table):
        if ri < start:
            continue
        for ci, v in enumerate(r):
            s = v.strip()
            if not s:
                continue
            if _ODD_CHARS.search(s):
                out.add((ri, ci)); continue
            if _DATEISH.match(s) and not (_STRICT_DT.match(s) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)):
                out.add((ri, ci)); continue
            L = lens.get(ci)
            if L and (not s.isdigit() or len(s) != L):
                out.add((ri, ci))
    return out


def list_blocks(words: list, gap_factor: float = 1.0, boxes_out: list | None = None) -> list[list[list[str]]]:
    """화면에서 찾은 모든 블록(표/폼/제목)을 각각 행/열 표로 돌려준다. (UI에서 고를 수 있게)
    boxes_out을 주면 블록마다 칸의 이미지 위치(바깥 상자) 표를 같은 순서로 채운다."""
    if not words:
        return []
    hh = statistics.median(w[3] for w in words)
    out, outb = [], []
    for b in split_blocks(core.cluster_rows(words)):
        bx: list = []
        g = _grid(b, gap_factor, hh, bx)
        if g:
            out.append(g); outb.append(bx)
    if boxes_out is not None:
        boxes_out[:] = outb
    return out


def block_row_ys(words: list, gap_factor: float = 1.0) -> list[list[float]]:
    """list_blocks와 같은 순서·같은 행 수로, 블록의 행마다 이미지 y좌표(행 가운데)를 돌려준다.
    (AI 보정이 표의 몇 행에 해당하는 이미지 조각을 잘라 보낼 때 쓴다)"""
    if not words:
        return []
    hh = statistics.median(w[3] for w in words)
    out = []
    for b in split_blocks(core.cluster_rows(words)):
        if _grid(b, gap_factor, hh):
            out.append([sum(w[2] for w in r) / len(r) for r in b])
    return out


def build_blocks(words: list, gap_factor: float = 1.0, main_only: bool = True) -> list[list[str]]:
    """화면 전체에서 '표'를 자동으로 찾아 행/열로 만든다.
    main_only=True: 가장 큰 표(행 수 × 열 수)만. False: 모든 블록을 빈 줄을 사이에 두고 차례로."""
    if not words:
        return []
    rows = core.cluster_rows(words)
    hh = statistics.median(w[3] for w in words)
    grids = [_grid(b, gap_factor, hh) for b in split_blocks(rows)]
    grids = [g for g in grids if g]
    if not grids:
        return []
    if main_only:
        return trim_sparse(max(grids, key=lambda g: len(g) * max(len(r) for r in g)))
    out: list[list[str]] = []
    for g in grids:
        if out:
            out.append([])
        out.extend(g)
    return out


_DT = re.compile(r"^(\d{4})\D?(\d{2})\D?(\d{2})\s+(\d{2})\D{0,2}\s?(\d{2})\D{0,2}(\d{2})$")
_D = re.compile(r"^(\d{4})[-•·.](\d{2})[-•·.](\d{2})$")


def fix_datetimes(table: list[list[str]]) -> list[list[str]]:
    """OCR이 망가뜨린 날짜/시간을 YYYY-MM-DD HH:MM:SS 형식으로 되돌린다.
    (예: '2026•11-05 14 5820', '2026-11-05 145625', '2026-11-05 1454.42')
    월/일/시/분/초가 범위를 벗어나면(=숫자를 잘못 읽은 것) 건드리지 않는다."""
    def fix(c: str) -> str:
        m = _DT.match(c.strip())
        if m:
            y, mo, d, hh, mi, ss = (int(x) for x in m.groups())
            if 1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mi < 60 and ss < 60:
                return f"{y:04d}-{mo:02d}-{d:02d} {hh:02d}:{mi:02d}:{ss:02d}"
            return c
        m = _D.match(c.strip())
        if m:
            y, mo, d = (int(x) for x in m.groups())
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        return c
    return [[fix(c) for c in row] for row in table]


_UNDERSCORE = re.compile(r"(?<=[A-Za-z0-9])[—–−](?=[A-Za-z])")


def fix_cells(table: list[list[str]]) -> list[list[str]]:
    """셀 단위 보정: 날짜/시간 형식 복원 + 영문 사이의 긴 줄표(—)를 밑줄(_)로 (예: 'mem—idx' → 'mem_idx')."""
    return [[_UNDERSCORE.sub("_", c) for c in row] for row in fix_datetimes(table)]


_DOT_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def fix_dot_thousands(table: list[list[str]]) -> list[list[str]]:
    """OCR이 천단위 콤마를 점으로 읽은 숫자(908.800)를 콤마로 되돌린다."""
    return [[c.replace(".", ",") if _DOT_THOUSANDS.match(c) else c for c in row] for row in table]


def to_tsv(table: list[list[str]], newline: str = "\n") -> str:
    return newline.join("\t".join(row) for row in table)


def from_tsv(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines()]


_NUM = re.compile(r"^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")


def _cell_value(s: str):
    import datetime as _dt
    s = s.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}):(\d{2}))?$", s)
    if m:                                       # 날짜/시간은 진짜 날짜 값으로 (서식은 save_xlsx에서 지정)
        try:
            y, mo, d, hh, mi, ss = (int(x) if x else 0 for x in m.groups())
            return _dt.datetime(y, mo, d, hh, mi, ss) if m.group(4) else _dt.date(y, mo, d)
        except ValueError:
            return s
    digits = s.replace(",", "")
    if _NUM.match(s) and not (len(s) > 1 and s.startswith("0") and not s.startswith("0.")) \
            and not (digits.isdigit() and len(digits) >= 12):      # 12자리 이상은 텍스트(지수 표기/정밀도 손실 방지)
        v = digits
        return float(v) if "." in v else int(v)
    return s


def save_xlsx(path: str, table: list[list[str]], img: Image.Image | None = None):
    """표 데이터를 '표' 시트에(숫자는 숫자로), 캡처 이미지를 '캡처' 시트에 저장."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "표"
    for r, row in enumerate(table, 1):
        for c, v in enumerate(row, 1):
            val = _cell_value(v)
            cell = ws.cell(r, c, val)
            if hasattr(val, "hour"):                       # datetime
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
            elif hasattr(val, "year"):                     # date
                cell.number_format = "yyyy-mm-dd"
    if img is not None:
        from openpyxl.drawing.image import Image as XLImage
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        cap = wb.create_sheet("캡처")
        cap.add_image(XLImage(buf), "A1")
    wb.save(path)
