"""단축 URL ID의 글자 모양(폭/높이)으로 OCR 오류를 바로잡는다.

화면에서 구분 가능한 것
  O(대문자) / 0(숫자)  : 폭이 다르다 (O가 훨씬 넓다)
  1 / I·l             : 1은 윗부분 꺾임 때문에 폭이 더 넓다
  i / I·l             : i는 점과 줄기 사이가 비어 있다
  o / p·q             : p·q는 아래로 내려온다
  끝 글자 누락         : OCR이 놓친 좁은 글자를 찾아 보충 / 글리프 개수로 빠진 글자의 위치·종류를 찾는다
화면에서 구분 불가능한 것
  I(대문자 아이) / l(소문자 엘): 글꼴상 모양이 완전히 같다 → '모호'로 표시해 원본 대조(또는 접속 확인)를 요구한다."""
import string
from collections import Counter

import numpy as np
from PIL import Image

AMBIG = "Il"
UPPER_DIGIT_TALL = string.ascii_uppercase + string.digits + "bdfhkt"      # 키가 큰 글자
XHEIGHT = "acemnorsuvwxz"                                                 # 키가 작은 글자(x-height)


# OCR이 실제로 헷갈리는, 같은 키/모양 계열 글자 묶음. 접속 확인이 후보를 만들 때 쓴다.
CONFUSE_GROUPS = ["0OoDQ", "Il1", "5S", "8B", "2Z", "6Gb", "uv", "UV", "ce", "ao", "nh"]


def confusions(ch: str) -> list[str]:
    """ch와 헷갈리기 쉬운 다른 글자들."""
    out = []
    for g in CONFUSE_GROUPS:
        if ch in g:
            out += [c for c in g if c != ch and c not in out]
    return out


def _runs(mask: np.ndarray):
    """가로로 빈 열이 없는 덩어리(=글자 하나)들을 왼쪽부터 돌려준다."""
    cols = mask.any(axis=0)
    runs, st = [], None
    for x, v in enumerate(list(cols) + [False]):
        if v and st is None:
            st = x
        if not v and st is not None:
            sub = mask[:, st:x]
            rowhas = sub.any(axis=1)
            rows = np.where(rowhas)[0]
            top, bot = int(rows.min()), int(rows.max())
            runs.append({"x": st, "w": x - st, "top": top, "bot": bot,
                         "gap": bool((~rowhas[top:bot + 1]).any())})    # 점-줄기 사이 빈 줄 (i, j)
            st = None
    return runs


def _fix_char(ch: str, r: dict, cap_top: int, base: int, cap_h: int):
    """OCR이 읽은 글자 ch를 글리프 r의 모양에 맞게 고친다. 반환 (고친 글자, 모양이 맞는지)."""
    tall = r["top"] <= cap_top + 1
    desc = r["bot"] > base + 1
    if ch in "0Oo":
        ch = ("0" if r["w"] <= 0.7 * cap_h else "O") if tall else "o"
    elif ch in "pq" and not desc:
        ch = "o"
    elif ch in "1Il|i":
        if r["gap"]:
            ch = "i"
        elif r["w"] >= max(3, 0.3 * cap_h):
            ch = "1"
        elif ch in AMBIG:
            pass
        else:
            ch = "I"
    ok = ((ch.isupper() or ch.isdigit() or ch in "bdfhijklt") == tall) and ((ch in "gjpqy") == desc)
    return ch, ok


def _crop_runs(img: Image.Image, x_left: float, x_right: float, yc: float, h: float, extend: int):
    pad_y = int(h * 0.9 + 3)
    box = (max(0, int(x_left) - 2), max(0, int(yc) - pad_y),
           min(img.width, int(x_right) + extend), min(img.height, int(yc) + pad_y))
    a = np.asarray(img.crop(box).convert("L"), dtype=np.float32)
    if a.size == 0:
        return box, []
    thr = a.min() + 0.38 * (np.median(a) - a.min())      # 어둡게 잡아야 붙어 보이는 글자가 갈라진다
    return box, _runs(a < thr)


def refine_id(img: Image.Image, x_left: float, x_right: float, yc: float, h: float, ident: str):
    """ident(OCR이 읽은 ID)를 글리프 모양으로 보정한다.
    반환 (보정된 ID, 모호한 글자 위치 리스트(1부터), 메모).
    글리프 정렬에 실패하면 원문을 그대로 두고 헷갈리기 쉬운 글자 위치를 전부 의심으로 돌려준다."""
    suspects = [i for i, c in enumerate(ident, 1) if c in "Il1O0o"]
    k = len(ident)
    if k == 0:
        return ident, suspects, "영역 없음", {}, None
    box, runs = _crop_runs(img, x_left, x_right, yc, h, 12)
    if not runs:
        return ident, suspects, "영역 없음", {}, None
    wedge = int(x_right) - box[0]                       # OCR 단어 박스의 오른쪽 끝
    inside = [r for r in runs if r["x"] < wedge + 1]
    outside = [r for r in runs if r["x"] >= wedge + 1]
    chars = list(ident)

    def evaluate(chs, glyphs):
        """chs[i] 글자를 glyphs[i] 글리프와 맞춰 본다. 반환 (고친 글자들, 모양이 모순인 자리 {자리: 후보들}, 자리별 허용 글자)."""
        base = Counter(r["bot"] for r in glyphs).most_common(1)[0][0]   # 기준선
        cap_top = min(r["top"] for r in glyphs)
        cap_h = base - cap_top + 1
        cls = [_candidates_for(r, cap_top, base, cap_h) for r in glyphs]      # 자리마다 모양이 허용하는 글자들
        out, subs = [], {}
        for idx, (ch, r) in enumerate(zip(chs, glyphs)):
            ch2, ok = _fix_char(ch, r, cap_top, base, cap_h)
            if ok:
                out.append(ch2)
            else:
                # OCR 글자가 화면의 글자 모양(키 큰/작은, 내려쓰기, 점)과 모순 = 이 자리의 글자를 잘못 읽었다는 뜻.
                # 포기하지 말고, 그 자리를 모양에 맞는 후보 글자들로 바꿔 보도록 알려 준다 (접속 확인이 대입한다).
                out.append(ch)
                subs[idx] = [c for c in cls[idx] if c != ch]
        return out, subs, cls

    # 정렬 후보 두 가지를 만들어 모양이 더 잘 맞는 쪽을 고른다.
    #  A) OCR 단어 박스 안의 글리프 (+ 박스 밖에 남은 좁은 글자 하나 = OCR이 놓친 끝 I/l)
    #  B) 박스 밖까지 포함한 '오른쪽 끝 k개' — OCR 박스가 마지막 글자 앞에서 끝나면(넓은 글자가 박스 밖으로 밀리면)
    #     A는 글자가 한 칸씩 밀려 엉뚱한 자리가 모순으로 지목된다. 그때는 B가 맞는다.
    options = []
    chars_a = list(chars)
    if len(outside) == 1 and outside[0]["w"] <= 2 and outside[0]["x"] - wedge <= 6:
        glyphs_a = inside[-k:] + outside
        chars_a.append("I")
    else:
        glyphs_a = inside[-k:]
    if len(inside) >= k and len(glyphs_a) == len(chars_a):
        options.append((chars_a, glyphs_a))
    if len(runs) >= k and not (options and runs[-k:] == options[0][1][-k:]):
        options.append((chars, runs[-k:]))
    if not options:
        return ident, suspects, "글리프 부족", {}, None
    scored = [(len(ev[1]), n, ev) for n, ev in ((n, evaluate(c, g)) for n, (c, g) in enumerate(options))]
    _, _, (out, subs, cls) = min(scored, key=lambda t: (t[0], t[1]))      # 모순이 적은 쪽, 같으면 A

    res = "".join(out)
    if len(subs) > 3:                                   # 너무 많이 어긋나면 정렬 자체가 틀린 것: 원문 그대로
        return ident, suspects, "글자 모양 불일치(정렬 실패)", {}, None
    memo = (f"글자 모양 불일치 {len(subs)}곳({','.join(str(i + 1) for i in subs)}번째)" if subs else "")
    return res, [i for i, c in enumerate(res, 1) if c in AMBIG], memo, subs, cls


# 글자 잉크 폭(Arial Bold 12px, 글자 높이 10px 기준). 실제 화면에서 잰 값 + 같은 글꼴 자간으로 추정한 값.
NOMINAL_W = {
    "r": 4, "n": 5, "H": 7, "9": 6, "y": 6, "t": 4, "z": 5, "Z": 7, "4": 7, "X": 7, "w": 9, "8": 6, "q": 6, "K": 7,
    "T": 7, "M": 10, "5": 5, "i": 2, "I": 1, "p": 6, "l": 1, "D": 7, "2": 5, "R": 7, "v": 6, "h": 5, "Y": 7, "J": 4,
    "C": 6, "S": 6, "7": 5, "s": 5, "O": 8, "P": 6, "e": 5, "A": 7, "F": 4, "Q": 9,
    "B": 7, "E": 6, "G": 8, "L": 6, "N": 7, "U": 7, "V": 8, "W": 10, "0": 6, "1": 4, "3": 6, "6": 6,
    "a": 6, "b": 6, "c": 5, "d": 6, "f": 4, "g": 6, "j": 3, "k": 6, "m": 9, "o": 6, "u": 6, "x": 6,
}


def _class_candidates(r: dict, cap_top: int, base: int) -> list[str]:
    """글리프 모양(키/내려쓰기/점)으로 가능한 글자 후보."""
    tall = r["top"] <= cap_top + 1
    desc = r["bot"] > base + 1
    if r["gap"]:
        return list("ij") if desc else list("i")
    if desc:
        return list("gjpqy")
    if tall and r["w"] <= 2:
        return list("Il")                               # 폭 1~2px 막대: 대문자 I / 소문자 l
    if tall:
        return list(UPPER_DIGIT_TALL)
    return list(XHEIGHT)


def _candidates_for(r: dict, cap_top: int, base: int, cap_h: int) -> list[str]:
    """글리프 모양으로 가능한 글자 후보. 폭이 비슷한 글자를 앞에 둔다 (제외하지는 않는다 — 다른 글꼴이면 폭 표가
    틀릴 수 있으므로, 우선순위만 매기고 나머지도 뒤에 남겨 둔다)."""
    cands = _class_candidates(r, cap_top, base)
    w = r["w"] * 10.0 / max(cap_h, 1)                   # 글자 높이 10px 기준으로 환산한 폭
    near = [c for c in cands if c in NOMINAL_W and abs(NOMINAL_W[c] - w) <= 1.8]
    return near + [c for c in cands if c not in near]


def n_priority(r: dict, cap_top: int, base: int, cap_h: int) -> int:
    """_candidates_for 결과 앞쪽 몇 개가 '폭이 비슷한 우선 후보'인지."""
    cands = _class_candidates(r, cap_top, base)
    w = r["w"] * 10.0 / max(cap_h, 1)
    return sum(1 for c in cands if c in NOMINAL_W and abs(NOMINAL_W[c] - w) <= 1.8)


def find_missing(img: Image.Image, x_left: float, x_right: float, yc: float, h: float, ident: str,
                 total_len: int):
    """OCR이 글자를 하나 빠뜨린 ID(ident, total_len-1자)에서 빠진 글자의 위치와 후보 글자를 찾는다.

    화면의 글리프(글자 하나하나의 덩어리)를 오른쪽 끝에서 total_len개 취해서, 한 개를 제외하고 나머지가
    OCR 글자들과 모양(키/내려쓰기/점)이 모두 맞는 위치를 찾는다. 같은 모양이 연속되면 위치가 여럿일 수 있다.
    반환 {"pos": [0부터 센 삽입 위치들], "chars": [후보 글자들], "ident": 보정된 ident, "ambiguous": [...]} 또는 None."""
    k = len(ident)
    if k != total_len - 1:
        return None
    box, runs = _crop_runs(img, x_left, x_right, yc, h, 18)      # 빠진 글자가 OCR 박스 밖에 있을 수 있어 오른쪽을 넉넉히
    if len(runs) < total_len:
        return None
    tail = runs[-total_len:]
    base = Counter(r["bot"] for r in tail).most_common(1)[0][0]
    cap_top = min(r["top"] for r in tail)
    cap_h = base - cap_top + 1
    found = []
    for p in range(total_len):                           # p번째 글리프가 OCR이 놓친 글자라고 가정
        rest = tail[:p] + tail[p + 1:]
        fixed, bad = [], {}
        for idx, (ch, r) in enumerate(zip(ident, rest)):
            ch2, ok = _fix_char(ch, r, cap_top, base, cap_h)
            fixed.append(ch2 if ok else ch)
            if not ok:                                    # 이 자리 OCR 글자가 모양과 모순 → 다른 글자일 수 있다
                bad[idx] = [c for c in _candidates_for(r, cap_top, base, cap_h) if c != ch]
        found.append((p, "".join(fixed), bad))
    # 모양 불일치가 가장 적은 위치만 취한다 (누락 + 오인식 한 곳이 겹쳐도 찾을 수 있게 1곳까지 허용)
    best = min(len(b) for _, _, b in found)
    if best > 1:
        return None
    found = [f for f in found if len(f[2]) == best]
    fixed_ident = found[0][1]
    # 모양 불일치 자리는 '빠진 글자가 어디냐'에 따라 달라지므로 삽입 위치마다 따로 보관한다 {삽입위치: {자리: 후보들}}
    return {"pos": [p for p, _, _ in found], "ident": fixed_ident, "subs": {p: b for p, _, b in found},
            "chars": {p: _candidates_for(tail[p], cap_top, base, cap_h) for p, _, _ in found},
            "npri": {p: n_priority(tail[p], cap_top, base, cap_h) for p, _, _ in found},
            "ambiguous": [i for i, c in enumerate(fixed_ident, 1) if c in AMBIG]}
