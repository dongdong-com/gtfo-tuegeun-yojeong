"""OCR이 읽은 URL 보정. URL 구조(호스트/경로/파라미터 이름)와 알려진 값으로 글자 오류를 바로잡는다.
공백 제거, www→wwvv/wvm, zf_user→zf-user, view_type→view-type, utm_source→utm source,
Nkakao1→Nkaka01, rec_idx 뒤에 붙은 잡음 등. 100% 로컬 처리.

URL 형식이 바뀌면 아래 상수(HOST는 config.py/local_config.py, PATH_SEGS, KEYS, VALUES, DIGITS)만 고치면 된다."""
import difflib
import re

import config

SHORT_PREFIX = config.SHORT_PREFIX
SHORT_ID_LEN = 10          # 단축 URL ID 길이 (표본이 적을 때의 기준)
SHORT_ID_FIRST = "r"       # ID 첫 글자 (OCR이 이상한 글자로 읽었을 때 되돌림)
HOST = config.ORIGIN_HOST
PATH_SEGS = ["zf_user", "jobs", "relay", "view"]
KEYS = ["view_type", "rec_idx", "t_ref", "t_ref_content", "utm_source", "utm_medium",
        "utm_campaign", "utm_term", "adsCategoryItem"]
# 값이 고정인 파라미터: OCR 결과가 이 값과 한두 글자만 다르면 이 값으로 되돌린다
VALUES = {
    "view_type": ["public-recruit"],
    "t_ref": ["public-recruit"],
    "t_ref_content": ["generic"],
    "utm_source": ["Nkakao1"],
    "utm_medium": ["Nkakao"],
    "utm_campaign": ["recruit"],
    "adsCategoryItem": ["effect_bold"],
}
DIGITS = {"rec_idx": 8, "utm_term": 8}      # 숫자만, 이 자리수까지 (뒤의 잡음 글자 제거)

_SEP = r"[_\-—–]?"
_KEY_RE = re.compile(
    rf"(view{_SEP}type|rec{_SEP}idx|t{_SEP}ref{_SEP}content|t{_SEP}ref|"
    rf"utm{_SEP}[A-Za-z]{{0,10}}|adsCategory[Il]tem|"                 # utm* 는 'utmcampalgn', 'utm' 처럼 깨져도 잡는다
    rf"[^\sA-Za-z0-9&=?_\-][_\-]?ref)=", re.I)                    # 마지막: 't_ref' 의 t가 이상한 글자로 읽힌 경우
_NORM = {re.sub(r"[^a-z]", "", k.lower()): k for k in KEYS}
_NORM["ref"] = "t_ref"
_UTM_SUFFIX = ["source", "medium", "campaign", "term"]


def _infer_utm(val: str) -> str | None:
    """키가 'utm' 처럼 뭉개져서 어느 utm_* 인지 모를 때, 값으로 추정한다 (Nkakao1→source, Nkakao→medium,
    recruit→campaign, 숫자 8자리→term)."""
    v = val.rstrip("&")
    vd = v.translate(_DIGITIZE)
    # 숫자 8자리 날짜 → utm_term. 값 뒤에 잡음이 붙어도('20261109of') 대부분이 숫자면 날짜로 본다.
    if v and sum(c.isdigit() for c in vd) >= 6 and sum(c.isdigit() for c in vd) >= 0.6 * len(v):
        return "utm_term"
    best, best_r = None, 0.0
    for k in ("utm_source", "utm_medium", "utm_campaign"):
        for cand in VALUES.get(k, []):
            r = difflib.SequenceMatcher(None, v, cand).ratio() + (0.05 if len(v) == len(cand) else 0.0)   # 길이가 같으면 가산
            if r > best_r:
                best, best_r = k, r
    return best if best_r >= 0.75 else None


def _canon(raw: str, val: str = "") -> str:
    n = re.sub(r"[^a-z]", "", raw.lower()).replace("categoryltem", "categoryitem")
    if n in _NORM:
        return _NORM[n]
    if n.startswith("utm"):
        suf = n[3:]
        best = difflib.get_close_matches(suf, _UTM_SUFFIX, 1, 0.6) if suf else []
        if best:
            return "utm_" + best[0]
        return _infer_utm(val) or raw                       # 'utm' 만 남았거나 못 알아본 키: 값으로 추정
    return _NORM.get(n, raw)


def _fix_head(head: str) -> str:
    scheme = "http" if re.match(r"(?i)^http:", head) else "https"
    base = HOST.split(".", 1)[1]                            # 예: example.com
    i = head.lower().find(base)
    if i >= 0:                                              # 서브도메인 자리의 잡음(wvm, mw/. 등)은 통째로 www로
        path = head[i + len(base):]
    else:
        m = re.match(r"^[A-Za-z\d]*:?/{1,2}([^/]+)(/.*)?$", head)
        if not m:
            return head
        host, path = m.group(1), m.group(2) or ""
        if difflib.SequenceMatcher(None, host.lower(), HOST).ratio() < 0.75:
            return head                                     # 다른 사이트면 손대지 않는다
    q = "?" if path.endswith("?") else ""
    segs = [s for s in path.rstrip("?").split("/") if s]
    out = []
    for s in segs:
        c = difflib.get_close_matches(s.replace("-", "_"), PATH_SEGS, 1, 0.7)
        out.append(c[0] if c else s)
    return f"{scheme}://{HOST}/" + "/".join(out) + q


# 숫자만 들어가는 자리(rec_idx, utm_term)에서 OCR이 숫자를 닮은 글자로 읽은 경우: 지우지 말고 숫자로 되돌린다
# (예: '5541O778' 의 O 는 0. 지우면 자리수가 줄어 URL이 달라진다)
_DIGITIZE = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                           "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})


def _fix_val(key: str, val: str) -> str:
    if key in DIGITS:
        d = re.sub(r"\D", "", val.translate(_DIGITIZE))
        return d[:DIGITS[key]]
    for cand in VALUES.get(key, []):
        if val == cand:
            return val
        if abs(len(val) - len(cand)) <= 1 and difflib.SequenceMatcher(None, val, cand).ratio() >= 0.8:
            return cand
    return val


def fix_origin_url(raw: str) -> str:
    s = re.sub(r"\s+", "", raw)
    ms = list(_KEY_RE.finditer(s))
    if not ms:
        return s                                            # 알려진 파라미터가 없으면 공백만 제거
    head = _fix_head(s[:ms[0].start()])
    parts = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(s)
        val = s[m.end():end]
        dbl = val.endswith("&&")                            # 원본에 && 가 있는 경우 보존
        key = _canon(m.group(1), val)
        parts.append(f"{key}={_fix_val(key, val.rstrip('&'))}")
        if dbl and i + 1 < len(ms):
            parts.append("")
    return head + "&".join(parts)
