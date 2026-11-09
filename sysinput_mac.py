"""macOS 화면 입력/창 제어/클립보드 (Quartz · AppKit, pyobjc). scrollcap.py·clipfmt.py가 macOS에서 불러온다.

sysinput_win.py와 같은 이름의 함수를 제공한다. 좌표는 '포인트'(Retina에서도 논리 좌표), 원점은 주 모니터 왼쪽 위 —
Tk의 e.x_root/e.y_root와 같은 좌표계라서 그대로 맞는다.

필요한 권한 (시스템 설정 > 개인정보 보호 및 보안): 이 앱을 실행하는 터미널(또는 Python)에 대해
  - 화면 및 시스템 오디오 녹음 : 화면 캡처 (없으면 배경화면만 찍힌다)
  - 손쉬운 사용              : 스크롤/키 입력을 다른 창에 보내기 (스크롤 캡처)
  - 입력 모니터링             : ESC 키로 스크롤 캡처 중단 (없으면 ESC 중단이 동작하지 않을 수 있다)
"""
import io
import os
import subprocess
import tempfile
import time

from PIL import Image

import Quartz

# macOS 가상 키코드 (ANSI). scrollcap이 VK_* 이름으로 쓴다.
VK_ESCAPE, VK_PRIOR, VK_NEXT = 53, 116, 121         # Esc, Page Up, Page Down
VK_SPACE, VK_UP, VK_DOWN = 49, 126, 125
LINES_PER_NOTCH = 3                                   # Windows 휠 1칸 ≈ 3줄


# ---------------------------------------------------------------- 마우스/키 입력
def get_cursor():
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def _post_move(x, y):
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (float(x), float(y)), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def set_cursor(x, y):
    Quartz.CGWarpMouseCursorPosition((float(x), float(y)))
    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    _post_move(x, y)                                  # 앱이 '실제 이동'으로 받도록 이동 이벤트도 보낸다


def esc_pressed() -> bool:
    try:
        return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateCombinedSessionState, VK_ESCAPE))
    except Exception:
        return False


def esc_tapped() -> bool:
    return esc_pressed()


def _nudge(cx: int, cy: int):
    """포인터를 영역 중앙에 놓고 2px 갔다 돌아온다 (휠이 대상 창으로 가도록)."""
    set_cursor(cx, cy)
    _post_move(cx + 2, cy)
    time.sleep(0.015)
    _post_move(cx, cy)
    time.sleep(0.015)
    set_cursor(cx, cy)


def _wheel(notches: int):
    """notches>0: 위로, <0: 아래로."""
    ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(notches) * LINES_PER_NOTCH)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _key(vk: int):
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, int(vk), down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _click():
    x, y = get_cursor()
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, kind, (float(x), float(y)), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _post_wheel(x: int, y: int, notches: int):
    """Windows의 '창 메시지 휠'에 해당하는 것이 macOS에는 없어서 일반 휠 입력으로 대신한다."""
    set_cursor(x, y)
    _wheel(notches)


# ---------------------------------------------------------------- 창 정보
def _window_at(x, y):
    """(x,y) 위에 있는 가장 앞의 일반 창(layer 0)의 정보 dict. 없으면 None."""
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:     # 앞→뒤 순서
        if w.get("kCGWindowLayer", 0) != 0:
            continue
        b = w.get("kCGWindowBounds")
        if b and b["X"] <= x < b["X"] + b["Width"] and b["Y"] <= y < b["Y"] + b["Height"]:
            return w
    return None


def window_info(x, y) -> str:
    try:
        w = _window_at(int(x), int(y))
        if not w:
            return "(창 없음)"
        return f"'{w.get('kCGWindowOwnerName', '')} - {w.get('kCGWindowName', '') or ''}' [layer {w.get('kCGWindowLayer', 0)}]"
    except Exception as ex:
        return f"(조회 실패: {ex})"


def window_client_bottom(x, y) -> int:
    """좌표 위 창의 아래쪽 화면 y좌표. 못 찾으면 0 (아래쪽 보충을 건너뛴다)."""
    try:
        w = _window_at(int(x), int(y))
        return int(w["kCGWindowBounds"]["Y"] + w["kCGWindowBounds"]["Height"]) if w else 0
    except Exception:
        return 0


def focus_window_at(x, y) -> bool:
    """좌표 위 창을 가진 앱을 앞으로 가져온다 (클릭하지 않는다)."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication, NSWorkspace
        w = _window_at(int(x), int(y))
        if not w:
            return False
        pid = int(w["kCGWindowOwnerPID"])
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None and int(front.processIdentifier()) == pid:
            return True
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.2)
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        return front is not None and int(front.processIdentifier()) == pid
    except Exception:
        return False


# ---------------------------------------------------------------- 화면
def virtual_screen():
    """모든 모니터를 합친 영역 (x, y, 폭, 높이). 포인트 단위."""
    try:
        err, ids, n = Quartz.CGGetActiveDisplayList(16, None, None)
        rects = [Quartz.CGDisplayBounds(i) for i in ids[:n]]
        x0 = min(r.origin.x for r in rects); y0 = min(r.origin.y for r in rects)
        x1 = max(r.origin.x + r.size.width for r in rects); y1 = max(r.origin.y + r.size.height for r in rects)
        return int(x0), int(y0), int(x1 - x0), int(y1 - y0)
    except Exception:
        r = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return int(r.origin.x), int(r.origin.y), int(r.size.width), int(r.size.height)


def grab(box) -> Image.Image:
    """화면 영역 캡처. Retina 화면은 실제 픽셀 해상도(보통 2배)로 돌려준다 — OCR에 유리하다.
    box는 포인트 좌표 (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = (int(v) for v in box)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["screencapture", "-x", "-t", "png", "-R", f"{x1},{y1},{max(1, x2 - x1)},{max(1, y2 - y1)}", path],
                       check=True, timeout=15)
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- 클립보드
def _pasteboard():
    from AppKit import NSPasteboard
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    return pb


def _nsdata(b: bytes):
    from Foundation import NSData
    return NSData.dataWithBytes_length_(b, len(b))


def set_text_html(text: str, html_fragment: str | None = None):
    """탭 구분 텍스트를 기본으로, html_fragment가 있으면 HTML 서식도 함께 클립보드에 넣는다."""
    from AppKit import NSPasteboardTypeHTML, NSPasteboardTypeString
    pb = _pasteboard()
    pb.setString_forType_(text, NSPasteboardTypeString)
    if html_fragment:
        page = f"<html><head><meta charset='utf-8'></head><body>{html_fragment}</body></html>"
        pb.setData_forType_(_nsdata(page.encode("utf-8")), NSPasteboardTypeHTML)


def copy_image_to_clipboard(img: Image.Image):
    """이미지를 클립보드(PNG + TIFF)에 넣는다. 엑셀/워드에서 붙여넣으면 그림으로 붙는다."""
    from AppKit import NSPasteboardTypePNG, NSPasteboardTypeTIFF
    rgb = img.convert("RGB")
    png, tiff = io.BytesIO(), io.BytesIO()
    rgb.save(png, "PNG")
    rgb.save(tiff, "TIFF")
    pb = _pasteboard()
    pb.setData_forType_(_nsdata(png.getvalue()), NSPasteboardTypePNG)
    pb.setData_forType_(_nsdata(tiff.getvalue()), NSPasteboardTypeTIFF)
