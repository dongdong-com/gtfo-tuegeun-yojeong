"""단축 URL 접속 확인 (선택 기능, 기본 꺼짐).

OCR만으로 구분할 수 없는 I(대문자 아이)/l(소문자 엘) 후보를 만들어 단축 URL 서버에 HEAD 요청을 보내고,
연결되는 원본 URL의 rec_idx가 화면의 원본 URL과 같은 후보를 정답으로 확정한다.
※ 이 기능은 단축 URL ID를 단축 URL 서버(short.example)로 보낸다. 화면 이미지는 보내지 않는다."""
import concurrent.futures as cf
import http.client
import itertools
import re
import threading
import time
from urllib.parse import urlsplit

import idfix
import urlfix

WORKERS = 8                       # 동시에 보내는 요청 수 (단축 URL 서버에 부담이 가지 않는 수준)
CHUNK = 16                        # 한 번에 묶어 보내는 후보 수. 앞쪽 후보가 먼저 이기도록 묶음 안에서는 순서대로 판정한다
ID_TIME_LIMIT = 25.0              # ID 하나의 복구 탐색 시간 제한(초)
MAX_CANDIDATES = 40
MAX_MISSING_CANDIDATES = 700      # 글자 누락/모양 불일치 복구 시 시도할 최대 후보 수 (HEAD 요청 수)
MAX_WIDE_CANDIDATES = 300         # 0/O/o·I/l/1 을 넓게 바꿔 보는 2단계 후보 수 상한
FAMILY = {"I": "Il", "l": "Il", "1": "1Il", "O": "O0o", "0": "O0o", "o": "O0o"}


_local = threading.local()          # 스레드마다 연결 하나를 재사용한다 (요청마다 새로 연결하지 않음)
_pool_obj: cf.ThreadPoolExecutor | None = None


def _pool() -> cf.ThreadPoolExecutor:
    global _pool_obj
    if _pool_obj is None:
        _pool_obj = cf.ThreadPoolExecutor(WORKERS, thread_name_prefix="shortverify")
    return _pool_obj


def location_of(ident: str, timeout: float = 6.0) -> str | None:
    """단축 URL이 가리키는 주소(Location). 접속 실패는 None, 리다이렉트 아님은 빈 문자열.
    리다이렉트를 따라가지 않고 Location 헤더만 본다. 연결은 스레드마다 재사용한다."""
    if not re.fullmatch(r"[A-Za-z0-9]+", ident):
        # OCR 잡글자('『', '@' 등)가 섞인 ID는 요청 자체를 만들 수 없다(한글 등은 요청줄 인코딩 오류).
        # 이를 '접속 실패(None)'로 돌려주면 서버 문제로 오판해 탐색을 접으므로, '없는 ID'로 취급한다.
        return ""
    u = urlsplit(urlfix.SHORT_PREFIX + ident)
    for attempt in (0, 1):                           # 서버가 놀던 연결을 끊었으면 새 연결로 한 번 더
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = _local.conn = http.client.HTTPConnection(u.netloc, timeout=timeout)
        try:
            conn.request("HEAD", u.path, headers={"User-Agent": "GTFO/1.0"})
            r = conn.getresponse()
            r.read()
            return r.getheader("Location") or ""
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None
    return None


def candidates(ident: str, positions: list[int]) -> list[str]:
    """OCR 결과를 첫 후보로, 모호한 위치의 글자를 가능한 글자로 바꾼 후보들(최대 MAX_CANDIDATES)."""
    opts = []
    for p in positions:
        c = ident[p - 1]
        opts.append(FAMILY.get(c, c))
    out = [ident]
    for combo in itertools.product(*opts):
        s = list(ident)
        for p, ch in zip(positions, combo):
            s[p - 1] = ch
        s = "".join(s)
        if s not in out:
            out.append(s)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def _is_generic(loc: str) -> bool:
    """존재하지 않는 ID가 가는 일반 페이지(사이트 루트 / zf_user 첫 화면)인가."""
    return re.fullmatch(r"https?://[^/]+(/zf_user)?/?", loc.strip()) is not None


def _matches(loc: str, origin: str) -> bool:
    """origin(화면의 원본 URL)이 있으면 rec_idx가 같은지, 없으면(단축 URL만 선택) '존재하는 ID인지'로 판단한다."""
    if not origin:
        return bool(loc.strip()) and not _is_generic(loc)
    m = re.search(r"rec_idx=(\d+)", origin)
    if m:
        return ("rec_idx=" + m.group(1)) in loc
    return loc == origin


def verify(rec: dict, pump=None, timeout: float = 6.0, budget: dict | None = None, cancel=None) -> str:
    """rec(urlrec.extract 결과 1건)의 단축 URL을 접속으로 확인/확정한다. rec를 갱신하고 상태 문자열을 돌려준다.
    상태: '확인됨' | '확정됨' | '불일치' | '접속 불가' | '건너뜀'"""
    ident, origin = rec.get("id", ""), rec.get("origin", "")
    if not ident:
        return "건너뜀"
    cands = candidates(ident, rec.get("ambiguous", []))
    miss = rec.get("missing")
    if miss:
        # OCR이 글자 하나를 빠뜨린 ID: 빠진 위치(여러 곳일 수 있음, 오른쪽 끝부터)와 글리프 모양으로 좁힌 후보 글자를
        # 모두 끼워 넣어 서버에 존재하는 ID를 찾는다. (I/l 모호 글자 변형도 함께)
        # 기존 글자(0/O/o, I/l/1)도 한 곳은 틀렸을 수 있으므로 한 글자씩 바꾼 변형도 함께 쓴다
        # 후보 순서가 중요하다 (상한 안에서 정답에 먼저 닿아야 한다). 가능성이 높은 것부터 '전체'를 한 번씩 훑는다:
        #   ① 원문 글자 그대로 × 모든 삽입 위치 × 폭이 비슷한 글자  ② 같은 위치 × 나머지 글자
        #   ③ 한 글자를 바꾼 변형(I/l, 0/O/o, 모양 불일치 자리) × 위치 × 폭이 비슷한 글자  ④ 그 변형 × 나머지 글자
        positions = sorted(miss["pos"], reverse=True)                  # 오른쪽 끝 위치부터
        npri = miss.get("npri", {})
        plain = [ident]
        ambig_variants = cands[1:] + _wide_candidates(ident, None, max_changes=1)

        def sub_variants(p):
            return [ident[:q] + ch + ident[q + 1:] for q, chars in (miss.get("subs", {}).get(p) or {}).items() for ch in chars]

        def insert(bases_for, part):
            out = []
            for p in positions:
                chars = miss["chars"][p]
                n = npri.get(p, len(chars))
                sel = chars[:n] if part == "pri" else chars[n:]
                for base in bases_for(p):
                    out += [base[:p] + ch + base[p:] for ch in sel]
            return out

        full = (insert(lambda p: plain + sub_variants(p)[:0], "pri") + insert(lambda p: plain, "rest") +
                insert(lambda p: ambig_variants + sub_variants(p), "pri") +
                insert(lambda p: ambig_variants + sub_variants(p), "rest"))
        cands = list(dict.fromkeys(full))[:MAX_MISSING_CANDIDATES]
    subs = rec.get("subs")
    if subs and not miss:
        # 글자 모양이 OCR 글자와 모순인 자리: 그 자리만 모양에 맞는 후보 글자로 바꿔 본다 (한 곳씩 → 두 곳씩)
        extra = []
        for base in cands[:6]:
            for p, chars in subs.items():
                extra += [base[:p] + ch + base[p + 1:] for ch in chars]
        for (p1, c1), (p2, c2) in itertools.combinations(sorted(subs.items()), 2):
            for a in c1:
                for b in c2:
                    s = list(ident)
                    s[p1], s[p2] = a, b
                    extra.append("".join(s))
        cands = list(dict.fromkeys(cands + extra))[:MAX_MISSING_CANDIDATES]
    tried: set[str] = set()
    failed = 0
    stopped = {"why": ""}                                    # 시간 제한/중단으로 탐색을 접은 이유
    id_deadline = time.time() + ID_TIME_LIMIT

    def should_stop(use_time: bool = True) -> bool:
        if cancel and cancel():
            stopped["why"] = "사용자 중단"
            return True
        now = time.time()
        if use_time and (now > id_deadline or (budget is not None and budget.get("deadline") and now > budget["deadline"])):
            stopped["why"] = "시간 제한"
            return True
        return False

    def run(batch: list[str], first_is_plain: bool, counted: bool = True, use_time: bool = True):
        """batch를 접속해 본다 (CHUNK개씩 WORKERS개 동시 요청). 반환: 상태 문자열 또는 None(못 찾음).
        한 묶음의 결과는 batch 순서대로 판정하므로 앞쪽(가능성 높은) 후보가 항상 먼저 이긴다.
        counted=True 인 '넓게 찾는' 후보는 한 번의 복사 전체에서 쓸 수 있는 요청 총량(budget)을 넘지 않게 센다."""
        nonlocal failed
        todo = [(i, c) for i, c in enumerate(batch) if c not in tried]
        for s in range(0, len(todo), CHUNK):
            chunk = todo[s:s + CHUNK]
            if counted and budget is not None:
                if budget["left"] <= 0:
                    stopped["why"] = "요청 총량 소진"
                    return None                              # 총량 소진: 이 ID의 더 넓은 탐색은 포기
                chunk = chunk[:budget["left"]]
                budget["left"] -= len(chunk)
            if should_stop(use_time):
                return None
            tried.update(c for _, c in chunk)
            if budget is not None:
                budget["used"] = budget.get("used", 0) + len(chunk)
            if pump:
                pump()
            locs = list(_pool().map(lambda t: location_of(t[1], timeout), chunk))      # 입력 순서 유지
            for (i, c), loc in zip(chunk, locs):
                if loc is not None and _matches(loc, origin):
                    rec["id"] = c
                    rec["short"] = urlfix.SHORT_PREFIX + c
                    rec["ambiguous"] = []
                    rec["zero_o"] = []
                    rec.pop("subs", None)
                    rec["note"] = ""
                    recovered = rec.pop("missing", None) is not None    # 빠진 글자를 찾아낸 경우도 '확정'
                    return "확인됨" if (first_is_plain and i == 0 and not recovered) else "확정됨"
            failed += sum(1 for loc in locs if loc is None)
            if failed >= 2 and all(loc is None for loc in locs):
                return "접속 불가"
        return None

    st = run(cands[:1], True, counted=False, use_time=False)   # OCR이 읽은 ID 그대로는 총량·시간 제한과 무관하게 항상 확인한다
    if st:
        return st
    reads = rec.get("reads") or []
    if reads:                                            # 여러 배율로 다시 읽은 결과와 자리별 투표 후보
        st = run(_vote_candidates(ident, reads), False)
        if st:
            return st
    st = run(cands[1:], False, counted=bool(miss or subs))    # 변형 후보: 글자 누락/모양 불일치로 넓게 늘어난 경우만 총량에 센다
    if st:
        return st
    if not miss:
        # 2단계: OCR이 글자 모양으로 '해결했다고 본' 0/O/o 도 틀렸을 수 있다 (모양 규칙이 틀리면 후보로 시도할 방법이 없었음).
        # 0·O·o, I·l·1 글자 위치에서 1~3개를 다른 글자로 바꿔 본다 (바꾼 글자가 적은 후보부터).
        st = run(_wide_candidates(ident, rec.get("cls"), limit=(MAX_MISSING_CANDIDATES if subs else None), extra=subs), False)
        if st:
            return st
    if stopped["why"]:
        rec["note"] = (rec.get("note", "") + f" · 복구 탐색 중단({stopped['why']})").strip(" ·")
    return "불일치"


def _vote_candidates(ident: str, reads: list[str]) -> list[str]:
    """여러 배율로 읽은 결과(reads)와 ident를 자리별로 투표해서 만든 후보들. 읽은 그대로의 결과가 먼저 온다.
    읽을 때마다 다른 자리가 틀리는 경우(예: 한 번은 7번째, 한 번은 10번째)에 서로의 정답 글자를 합칠 수 있다."""
    reads = [x for x in reads if len(x) == len(ident)]
    if not reads:
        return []
    out = list(reads)
    opts = [list(dict.fromkeys([ident[p]] + [x[p] for x in reads])) for p in range(len(ident))]
    diff = [p for p, o in enumerate(opts) if len(o) > 1][:6]
    if diff:
        for combo in itertools.product(*[opts[p] for p in diff]):
            s = list(ident)
            for p, ch in zip(diff, combo):
                s[p] = ch
            out.append("".join(s))
    return list(dict.fromkeys(out))[:300]


def _wide_candidates(ident: str, cls=None, max_changes: int = 3, limit: int = None, extra=None) -> list[str]:
    """ident에서 헷갈리기 쉬운 글자(0/O/o, I/l/1, 5/S, 8/B, 2/Z, 6/G, u/v …) 위치 중 1~max_changes개를
    같은 계열의 다른 글자로 바꾼 후보들 (바꾼 수가 적은 것부터).
    cls(자리별로 글자 모양이 허용하는 글자들)가 있으면 모양과 맞지 않는 글자는 후보에서 뺀다.
    extra({자리: 후보 글자들})는 '모양이 모순이거나 잡글자인 자리'의 후보로, 혼동 후보와 함께 조합한다."""
    limit = limit or MAX_WIDE_CANDIDATES
    extra = extra or {}

    def alts_of(p):
        a = idfix.confusions(ident[p])
        if cls and p < len(cls) and cls[p]:
            a = [x for x in a if x in cls[p]]
        if p in extra:
            a = list(dict.fromkeys(list(extra[p]) + a))
        return [x for x in a if x != ident[p]]

    # 알 수 없는 글자(extra)가 있는 자리를 먼저, 그다음 앞쪽 자리 순으로 최대 10곳
    pos = sorted((i for i in range(len(ident)) if alts_of(i)), key=lambda p: (p not in extra, p))[:10]
    out: list[str] = []
    for r in range(1, max_changes + 1):
        for subset in itertools.combinations(pos, r):
            alts = [alts_of(p) for p in subset]
            for combo in itertools.product(*alts):
                s = list(ident)
                for p, ch in zip(subset, combo):
                    s[p] = ch
                out.append("".join(s))
                if len(out) >= limit:
                    return out
    return out
