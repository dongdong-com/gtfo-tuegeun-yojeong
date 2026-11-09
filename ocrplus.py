"""일반 텍스트용 고품질 OCR: 배율/선명화를 바꿔 여러 번 읽고, 열(카드·단)마다 줄 단위로 가장 좋은 결과를 고른다.

Windows OCR은 같은 그림도 배율·선명화에 따라 틀리는 글자가 달라진다(어떤 줄은 3배에서, 어떤 줄은 6배에서 맞는다).
 1) 여러 설정으로 읽는다 (넓은 이미지는 타일로 나눠 지정 배율 그대로 읽는다)
 2) 모든 단어 위치로 열을 나눈다 (카드 여러 장이 나란히 있어도 줄이 섞이지 않게)
 3) 열마다, 같은 높이의 줄 후보들 중 '글자다운 글자'가 가장 많은 줄을 고른다
 4) 후보들의 단어 수가 같으면 단어마다 다수결로 고른다
 5) 서로 다른 위치(사진 위 작은 글자처럼 한 설정에서만 읽힌 것)는 그대로 합친다"""
import re
import statistics
from collections import Counter

import numpy as np

import core
import tablegrid

# (배율, 선명화, 어둡게). '어둡게'(감마 1.8)는 얇고 흐린 작은 글자(웹 표의 10px 글씨)를 굵고 진하게 만들어 인식을 돕는다
# (사용자 표에서 `숨인완료→승인완료` 6/6 개선, 전체 일치율 0.896 → 0.93)
VARIANTS_FULL = [(3.0, True, False), (3.0, False, False), (4.0, True, False), (4.0, False, False),
                 (6.0, True, False), (6.0, False, False), (3.0, False, True), (4.0, False, True)]
VARIANTS_MID = [(3.0, True, False), (3.0, False, False), (4.0, True, False), (3.0, False, True)]
VARIANTS_BIG = [(3.0, False, False)]
_GAMMA_LUT = [int(255 * (v / 255) ** 1.8 + 0.5) for v in range(256)]

last_bounds: list = []        # 마지막 read_words에서 찾은 열 경계 [(x0, x1), …] (열이 없으면 한 구간)
last_vocab: set = set()       # 마지막 read_words에서 '어느 설정이든 한 번이라도 읽은' 단어들 (AI 보정이 OCR이 읽은 적 없는 글자로 바꾸는지 가려내는 데 쓴다)
_PUNCT = set(".,:;!?()[]{}<>/-~%&+'\"·…@#*=_₩$")


def _is_valid(ch: str) -> bool:
    o = ord(ch)
    return (0xAC00 <= o <= 0xD7A3) or ch.isascii() and (ch.isalnum() or ch in _PUNCT)


def line_score(text: str) -> float:
    """글자다운 글자(한글/영문/숫자/흔한 기호)는 +1, 엉뚱한 기호·한자·특수문자는 -3."""
    s = 0.0
    for ch in text:
        if ch.isspace():
            continue
        if not _is_valid(ch):
            s -= 3
        elif ch.isalnum() or ch in "[]()":
            s += 1
        elif ch in ".,":
            s += 0.5                                     # 마침표/쉼표는 조금만 (엔진이 설정에 따라 떨어뜨리곤 한다). '-!/' 같은 부호는 0점
    s -= 3.0 * len(re.findall(r"\d[가-힣]\d", text))      # 1예0억 처럼 숫자 사이에 낀 한글은 오인식
    s -= 3.0 * len(re.findall(r"[가-힣][0-9A-Za-z]{1,3}[가-힣]", text))   # 하0H기 처럼 한글 사이에 낀 숫자/영문도 오인식 (한글 '애'가 'o'+'H'로 읽히는 식)
    s -= 2.5 * len(re.findall(r"(?<=[a-z])[Il](?=[A-Z])|(?<=[a-z])I+(?=[a-z])", text))   # Hello → HeIIo 처럼 소문자 사이의 대문자 I
    return s - 2.0 * len(text.split())                 # 단어가 잘게 쪼개진 후보('생산 품질부문')보다 붙은 후보를 선호


def _acceptable(text: str, min_alnum: int = 2) -> bool:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return False
    bad = sum(1 for c in chars if not _is_valid(c))
    if bad > 0.34 * len(chars):
        return False
    return sum(1 for c in chars if c.isalnum()) >= min_alnum    # '4', '-가' 같은 한 글자 잡음 줄은 버린다 (표는 '0', '1' 같은 한 글자 칸이 있어 1로 낮춘다)


def _variants(img):
    px = img.width * img.height
    if px > 4_000_000:
        return VARIANTS_BIG
    if px > 1_200_000:
        return VARIANTS_MID
    return VARIANTS_FULL


def _columns(img, words):
    """이미지에서 '위아래로 끝까지 배경색뿐인 세로 띠'를 찾아 열(카드·단) 경계를 구한다. 없으면 [(-inf, inf)].
    (사진 위 글자 같은 잡음 단어가 있어도 흔들리지 않도록 단어가 아니라 그림으로 판단한다)"""
    g = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = g.shape
    if w < 200 or not words:
        return [(-1e9, 1e9)]
    # 위아래로 한 가지 색(배경)뿐인 세로 띠는 False, 글자·그림이 지나가면 True (가장자리 선 몇 px는 무시하도록 비율로 판단)
    ink = (np.abs(g - np.median(g, axis=0)) > 20).mean(axis=0) > 0.03
    hh = statistics.median(x[3] for x in words)
    gap_min = max(0.7 * hh, 10)                                  # 카드 사이 여백(약 20px)도 잡도록. 한 줄 글자 사이는 위아래로 끝까지 비지 않는다
    cuts, run = [], 0
    for x in range(w):
        if not ink[x]:
            run += 1
        else:
            if run >= gap_min and x - run > 0:
                cuts.append(x - run / 2)
            run = 0
    bounds = [-1e9] + cuts + [1e9]
    spans = list(zip(bounds[:-1], bounds[1:]))
    spans = [s for s in spans if sum(1 for x in words if s[0] <= x[1] + x[4] / 2 < s[1]) >= 2]   # 글자가 없는 띠는 제외
    return spans if len(spans) >= 2 else [(-1e9, 1e9)]


_DIGRAPH = re.compile(r"(?<=[가-힣(\[])[0oO][Hh](?=[가-힣)\]])")          # 한글 사이의 'oH'/'0H' → 한글 '애' ('애'의 ㅇ+ㅐ가 두 글자로 읽힘)


def _fix_digraphs(words):
    return [((_DIGRAPH.sub("애", w[0]),) + tuple(w[1:])) if _DIGRAPH.search(w[0]) else w for w in words]


def _lines_of(words):
    out = []
    for ln in core.cluster_rows(_fix_digraphs(words)):
        ln = [x for x in ln if sum(1 for c in x[0] if not _is_valid(c)) * 2 < len(x[0])]   # 아이콘이 만든 기호 위주 단어는 버린다 (立, 그云1夕`하 …)
        if not ln:
            continue
        hh = statistics.median(x[3] for x in ln)
        segs, cur = [], [ln[0]]
        for a, b in zip(ln, ln[1:]):                               # 크게 벌어진 칸은 따로 취급 (한 줄 안의 제목/날짜 등을 각자 고르기 위해)
            if b[1] - (a[1] + a[4]) > 2.0 * hh:
                segs.append(cur); cur = []
            cur.append(b)
        segs.append(cur)
        for sg in segs:
            text = " ".join(w[0] for w in sg)
            out.append({"w": sg, "text": text, "y": sum(w[2] for w in sg) / len(sg),
                        "h": max(w[3] for w in sg), "x0": min(w[1] for w in sg),
                        "x1": max(w[1] + w[4] for w in sg), "score": line_score(text)})
    return out


def _overlap(a, b):
    w = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
    if w <= 0:
        return 0.0
    return max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])) / w


def _pick(lines, min_alnum: int = 2):
    """한 열의 모든 설정 줄 후보 → 최종 줄 목록."""
    lines = sorted((l for l in lines if _acceptable(l["text"], min_alnum)), key=lambda l: l["y"])
    groups, cur = [], []
    for l in lines:                                                  # 같은 높이끼리 묶기
        if cur and abs(l["y"] - cur[-1]["y"]) < 0.6 * max(l["h"], cur[-1]["h"]):
            cur.append(l)
        else:
            if cur:
                groups.append(cur)
            cur = [l]
    if cur:
        groups.append(cur)
    chosen = []
    for g in groups:
        g.sort(key=lambda l: -l["score"])
        picked = []
        for l in g:
            if all(_overlap(l, p) < 0.3 for p in picked):            # 겹치지 않는 위치의 줄은 보완 관계라 함께 쓴다
                picked.append(l)
        for best in picked:
            alts = [l for l in g if l is best or _overlap(l, best) >= 0.6]
            same = [l for l in alts if len(l["w"]) == len(best["w"])]
            words = list(best["w"])
            if len(same) >= 3:                                       # 단어 수가 같은 후보가 3개 이상이면 단어별 다수결
                new = []
                for i, w in enumerate(best["w"]):
                    votes = Counter(l["w"][i][0] for l in same)
                    top, n = votes.most_common(1)[0]
                    if (top != w[0] and n > votes[w[0]] and w[0].rstrip(".,") != top    # 마침표만 다른 경우는 다수결로 지우지 않는다
                            and line_score(top) >= line_score(w[0])):                   # 다수결이 더 '글자다울' 때만 따른다 (HeIIo 다수 → Hello 소수)
                        w = (top,) + tuple(w[1:])
                    new.append(w)
                words = new
            if len(same) >= 3:                                       # 글자 수가 같은 후보끼리는 글자 단위 다수결 (율/을처럼 한 글자만 갈리는 경우)
                new = []
                for i, w in enumerate(words):
                    cands = [l["w"][i][0] for l in same if len(l["w"][i][0]) == len(w[0])]
                    chars = list(w[0])
                    if len(cands) >= 3:
                        for p in range(len(chars)):
                            votes = Counter(c[p] for c in cands)
                            top, n = votes.most_common(1)[0]
                            if top != chars[p] and n > votes[chars[p]] and n >= 2 and _is_valid(top):
                                chars[p] = top
                    new.append((("".join(chars)),) + tuple(w[1:]))
                words = new
            chosen.append(words)
    return chosen


def read_words(img, scale: float = 3.0, sharp: bool = True, lang: str = "ko", progress=None, min_alnum: int = 2) -> list:
    """img를 여러 설정으로 읽어 합친 단어 목록 [(text, x, yc, h, w)]을 돌려준다 (compose_text에 바로 쓸 수 있다)."""
    variants = list(_variants(img))
    if (scale, sharp, False) not in variants and len(variants) > 1:
        variants[-1] = (scale, sharp, False)
    runs = []
    dark = None
    for i, (sc, sh, gm) in enumerate(variants, 1):
        if progress:
            progress(f"OCR {i}/{len(variants)} (배율 {sc:g}{' 선명화' if sh else ''}{' 어둡게' if gm else ''})")
        try:
            if gm and dark is None:
                dark = img.convert("RGB").point(_GAMMA_LUT * 3)
            runs.append(tablegrid.ocr_tall(dark if gm else img, scale=sc, sharp=sh, tile=True, lang=lang))
        except Exception:
            if not runs and i == len(variants):
                raise
    union = [w for r in runs for w in r]
    if not union:
        return []
    out = []
    global last_bounds, last_vocab
    last_vocab = {w[0] for r in runs for w in _fix_digraphs(r)}
    last_bounds = _columns(img, union)
    for lo, hi in last_bounds:
        cand = []
        for r in runs:
            col = [w for w in r if lo <= w[1] + w[4] / 2 < hi]
            cand.extend(_lines_of(col))
        for words in _pick(cand, min_alnum):
            out.extend(words)
    return _dedupe(out)


def _dedupe(words: list) -> list:
    """같은 자리의 같은 글자가 여러 번 나오는 것을 하나로 줄인다. 설정마다 단어 상자의 세로 위치가 몇 px씩 달라서
    (작은 글자일수록 글자 높이보다 크게 어긋남) 줄 묶기가 갈라지면 '5,000 5,000 5,000'처럼 중복되기 때문이다."""
    kept: list = []
    for w in sorted(words, key=lambda w: (-line_score(w[0]), w[2])):       # 글자다운 단어를 먼저 남긴다
        dup = False
        for k in kept:
            ov = min(w[1] + w[4], k[1] + k[4]) - max(w[1], k[1])
            hh = max(w[3], k[3])
            if ov > 0.6 * min(w[4], k[4]) and abs(w[2] - k[2]) < 1.1 * hh:
                dup = True
                break
            if w[0] == k[0] and abs(w[2] - k[2]) < 1.7 * hh and abs(w[1] - k[1]) < 3 * hh:    # 같은 글자가 설정마다 위·옆으로 어긋난 중복 (세로로 16px까지 어긋나는 일이 있다)
                dup = True
                break
        if not dup:
            kept.append(w)
    return sorted(kept, key=lambda w: (w[2], w[1]))
