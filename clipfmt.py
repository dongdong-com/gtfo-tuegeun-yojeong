"""엑셀 붙여넣기용 클립보드 (텍스트 + HTML 서식을 함께 넣는다).

탭 구분 텍스트만 붙이면 엑셀이 문자열을 멋대로 날짜로 바꾸고 초를 숨긴다
(예: '2026-11-05 14:56:25' → 날짜 값이 되고 '2026-11-05 14:56'으로 보임).
HTML 표에 셀별 `mso-number-format`을 지정하면 엑셀이 그 서식 그대로 붙여 넣는다.
 - 날짜/시간  → 진짜 날짜 값 + 'yyyy-mm-dd hh:mm:ss' 표시 (초까지 보임, 정렬/계산 가능)
 - 앞이 0인 숫자, 12자리 이상 숫자 → 텍스트 (0 사라짐/지수 표기 방지)
 - 그 외 → 엑셀 기본 (9,900 은 숫자)
HTML을 못 읽는 프로그램(메모장 등)에는 일반 탭 구분 텍스트가 붙는다."""
import ctypes
import html
import re
import sys
import time

if sys.platform == "win32":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_DT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_D = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TEXTNUM = re.compile(r"^(0\d+|\d{12,})$")

FMT_DT = r'yyyy\-mm\-dd\ hh\:mm\:ss'
FMT_D = r'yyyy\-mm\-dd'
FMT_TEXT = r'\@'


def cell_style(v: str) -> str:
    s = v.strip()
    if _DT.match(s):
        return FMT_DT
    if _D.match(s):
        return FMT_D
    if _TEXTNUM.match(s):
        return FMT_TEXT
    return ""


FLAG_BG = "#FFF2CC"          # 불확실한 셀의 배경색 (연노랑)


def table_html(table: list[list[str]], flags: set | None = None) -> str:
    """flags: 불확실한 셀 (행, 열) 집합 — 엑셀에서 노란 배경으로 표시된다."""
    flags = flags or set()
    rows = []
    for ri, r in enumerate(table):
        tds = []
        for ci, v in enumerate(r or [""]):
            st = cell_style(v)
            parts = []
            if st:
                parts.append(f'mso-number-format:"{st}"')
            if (ri, ci) in flags:
                parts.append(f"background:{FLAG_BG}")
            style = f" style='{';'.join(parts)}'" if parts else ""
            tds.append(f"<td{style}>{html.escape(v)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _cf_html(fragment: str) -> bytes:
    """CF_HTML('HTML Format') 형식: 헤더에 UTF-8 바이트 오프셋이 들어간다."""
    pre = "<html><body>\r\n<!--StartFragment-->"
    post = "<!--EndFragment-->\r\n</body></html>"
    head_tpl = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
                "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
    hlen = len(head_tpl.format(0, 0, 0, 0))
    b_pre, b_frag, b_post = pre.encode("utf-8"), fragment.encode("utf-8"), post.encode("utf-8")
    start_html = hlen
    start_frag = start_html + len(b_pre)
    end_frag = start_frag + len(b_frag)
    end_html = end_frag + len(b_post)
    head = head_tpl.format(start_html, end_html, start_frag, end_frag)
    return head.encode("utf-8") + b_pre + b_frag + b_post


def _alloc(data: bytes):
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    return h


def set_clipboard(text: str, html_fragment: str | None = None):
    """text(탭 구분)를 기본으로, html_fragment가 있으면 HTML 서식도 함께 클립보드에 넣는다."""
    if sys.platform != "win32":                      # macOS: NSPasteboard (텍스트 + public.html)
        import sysinput_mac
        sysinput_mac.set_text_html(text, html_fragment)
        return
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    h_text = _alloc(text.encode("utf-16-le") + b"\x00\x00")
    h_html = _alloc(_cf_html(html_fragment) + b"\x00") if html_fragment else None
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("클립보드를 열 수 없습니다.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h_text):
            raise RuntimeError("클립보드에 텍스트를 넣지 못했습니다.")
        if h_html:
            user32.SetClipboardData(user32.RegisterClipboardFormatW("HTML Format"), h_html)
    finally:
        user32.CloseClipboard()
