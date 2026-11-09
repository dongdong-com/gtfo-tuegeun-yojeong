"""OCR 단어 → (순번, 원본 URL, 단축 URL) 레코드.
표의 열 경계에 의존하지 않고, 레코드 영역 안에서 URL을 직접 조립한다.
 - 원본 URL: 'http' 로 시작하는 가장 왼쪽 열의 모든 줄을 이어붙인 뒤 urlfix로 보정
 - 단축 URL: '/s/' 뒤의 ID만 취하고 접두어는 고정, ID는 idfix로 글자 모양 보정"""
import difflib
import re
import string
import unicodedata
from collections import Counter

from PIL import Image

import config
import core
import idfix
import urlfix


def _is_url_start(t: str) -> bool:
    return "://" in t or re.match(r"(?i)^(h?t?tps?|ttp)[:/]", t) is not None


# '/s/' 의 슬래시를 OCR이 '!', '|', '\' 로 읽는 일이 있다 (예: 'short.example!s/rjevOij80c')
_TAIL = re.compile(r"[/!|\\]\s?s\s?[/!|\\]([^/\s!|\\]{3,})$")
# 슬래시를 l, I, 1 로까지 읽은 경우('short.examplels/…'). 오탐을 막으려고 호스트가 short.example 비슷할 때만 쓴다.
_TAIL_LOOSE = re.compile(r"[/!|\\lI1]\s?s\s?[/!|\\lI1]([^/\s!|\\]{3,})$")


def _short_id(t: str):
    """'…/s/ID' 꼴이면 ID 글자를, 아니면 None. 구분 슬래시가 !,|,\\ (또는 l,I,1)로 깨져도 알아본다."""
    t = t.strip()
    m = _TAIL.search(t)
    if m:
        return m.group(1)
    m = _TAIL_LOOSE.search(t)
    if m and _host_like(t):
        return m.group(1)
    return None


def _host_like(t: str) -> bool:
    """단어의 호스트 부분이 'short.example'과 비슷한가. 접두어가 'http:〃Short.example', 'ttp//short.example',
    'fittp://short.example', 'ram.in', 'short.example.' 처럼 깨져도 알아본다."""
    t = t.strip()
    m = _TAIL.search(t) or _TAIL_LOOSE.search(t)
    head = t[:m.start()] if m else t
    # 접두어(http:// 가 깨진 것 포함)를 ':' 또는 '//' 까지 통째로 제거
    host = re.sub(r"^.*?(?::\W{0,3}|//)", "", head, count=1)
    host = re.split(r"[/!|\\]", re.sub(r"^\W+", "", host).lower())[0]
    return difflib.SequenceMatcher(None, host, config.SHORT_HOST.lower()).ratio() >= 0.75


def _is_short(t: str) -> bool:
    """완전한 단축 URL 단어인가? (호스트가 short.example 비슷 + '/s/' 뒤에 ID 6자 이상)"""
    sid = _short_id(t)
    return sid is not None and len(sid) >= 6 and _host_like(t)


def _is_short_like(t: str) -> bool:
    """단축 URL '같은' 단어인가? ID가 잘렸거나 짧아도(예: 'short.example/s/rc5t1') 단축 URL 줄로 취급한다.
    그렇지 않으면 그 줄이 '원본 URL 시작'으로 잘못 분류되어 추출 전체가 틀어진다."""
    return _is_url_start(t) and config.ORIGIN_BASE.lower() not in t.lower() and _host_like(t)


def normalize_short_text(s: str) -> str:
    """셀/줄 안의 깨진 단축 URL을 'http://short.example/s/ID'로 바로잡는다 ('복사하기' 버튼 글자는 제거).
    ID는 OCR 그대로다 (I/l 확정은 접속 확인이 한다). 단축 URL이 아니면 원문을 그대로 돌려준다."""
    compact = re.sub(r"\s+", "", s.replace("복사하기", ""))
    if _is_short(compact):
        return urlfix.SHORT_PREFIX + _short_id(compact)
    return s


def _bands(words, bounds, anchors):
    if bounds and len(bounds) >= 2:
        import bisect
        g = {}
        for w in words:
            g.setdefault(bisect.bisect(bounds, w[2]), []).append(w)
        return [g[k] for k in sorted(g)]
    ys = sorted(a[2] for a in anchors)                   # 줄무늬가 없으면 원본 URL 시작 줄을 기준으로 나눈다
    hh = sorted(w[3] for w in words)[len(words) // 2]
    cuts = [y - 1.2 * hh for y in ys[1:]]
    import bisect
    g = {}
    for w in words:
        g.setdefault(bisect.bisect(cuts, w[2]), []).append(w)
    return [g[k] for k in sorted(g)]


def _clean_id(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def confirm_send(n: int) -> bool:
    """접속 확인 전 확인창. 사용자가 상시 사용을 지정했으므로 묻지 않고 진행한다.
    (보내지 않으려면 화면의 'I/l 접속 확인' 체크를 끄면 된다. 다시 묻게 하려면 이 함수를 askyesno로 되돌린다)"""
    return True


def verify_all(recs: list, pump=None, progress=None) -> dict:
    """모든 레코드를 접속 확인한다. {id(rec): 상태}"""
    import shortverify
    import time
    try:
        from scrollcap import esc_tapped
    except Exception:                                   # 키 상태를 못 읽는 환경이면 중단 기능만 끈다
        esc_tapped = lambda: False
    targets = [r for r in recs if r["id"]]            # 원본이 없어도(단축 URL만 선택) 존재 여부로 확인한다
    out = {}
    # 복구 불가능한 ID가 많아도 서버 요청이 끝없이 늘지 않게 하는 총량(요청 수)과 전체 시간 제한
    budget = {"left": 2500, "used": 0, "deadline": time.time() + 150}
    esc_tapped()                                        # 이전에 눌린 ESC 기록을 비운다
    cur = {"n": 0}

    def tick():
        if pump:
            pump()
        if progress:
            progress(f"단축 URL 접속 확인 {cur['n']}/{len(targets)} · 요청 {budget['used']}회 · ESC = 중단")

    for n, r in enumerate(targets, 1):
        cur["n"] = n
        tick()
        out[id(r)] = shortverify.verify(r, pump=tick, budget=budget, cancel=esc_tapped)
        if r.get("note", "").endswith("(사용자 중단)"):    # ESC: 남은 ID는 확인하지 않는다
            break
    return out


WHICH = ("원본+단축", "단축만", "원본만")


def format_records(recs: list, verified: dict | None = None, mode: str = "memo", which: str = "원본+단축"):
    """레코드 → (엑셀 붙여넣기용 TSV, 안내 메시지, 확인필요 건수).
    mode: 'memo' 원본URL|단축URL|확인필요 (기본)
          'url'  URL만 — which: '원본+단축' | '단축만' | '원본만'
          'full' 전체 — 순번|원본URL|단축URL|확인필요"""
    verified = verified or {}
    lines, flagged = [], []
    for n, r in enumerate(recs, 1):
        memo = []
        st = verified.get(id(r))
        if st in ("확정됨", "확인됨"):
            memo.append("접속 " + st)
        elif st:
            memo.append("접속 확인 " + st)
        if r["ambiguous"]:
            memo.append("ID " + ",".join(str(i) for i in r["ambiguous"]) + "번째 글자 확인")
        if r.get("zero_o") and st not in ("확정됨", "확인됨"):
            memo.append("0/O/o " + ",".join(str(i) for i in r["zero_o"]) + "번째 오인식 가능")
        if r["note"]:
            memo.append(r["note"])
        if memo and not (st in ("확정됨", "확인됨") and len(memo) == 1):
            flagged.append(f"{r['no'] or n}번: " + " / ".join(memo))
        m = "; ".join(memo)
        if mode == "url":
            cells = {"원본+단축": [r["origin"], r["short"]], "단축만": [r["short"]], "원본만": [r["origin"]]}[which]
        elif mode == "full":
            cells = [str(r["no"] or n), r["origin"], r["short"], m]
        else:
            cells = [r["origin"], r["short"], m]
        lines.append("\t".join(cells))
    cols = {"memo": "원본URL | 단축URL | 확인필요 (3열)", "full": "순번 | 원본URL | 단축URL | 확인필요 (4열)",
            "url": {"원본+단축": "원본URL | 단축URL (2열)", "단축만": "단축URL (1열)", "원본만": "원본URL (1열)"}[which]}[mode]
    msg = f"{len(recs)}건을 복사했습니다.\n엑셀에서 Ctrl+V → {cols}\n"
    if verified:
        ok = sum(v in ("확정됨", "확인됨") for v in verified.values())
        fixed = sum(v == "확정됨" for v in verified.values())
        msg += f"\n접속 확인: {ok}/{len(verified)}건 일치 (그중 I/l 등을 접속으로 확정 {fixed}건)\n"
    if flagged:
        msg += ("\n[원본 대조 필요] 대문자 I와 소문자 l은 화면 글꼴상 모양이 같아 구분할 수 없습니다.\n"
                "접속 확인을 켜면 자동으로 확정됩니다.\n" + "\n".join(flagged[:15]))
        if len(flagged) > 15:
            msg += f"\n… 외 {len(flagged) - 15}건"
        if mode == "url":
            msg += "\n※ 'URL만' 복사에는 확인필요 열이 없습니다. 위 항목은 따로 확인하세요."
    return "\r\n".join(lines) + "\r\n", msg, len(flagged)


def extract(words: list, img, bounds=None, short_prefix: str = urlfix.SHORT_PREFIX):
    """반환 [{no, origin, short, ambiguous(list), note}]"""
    urls = [w for w in words if _is_url_start(w[0]) and not _is_short(w[0]) and not _is_short_like(w[0])]
    if not urls:                                         # 원본 URL이 없으면 단축 URL만 레코드로 만든다
        return _extract_shorts_only(words, img, short_prefix)
    minx = min(w[1] for w in urls)
    anchors = [w for w in urls if w[1] <= minx + 40]     # 원본 URL 열의 시작 단어
    recs = []
    for band in _bands(words, bounds, anchors):
        a = [w for w in band if w in anchors]
        if not a:
            continue
        x0 = min(w[1] for w in a)
        shorts = [w for w in band if w not in anchors and (_short_id(w[0]) is not None or _is_short_like(w[0])
                                                          or (_is_url_start(w[0]) and w[1] > minx + 40))]
        sx0 = min((w[1] for w in shorts), default=float("inf"))
        no = next((w[0] for w in sorted(band, key=lambda w: w[1]) if w[0].isdigit() and w[1] < x0 - 6), "")
        ytop = min(w[2] for w in a) - 0.6 * min(w[3] for w in a)      # 시작 줄 위(머리글 등)는 제외
        lines = core.cluster_rows([w for w in band if w[2] >= ytop and x0 - 6 <= w[1] < sx0 - 4
                                   and not re.search(r"[가-힣]", w[0])])
        origin = urlfix.fix_origin_url("".join(w[0] for ln in lines for w in ln))
        rec = {"no": no, "origin": origin, "short": "", "id": "", "ambiguous": [], "note": "",
               "_box": None}
        if shorts:
            idw = max((w for w in shorts if _short_id(w[0]) is not None), key=lambda w: w[1], default=None)
            if idw is not None:
                line = [w for w in band if abs(w[2] - idw[2]) <= idw[3] * 0.6 and w[1] >= sx0 - 3]
                line.sort(key=lambda w: w[1])
                text = "".join(w[0] for w in line)
                rec["id"] = _clean_id(_short_id(text) or "").replace(" ", "")
                rec["_box"] = (min(w[1] for w in line), max(w[1] + w[4] for w in line), idw[2], idw[3])
        if not rec["id"]:                                      # 못 찾았으면 그 줄 오른쪽을 다시 읽어 만회한다
            origin_right = max((w[1] + w[4] for ln in lines for w in ln), default=x0)
            got = _rescue_short(img, band, origin_right)
            if got:
                rec["id"], rec["_box"] = got
        recs.append(rec)

    return _finalize(recs, img, short_prefix)


def _finalize(recs: list, img, short_prefix: str) -> list:
    """ID 길이/첫 글자 추정 → 글리프 모양 보정 → 단축 URL(접두어 고정) 확정."""
    ids = [r["id"] for r in recs if len(r["id"]) >= 8]       # 형식 추정: 가장 흔한 길이/첫 글자
    # 표본이 3개 미만이면 통계 대신 알려진 ID 길이(10자)를 쓴다 (단축 URL 1~2개만 읽은 경우)
    mode_len = (Counter(len(i) for i in ids).most_common(1)[0][0] if len(ids) >= 3 else urlfix.SHORT_ID_LEN) if recs else 0
    first = (Counter(i[0] for i in ids if i[0].isalnum()).most_common(1)[0][0]
             if len(ids) >= 3 else urlfix.SHORT_ID_FIRST)
    for r in recs:
        i = r["id"]
        if not i:
            r["note"] = "단축 URL 못 찾음"
            continue
        if first and not i[0].isalnum():
            i = first + i[1:]
        i = re.sub(r"[^A-Za-z0-9]+$", "", i) if mode_len and len(i) > mode_len else i
        if mode_len and len(i) != mode_len and r["_box"] is not None:
            again = _reread(img, r["_box"], mode_len)          # ① 그 줄만 잘라 배율을 바꿔 다시 읽는다
            if again:
                i = again
        if mode_len and len(i) == mode_len - 1 and r["_box"] is not None:
            xl, xr, yc, h = r["_box"]                          # ② 글자 하나 누락: 글리프 개수로 위치·종류를 찾는다
            miss = idfix.find_missing(img, xl, xr, yc, h, i, mode_len)
            if miss:
                i = miss["ident"]
                r["missing"] = miss                            # ③ 후보 복구는 접속 확인(shortverify)이 한다
                r["ambiguous"] = miss["ambiguous"]
                at_end = miss["pos"] == [mode_len - 1]
                r["note"] = ("끝 글자 누락" if at_end else "글자 누락(위치 불명확)") + " — 접속 확인이 켜져 있으면 복구합니다"
                p0 = miss["pos"][-1]
                r["id"] = i
                r["short"] = short_prefix + i[:p0] + "?" + i[p0:]           # 빠진 자리를 ?로 표시 (조용히 틀린 URL이 되지 않게)
                continue
        if mode_len and len(i) != mode_len:
            r["note"] = f"ID 길이 {len(i)}자(보통 {mode_len}자) — 원본 대조"
            r["ambiguous"] = [n for n, c in enumerate(i, 1) if c in "Il1O0o"]
        elif r["_box"] is not None:
            xl, xr, yc, h = r["_box"]
            i, amb, memo, subs, cls = idfix.refine_id(img, xl, xr, yc, h, i)
            r["ambiguous"] = amb
            r["note"] = memo + (" — 접속 확인이 후보를 대입합니다" if subs else "")
            if subs:
                r["subs"] = subs
            if cls:
                r["cls"] = cls                                   # 자리별로 모양이 허용하는 글자 (후보 좁히기용)
        # OCR 잡글자('『', '@' …)가 섞인 자리는 '알 수 없는 글자'다. 그 자리에 글자 모양이 허용하는 후보(없으면 영숫자 전체)를
        # 넣어 보도록 subs에 올린다 (접속 확인이 다른 혼동 후보와 함께 조합해 찾는다).
        junk = [n for n, c in enumerate(i) if not (c.isascii() and c.isalnum())]
        if junk:
            cl = r.get("cls")
            subs_j = r.setdefault("subs", {})
            for n in junk:
                subs_j[n] = list(cl[n]) if cl and n < len(cl) and cl[n] else list(ALNUM)
            r["note"] = (r["note"].replace(" — 접속 확인이 후보를 대입합니다", "") +
                         f" · 잡글자 {len(junk)}곳({','.join(str(n + 1) for n in junk)}번째) — 접속 확인이 후보를 대입합니다").strip(" ·")
        if (junk or r.get("subs")) and r["_box"] is not None:       # 모양이 모순이거나 잡글자가 있으면 여러 배율로 다시 읽어 투표 후보를 만든다
            reads = [x for x in _reread_all(img, r["_box"], len(i)) if x != i]
            if reads:
                r["reads"] = reads
        r["id"] = i
        r["short"] = short_prefix + i
        # 0/O/o 는 모양으로 가려도 오인식이 잦다 → 접속 확인으로 확정되지 않으면 확인필요 열에 위치를 알린다
        r["zero_o"] = [n for n, c in enumerate(i, 1) if c in "0Oo"]
    for r in recs:
        r.pop("_box", None)
    return recs


def _reread(img, box, want_len: int):
    """ID 길이가 모자랄 때, 그 단축 URL 줄만 잘라 배율/선명화를 바꿔 다시 OCR한다.
    넓은 표 전체를 한 번에 읽을 때 마지막 글자를 놓치는 경우가 많지만, 좁게 잘라 읽으면 읽히는 일이 흔하다."""
    xl, xr, yc, h = box
    crop = img.crop((max(0, int(xl) - 24), max(0, int(yc - h * 1.2)),
                     min(img.width, int(xr) + 40), min(img.height, int(yc + h * 1.2))))
    if crop.width < 8 or crop.height < 8:
        return None
    pad = 20
    padded = Image.new("RGB", (crop.width + 2 * pad, crop.height + 2 * pad), crop.getpixel((0, 0)))
    padded.paste(crop, (pad, pad))
    for scale, sharp in ((4.0, True), (3.0, True), (5.0, True), (3.0, False), (2.0, False), (6.0, True)):
        try:
            ws = sorted(core.ocr_words(padded, scale, sharp), key=lambda w: w[1])
        except Exception:
            return None
        text = re.sub(r"\s+", "", "".join(w[0] for w in ws))
        if _is_short(text):
            ident = _clean_id(_short_id(text) or "")
            ident = re.sub(r"[^A-Za-z0-9]+$", "", ident)
            if len(ident) == want_len:
                return ident
    return None


ALNUM = string.ascii_letters + string.digits


def _reread_all(img, box, want_len: int) -> list[str]:
    """그 줄만 잘라 여러 배율/선명화로 읽은 결과 중, 길이가 want_len이고 영숫자뿐인 것들(중복 제거).
    읽을 때마다 틀리는 자리가 달라서, 서로 다른 읽기를 자리별로 투표하는 데 쓴다."""
    xl, xr, yc, h = box
    crop = img.crop((max(0, int(xl) - 24), max(0, int(yc - h * 1.2)),
                     min(img.width, int(xr) + 40), min(img.height, int(yc + h * 1.2))))
    if crop.width < 8 or crop.height < 8:
        return []
    pad = 20
    padded = Image.new("RGB", (crop.width + 2 * pad, crop.height + 2 * pad), crop.getpixel((0, 0)))
    padded.paste(crop, (pad, pad))
    out: list[str] = []
    for scale, sharp in ((4.0, True), (3.0, True), (5.0, True), (3.0, False), (2.0, False), (6.0, True), (3.5, True)):
        try:
            ws = sorted(core.ocr_words(padded, scale, sharp), key=lambda w: w[1])
        except Exception:
            break
        text = re.sub(r"\s+", "", "".join(w[0] for w in ws))
        sid = _short_id(text) if _is_short(text) else None
        if sid:
            sid = re.sub(r"[^A-Za-z0-9]+$", "", _clean_id(sid))
            if len(sid) == want_len and sid.isalnum() and sid not in out:
                out.append(sid)
    return out


def _rescue_short(img, band: list, origin_right: float):
    """레코드(행)에서 단축 URL을 못 찾았을 때: 원본 URL 오른쪽 영역만 잘라 다시 OCR해서 만회한다.
    넓은 표 전체를 읽을 때 놓쳤거나 단어가 쪼개진 줄도 좁게 읽으면 읽히는 일이 흔하다.
    반환 (ID, (x왼쪽, x오른쪽, y중심, 높이))  또는 None."""
    ys = [w[2] for w in band]
    hh = max(w[3] for w in band)
    top, bot = max(0, int(min(ys) - 2 * hh)), min(img.height, int(max(ys) + 2 * hh))
    x1 = max(0, int(origin_right) + 16)
    if img.width - x1 < 40 or bot - top < 10:
        return None
    crop = img.crop((x1, top, img.width, bot))
    pad = 16
    padded = Image.new("RGB", (crop.width + 2 * pad, crop.height + 2 * pad), crop.getpixel((0, 0)))
    padded.paste(crop, (pad, pad))
    for scale, sharp in ((4.0, True), (3.0, True), (2.0, False)):
        try:
            ws = core.ocr_words(padded, scale, sharp)
        except Exception:
            return None
        for w in sorted(ws, key=lambda w: (w[2], w[1])):
            t = re.sub(r"\s+", "", w[0])
            sid = _short_id(t)
            if sid and len(sid) >= 6 and _host_like(t):
                xl = x1 - pad + w[1]
                return _clean_id(sid), (xl, xl + w[4], top - pad + w[2], w[3])
    return None


def _extract_shorts_only(words: list, img, short_prefix: str) -> list:
    """원본 URL 없이 단축 URL만 있는 영역(단축 URL 열만 선택/캡처). 단축 URL 하나가 레코드 하나.
    이 경우 원본이 없어서 화면과 대조할 수 없으므로, 접속 확인은 '존재하는 ID인지'로 한다."""
    recs = []
    for w in sorted((w for w in words if _is_short(w[0]) or _is_short_like(w[0])),
                    key=lambda w: (round(w[2] / max(1.0, w[3])), w[1])):
        ident = _clean_id(_short_id(re.sub(r"\s+", "", w[0])) or "")
        recs.append({"no": "", "origin": "", "short": "", "id": ident, "ambiguous": [], "note": "",
                     "_box": (w[1], w[1] + w[4], w[2], w[3])})
    return _finalize(recs, img, short_prefix)
