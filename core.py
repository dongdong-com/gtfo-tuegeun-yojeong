"""OCR(로컬, Windows 내장) + 파싱 + 엑셀 생성 + 클립보드 로직. UI와 분리."""
import asyncio
import io
import re
import sys
from copy import copy
from dataclasses import dataclass

import openpyxl
from PIL import Image, ImageFilter, ImageOps



# ---------------------------------------------------------------- OCR
_winrt_ok = None


def _use_winrt() -> bool:
    """winrt 파이썬 패키지를 쓸 수 있는가. 'DLL load failed while importing _winrt: 애플리케이션 제어 정책…'처럼 보안 정책이
    .pyd를 막은 PC에서는 False → PowerShell 경로(ocr_ps)로 같은 Windows OCR을 부른다. 환경변수 GTFO_OCR_BACKEND=ps 로 강제할 수 있다."""
    global _winrt_ok
    if _winrt_ok is None:
        import os
        if os.environ.get("GTFO_OCR_BACKEND", "").lower() == "ps":
            _winrt_ok = False
        else:
            try:
                from winrt.windows.media.ocr import OcrEngine  # noqa: F401
                _winrt_ok = True
            except Exception:
                _winrt_ok = False
    return _winrt_ok


def ocr_languages() -> list[tuple[str, str]]:
    """이 PC에 설치된 OCR 언어 [(언어 태그, 표시 이름)]. Windows 설정 > 시간 및 언어 > 언어에서 언어팩(OCR 포함)을 설치하면 늘어난다."""
    if sys.platform == "darwin":                  # macOS: Apple Vision
        import ocr_mac
        return ocr_mac.languages()
    if not _use_winrt():
        import ocr_ps
        return ocr_ps.languages()
    try:
        from winrt.windows.media.ocr import OcrEngine
        return [(l.language_tag, l.display_name) for l in OcrEngine.available_recognizer_languages]
    except Exception:
        return [("ko", "한국어")]


async def _recognize(img: Image.Image, scale: float = 2.0, sharp: bool = False, lang: str = "ko") -> list:
    """OCR 단어 목록 [(text, x, y중심, 높이, 너비)] — 좌표는 입력 이미지 기준(배율 복원).
    lang: OCR 언어 태그('ko', 'en-US' …) 또는 'auto'(사용자 프로필 언어)."""
    # 흑백+대비 보정이 인식률에 큰 영향. 엔진 최대 크기 제한이 있어 배율을 제한한다.
    g = ImageOps.autocontrast(img.convert("L"))
    scale = min(scale, 2400 / max(g.width, g.height))
    big = g.resize((max(1, int(g.width * scale)), max(1, int(g.height * scale))),
                   Image.LANCZOS)
    if sharp:   # 작은 글씨의 5/6, 3/8 같은 혼동을 줄이기 위한 선명화 변형
        big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))
    big = big.convert("RGB")
    buf = io.BytesIO()
    big.save(buf, "PNG")
    if sys.platform == "darwin":                  # macOS: Apple Vision (좌표는 확대한 이미지 기준 → 배율 복원)
        import ocr_mac
        return [(t, x / scale, y / scale, h / scale, w / scale)
                for t, x, y, h, w in ocr_mac.recognize(buf.getvalue(), big.width, big.height, lang)]
    if not _use_winrt():                          # winrt가 막힌 PC: PowerShell로 같은 Windows OCR 호출
        import ocr_ps
        return [(t, x / scale, y / scale, h / scale, w / scale) for t, x, y, h, w in ocr_ps.recognize(buf.getvalue(), lang)]
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    decoder = await BitmapDecoder.create_async(stream)
    bmp = await decoder.get_software_bitmap_async()
    if lang in ("", "auto", None):
        engine = OcrEngine.try_create_from_user_profile_languages()
    else:
        engine = OcrEngine.try_create_from_language(Language(lang))
    if engine is None:
        raise RuntimeError(f"OCR 언어 '{lang}'를 사용할 수 없습니다. Windows 설정 > 시간 및 언어 > 언어에서 "
                           "해당 언어(OCR 포함)를 설치하세요.")
    result = await engine.recognize_async(bmp)
    words = []
    for line in result.lines:
        for w in line.words:
            r = w.bounding_rect
            words.append((w.text, r.x / scale, (r.y + r.height / 2) / scale,
                          r.height / scale, r.width / scale))
    return words


def cluster_rows(words: list) -> list[list]:
    """표는 셀 단위로 인식 순서가 뒤섞이므로, 단어 좌표로 같은 높이끼리 묶어 '행' 단위로 재구성.
    각 행은 x 순으로 정렬된 단어 목록."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: w[2]):
        if rows and abs(w[2] - rows[-1][-1][2]) < max(w[3], rows[-1][-1][3]) * 0.6:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w[1]) for r in rows]


async def _ocr(img: Image.Image, scale: float = 2.0, sharp: bool = False) -> str:
    rows = cluster_rows(await _recognize(img, scale, sharp))
    return "\n".join(" ".join(t[0] for t in r) for r in rows)


def ocr_words(img: Image.Image, scale: float = 2.0, sharp: bool = False, lang: str = "ko") -> list:
    return asyncio.run(_recognize(img, scale, sharp, lang))


# (배율, 선명화) 조합을 차례로 시도한다
OCR_VARIANTS = ((2.0, False), (3.0, False), (2.0, True), (3.0, True), (1.5, False), (4.0, True), (1.0, False))


def ocr_image(img: Image.Image, scale: float = 2.0, sharp: bool = False) -> str:
    return asyncio.run(_ocr(img, scale, sharp))


# ---------------------------------------------------------------- 파싱
# 통합정산내역조회 표 컬럼 순서: 지급일 상점ID 지불수단 정산일 건수 거래금액 수수료 무이자수수료 부가세 지급액
# 날짜 구분자는 OCR이 '-' 대신 '•' 등으로 읽는 일이 있어 숫자/공백 아닌 아무 문자 1개를 허용한다.
PERIOD = re.compile(r"(\d{4})[^\d\s](\d{2})[^\d\s](\d{2})\s*[~\-–]?\s*(\d{4})[^\d\s](\d{2})[^\d\s](\d{2})")

import config                                  # 상점 ID는 config.py / local_config.py

KNOWN_IDS = list(config.STORE_IDS)
STORE_ORDER = list(config.STORE_ORDER)           # 수수료정산 양식의 상점 순서
# 상점ID 후보 토큰: 첫 상점 ID의 앞 3글자로 시작하거나, 앞부분이 깨져도 끝 3글자가 어느 상점 ID와 같은 토큰
_ID_PREFIX = re.escape(KNOWN_IDS[0][:3])
_ID_SUFFIX = "|".join(re.escape(i[-3:]) for i in KNOWN_IDS)
ID_TOKEN = re.compile(rf"\S*(?:{_ID_PREFIX}\w{{3,}}|(?:{_ID_SUFFIX})\b)", re.I)


def fix_id(tok: str) -> str:
    """OCR 오인식(store0o1 등)을 알려진 상점ID 중 가장 가까운 것으로 보정."""
    import difflib
    t = tok.lower()
    for known in KNOWN_IDS:                   # 끝 3글자가 같으면 같은 상점
        if t.endswith(known[-3:]):
            return known
    best = difflib.get_close_matches(t, KNOWN_IDS, n=1, cutoff=0.7)
    return best[0] if best else t


def _numbers(tail: str) -> list[int]:
    """OCR 텍스트 뒷부분의 금액들을 정수 목록으로. 구분자가 점/없음/공백인 경우를 모두 처리.
    예) '908.800 22.720 0 2281 883 799' -> [908800, 22720, 0, 2281, 883799]"""
    toks = [t for t in (x.strip(".,•·") for x in tail.split()) if re.fullmatch(r"\d[\d.,]*", t)]
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        # 천단위가 공백으로 떨어진 경우('883 799') 합친다. 0으로 시작하는 값은 합치지 않는다.
        if (re.fullmatch(r"[1-9]\d{0,2}", t) and i + 1 < len(toks)
                and re.fullmatch(r"\d{3}", toks[i + 1])):
            out.append(int(t + toks[i + 1])); i += 2
        else:
            out.append(int(re.sub(r"[.,]", "", t))); i += 1
    return out


def parse_rows(text: str) -> list[dict]:
    """통합정산내역 표의 데이터 행(상점ID 기준)을 모두 추출.
    반환: [{mid, period('MM/DD~MM/DD'), ym('YYYY년 MM월'), sales, fee, vat, deposit}]"""
    rows = []
    for line in text.splitlines():          # 한 줄 = 표의 한 행
        im, pm = ID_TOKEN.search(line), PERIOD.search(line)
        if not im or not pm:
            continue                        # 헤더/합계/기타 줄 제외
        y1, m1, d1, y2, m2, d2 = pm.groups()
        nums = _numbers(line[pm.end():])[:6]
        if len(nums) == 6:                  # 건수 거래금액 수수료 무이자 부가세 지급액
            nums = nums[1:]
        if len(nums) != 5:                  # (건수가 OCR에서 빠진 경우는 5개)
            continue
        sales, fee, free_fee, vat, deposit = nums
        # OCR이 2026을 2025로 읽는 일이 있어 정산기간 두 연도 중 큰 값 사용
        # (지급일은 다음 달/해일 수 있어 제외: 12/16~12/30 정산분이 1월에 지급되는 경우)
        rows.append({
            "mid": fix_id(im.group()),
            "period": f"{m1}/{d1}~{m2}/{d2}",
            "ym": f"{max(int(y1), int(y2))}년 {m2}월",
            "sales": sales, "fee": fee + free_fee, "vat": vat, "deposit": deposit,
        })
    return rows


def parse_tax_rows(text: str) -> list[dict]:
    """세금계산서 발행내역조회 표의 행 추출.
    컬럼: No 상점 이관발행ID 기간 거래금액 공급가액 세액 합계 품목 영수구분 발행일 ...
    반환: [{mid, ym, supply, tax, total}]"""
    out = []
    for line in text.splitlines():
        im, pm = ID_TOKEN.search(line), PERIOD.search(line)
        if not im or not pm:
            continue
        nums = _numbers(line[pm.end():])[:4]
        # 거래금액 칸이 비어 있으면 [공급가액, 세액, 합계], 값이 있으면 앞에 하나 더 붙는다
        cands = [c for c in (nums[0:3], nums[1:4]) if len(c) == 3]
        if not cands:
            continue
        supply, tax, total = next((c for c in cands if c[0] + c[1] == c[2]), cands[0])
        out.append({"mid": fix_id(im.group()),
                    "ym": f"{max(int(pm.group(1)), int(pm.group(4)))}년 {pm.group(5)}월",
                    "supply": supply, "tax": tax, "total": total})
    return out


def settle_ok(r: dict) -> bool:
    return r["sales"] == r["deposit"] + r["fee"] + r["vat"]


def tax_ok(r: dict) -> bool:
    return r["supply"] + r["tax"] == r["total"]


# OCR이 자주 혼동하는 숫자쌍 (작은 글씨에서 5↔6, 3↔8 등)
_CONFUSABLE = [("5", "6"), ("0", "8"), ("0", "6"), ("0", "9"), ("3", "8"), ("1", "7"),
               ("5", "8"), ("6", "8"), ("4", "9"), ("2", "7")]
_ALT: dict[str, set] = {}
for _a, _b in _CONFUSABLE:
    _ALT.setdefault(_a, set()).add(_b)
    _ALT.setdefault(_b, set()).add(_a)


def _one_digit_variants(n: int):
    s = str(n)
    for i, d in enumerate(s):
        for alt in _ALT.get(d, ()):
            t = s[:i] + alt + s[i + 1:]
            if i == 0 and t.startswith("0") and len(t) > 1:
                continue
            yield int(t)


def autofix(r: dict, keys: tuple, ok, labels: dict):
    """합계 검증이 깨진 행을 '숫자 한 자리 혼동' 수정으로 맞출 수 있으면 고친다.
    후보가 정확히 1개일 때만 적용(애매하면 그대로 두고 경고). 적용하면 r['fix']에 내역을 남긴다."""
    if ok(r):
        return r
    cands = []
    for k in keys:
        for v in _one_digit_variants(r[k]):
            r2 = {**r, k: v}
            if ok(r2):
                cands.append((k, r[k], v))
    if len(cands) == 1:
        k, old, new = cands[0]
        r[k] = new
        r["fix"] = f"{labels[k]} {old:,}→{new:,}"
    return r


def _best(img, parse, ok, keys, labels):
    """여러 배율/선명화로 OCR해서 '합계 검증이 통과하는 행'이 가장 많은 결과를 채택. (rows, text)
    그래도 안 맞는 행은 한 자리 혼동 자동 보정을 시도한다."""
    best, best_key = ([], ""), (-1, -1)
    for sc, sharp in OCR_VARIANTS:
        text = ocr_image(img, sc, sharp)
        rows = parse(text)
        key = (sum(1 for r in rows if ok(r)), len(rows))
        if key > best_key:
            best, best_key = (rows, text), key
        if rows and key[0] == len(rows):
            break
    rows, text = best
    return [autofix(r, keys, ok, labels) for r in rows], text


def read_settle_rows(img):
    return _best(img, parse_rows, settle_ok, ("sales", "fee", "vat", "deposit"),
                 {"sales": "거래금액", "fee": "수수료", "vat": "부가세", "deposit": "지급액"})


def read_tax_rows(img):
    return _best(img, parse_tax_rows, tax_ok, ("supply", "tax", "total"),
                 {"supply": "공급가액", "tax": "세액", "total": "합계"})

# ---------------------------------------------------------------- 분개
@dataclass
class Entry:
    mid: str        # 상점ID (예: store001)
    period: str     # 09/16~09/30
    deposit: int    # 입금액  -> 예치금-pg 차변
    sales: int      # 결제금액 -> 미수금-PG(카드) 대변
    fee: int        # 수수료
    vat: int        # 부가세

    def check(self) -> int:
        """결제금액 - (입금액+수수료+부가세). 0이어야 정상 (OCR 오류 검증)."""
        return self.sales - (self.deposit + self.fee + self.vat)


@dataclass
class Settings:
    section: str    # "미지급금" | "선급금"
    vendor: str     # 운세사주
    ym: str         # 2026년 09월  (수수료 적요용)


SECTION_TITLE = {"미지급금": "매월 8일 - 미지급금", "선급금": "매월 22일 - 선급금"}
SECTION_ACCOUNT = {"미지급금": "미지급금-PG", "선급금": "선급금-PG"}
HEAD = ["행번호", "계정과목", "비용구분", "차변금액", "대변금액", "적요", "귀속부서", "활동센터", "관계회사", "관리항목"]


def build_rows(entries: list[Entry], st: Settings) -> list[list]:
    """엑셀 한 줄 = [행번호, 계정, 비용구분, 차변, 대변, 적요, 부서, 센터, 관계회사, 관리항목].
    차변/대변은 숫자 또는 '=a+b' 수식 문자열."""
    rows, n = [], 0
    common = ["플랫폼사업팀", "플랫폼사업본부", None, f"거래처 - {st.vendor}"]
    for e in entries:
        # 양식 관례: 8일(미지급금)은 "09/16 ~ 09/30", 22일(선급금)은 "10/01~10/15"
        period = e.period.replace("~", " ~ ") if st.section == "미지급금" else e.period
        desc = f"{config.JOURNAL_PREFIX}이니시스 {e.mid} 결제대금 입금 ({period})"
        fee_desc = f"{config.JOURNAL_PREFIX}이니시스 {e.mid} 결제대행수수료(카드) ({st.ym})"
        n += 1; rows.append([n, "예치금-pg", None, e.deposit, None, desc, *common])
        n += 1; rows.append([n, "미수금-PG(카드)", None, None, e.sales, desc, *common])
        n += 1; rows.append([n, SECTION_ACCOUNT[st.section], None, f"={e.fee}+{e.vat}", None, fee_desc, *common])
    return rows


def _val(v):
    if isinstance(v, str) and v.startswith("="):
        return sum(int(x) for x in v[1:].split("+"))
    return v


def clipboard_text(rows: list[list], first: int = 0, last: int = 9) -> str:
    """영림원에 붙여넣을 탭 구분 텍스트 (헤더 제외, 수식은 계산값).
    first~last: 복사할 열 범위(0=행번호 ... 9=관리항목). 엑셀 복사처럼 마지막 줄에도 줄바꿈을 붙인다."""
    return "".join(
        "\t".join("" if (c := _val(v)) is None else str(c) for v in r[first:last + 1]) + "\r\n"
        for r in rows
    )



PREPAID_SHEET = "미지급금 및 선급금"
FEE_SHEET = "PG사(이니시스) 수수료정산"


def _style(s, d):
    d.font, d.fill, d.border = copy(s.font), copy(s.fill), copy(s.border)
    d.alignment, d.number_format = copy(s.alignment), s.number_format


def _sheet(wb, name):
    if name in wb.sheetnames:
        return wb[name]
    raise ValueError(f"양식 파일에 '{name}' 시트가 없습니다. (시트: {', '.join(wb.sheetnames)})")


def save_excel(template: str, out: str, rows: list[list], st: Settings):
    """'미지급금 및 선급금' 시트의 스타일(헤더/데이터 행)을 복사해 새 파일로 저장."""
    src = _sheet(openpyxl.load_workbook(template), PREPAID_SHEET)
    wb = openpyxl.Workbook()
    new = wb.active
    new.title = st.section

    def style_row(dst_r, src_r):
        for c in range(1, 11):
            _style(src.cell(src_r, c), new.cell(dst_r, c))

    for c in range(1, 11):
        L = openpyxl.utils.get_column_letter(c)
        new.column_dimensions[L].width = src.column_dimensions[L].width or 14
    style_row(1, 1)
    new["A1"] = SECTION_TITLE[st.section]
    for i, h in enumerate(HEAD, 1):
        new.cell(2, i, h)
    style_row(2, 2)
    for r, row in enumerate(rows, 3):
        style_row(r, 3)
        for c, v in enumerate(row, 1):
            new.cell(r, c, v)
    tot = 3 + len(rows)
    style_row(tot, 12)
    new.cell(tot, 4, f"=SUM(D3:D{tot-1})")
    new.cell(tot, 5, f"=SUM(E3:E{tot-1})")
    wb.save(out)
    return tot


# ---------------------------------------------------------------- PG 수수료 정산 (세금계산서 기준)
@dataclass
class FeeStore:
    """상점 1개의 월 수수료 정산 입력값."""
    mid: str
    supply: int = 0      # 세금계산서 공급가액  -> 지급수수료-PG수수료 차변
    tax: int = 0         # 세금계산서 세액      -> 부가세대급금 차변
    pre_fee: int = 0     # 정산일 1~15일 수수료  -> 선급금-PG 대변 (= 수수료+부가세)
    pre_vat: int = 0
    post_fee: int = 0    # 정산일 16~말일 수수료 -> 미지급금-PG 대변 (= 수수료+부가세)
    post_vat: int = 0

    def diff(self) -> int:
        """세금계산서 합계 - 통합정산내역 한 달 수수료·부가세 합. 0이어야 정상."""
        return (self.supply + self.tax) - (self.pre_fee + self.pre_vat + self.post_fee + self.post_vat)

    def empty(self) -> bool:
        return not any((self.supply, self.tax, self.pre_fee, self.pre_vat, self.post_fee, self.post_vat))


@dataclass
class ExtraFee:
    """계좌성명조회 등 기타 수수료 (미지급금-거래처로 처리)."""
    mid: str
    label: str = "계좌성명조회"
    ym: str = ""
    supply: int = 0
    tax: int = 0


FEE_DEPT, FEE_CENTER = "플랫폼사업팀", "신성장사업실"
FEE_NOTES = {
    "supply": "> 전월 세금계산서 발행내역의 공급가액",
    "tax": "> 전월 세금계산서 발행내역의 세액",
    "pre": "> 통합정산내역 조회 > 정산일 1일 ~ 15일의 수수료+부가세",
    "post": "> 통합정산내역 조회 > 정산일 16일 ~ 31일의 수수료+부가세",
}
FEE_HEAD = ["행번호", "계정과목", "비용구분", "차변금액", "대변금액", "적요", "귀속부서", "활동센터", "산출근거"]


def build_fee_rows(stores: list[FeeStore], ym: str, extras: list[ExtraFee] | None = None) -> list[list]:
    """[행번호, 계정, 비용구분, 차변, 대변, 적요, 부서, 센터, 산출근거] (양식 'PG사(이니시스) 수수료정산' 탭과 동일).
    클립보드는 앞 8칸(행번호~활동센터)만 사용한다."""
    rows, n = [], 0

    def add(acct, kind, dr, cr, desc, note, dept=FEE_DEPT, center=FEE_CENTER):
        nonlocal n
        n += 1
        rows.append([n, acct, kind, dr, cr, desc, dept, center, note])

    for s in stores:
        if s.empty():
            continue
        desc = f"{config.JOURNAL_PREFIX}이니시스 {s.mid} 카드결제 수수료 ({ym})"
        add("지급수수료-PG수수료", "판관", s.supply, 0, desc, FEE_NOTES["supply"])
        add("부가세대급금", None, s.tax, 0, desc, FEE_NOTES["tax"])
        add("선급금-PG", None, 0, f"={s.pre_fee}+{s.pre_vat}", desc, FEE_NOTES["pre"])
        add("미지급금-PG", None, 0, f"={s.post_fee}+{s.post_vat}", desc, FEE_NOTES["post"])
    for x in extras or []:
        if not (x.supply or x.tax):
            continue
        desc = f"{config.JOURNAL_PREFIX}이니시스 {x.mid} {x.label} ({x.ym or ym})"
        add("지급수수료-PG수수료", None, x.supply, 0, desc, "", None, None)
        add("부가세대급금", None, x.tax, 0, desc, "", None, None)
        add("미지급금-거래처", None, 0, x.supply + x.tax, desc, "", None, None)
    return rows


def save_fee_excel(template: str, out: str, rows: list[list]):
    """'PG사(이니시스) 수수료정산' 탭의 데이터 행 스타일을 복사해 분개표만 새 파일로 저장."""
    twb = openpyxl.load_workbook(template)
    fee, hdr = _sheet(twb, FEE_SHEET), _sheet(twb, PREPAID_SHEET)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "수수료정산"
    for i, w in enumerate((8, 22, 10, 14, 14, 62, 14, 16, 52), 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for i, h in enumerate(FEE_HEAD, 1):
        c = ws.cell(1, i, h)
        _style(hdr.cell(2, min(i, 10)), c)
    for r, row in enumerate(rows, 2):
        for i, v in enumerate(row, 1):
            c = ws.cell(r, i, v)
            _style(fee.cell(77, i + 2), c)      # 양식은 C열부터 시작
    tot = 2 + len(rows)
    for i in (4, 5):
        L = openpyxl.utils.get_column_letter(i)
        c = ws.cell(tot, i, f"=SUM({L}2:{L}{tot-1})")
        _style(fee.cell(92, i + 2), c)
    wb.save(out)
    return tot