"""Windows 화면 입력/창 제어 (user32). scrollcap.py가 Windows에서 불러온다."""
import ctypes
import io
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

VK_ESCAPE, VK_PRIOR, VK_NEXT = 0x1B, 0x21, 0x22
VK_SPACE, VK_UP, VK_DOWN, VK_MENU = 0x20, 0x26, 0x28, 0x12
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x0001, 0x0002, 0x0004, 0x0800


# ---------------------------------------------------------------- 입력 도구
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.WindowFromPoint.argtypes = [_POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]


def get_cursor():
    p = _POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


def esc_pressed() -> bool:
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def esc_tapped() -> bool:
    """ESC를 '눌렀다 뗀 경우'도 잡는다 (마지막 호출 이후 한 번이라도 눌렸으면 True). 짧게 톡 눌러도 인식된다."""
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8001)


def _move_abs(x: int, y: int):
    """가상 화면 절대 좌표로 마우스 이동 입력을 보낸다 (다중 모니터/혼합 배율에서도 누적 오차 없음)."""
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    nx = int((x - vx) * 65535 / max(1, vw - 1))
    ny = int((y - vy) * 65535 / max(1, vh - 1))
    user32.mouse_event(MOUSEEVENTF_MOVE | 0x8000 | 0x4000, nx, ny, 0, 0)     # ABSOLUTE | VIRTUALDESK


def _nudge(cx: int, cy: int):
    """포인터를 영역 중앙에 다시 놓고 2px 갔다 돌아온다.
    - 사용자가 마우스를 건드려 포인터가 벗어났어도 휠이 대상 창으로 가도록 매번 제자리로 돌린다.
    - SetCursorPos는 원격 뷰어가 '실제 이동'으로 받지 않는 경우가 있어 이동 입력을 직접 보내 위치를 알린다."""
    set_cursor(cx, cy)
    _move_abs(cx + 2, cy)
    time.sleep(0.015)
    _move_abs(cx, cy)
    time.sleep(0.015)
    set_cursor(cx, cy)


def _wheel(notches: int):
    """notches>0: 위로, <0: 아래로 (1칸=120)."""
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_ulong((120 * notches) & 0xFFFFFFFF).value, 0)


def _key(vk: int):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def _click():
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
WM_MOUSEWHEEL = 0x020A


def window_info(x, y) -> str:
    """좌표 위의 창 정보 (진단 로그용): '창 제목 [클래스]'. 하위 창이 아니라 최상위 창 기준."""
    try:
        hwnd = user32.WindowFromPoint(_POINT(int(x), int(y)))
        if not hwnd:
            return "(창 없음)"
        root = user32.GetAncestor(hwnd, 2) or hwnd
        buf, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(root, buf, 256)
        user32.GetClassNameW(hwnd, cls, 128)
        return f"'{buf.value}' [{cls.value}]"
    except Exception as ex:
        return f"(조회 실패: {ex})"


def _post_wheel(x: int, y: int, notches: int):
    """창 메시지(WM_MOUSEWHEEL)를 대상 창에 직접 보낸다. 시스템 입력(mouse_event)이 전달되지 않는 환경 대비.
    notches>0: 위로, <0: 아래로."""
    hwnd = user32.WindowFromPoint(_POINT(int(x), int(y)))
    if hwnd:
        delta = (120 * notches) & 0xFFFF
        user32.PostMessageW(hwnd, WM_MOUSEWHEEL, delta << 16, ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(_POINT)]


def window_client_bottom(x, y) -> int:
    """좌표 위의 최상위 창의 '클라이언트 영역' 아래쪽 화면 y좌표. (VDI 뷰어는 원격 화면 전체가 클라이언트 영역)"""
    hwnd = user32.WindowFromPoint(_POINT(int(x), int(y)))
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, 2) or hwnd
    rc = _RECT()
    user32.GetClientRect(root, ctypes.byref(rc))
    pt = _POINT(0, rc.bottom)
    user32.ClientToScreen(root, ctypes.byref(pt))
    return int(pt.y)


def focus_window_at(x, y) -> bool:
    """좌표 위에 있는 최상위 창을 앞으로 가져온다 (클릭하지 않으므로 화면 내용은 건드리지 않는다).
    VDI 뷰어는 활성 창일 때만 휠/키 입력을 받는 경우가 많다."""
    try:
        hwnd = user32.WindowFromPoint(_POINT(int(x), int(y)))
        if not hwnd:
            return False
        root = user32.GetAncestor(hwnd, 2) or hwnd            # GA_ROOT
        if user32.GetForegroundWindow() == root:
            return True
        if user32.IsIconic(root):
            user32.ShowWindow(root, 9)                        # SW_RESTORE
        user32.SetForegroundWindow(root)
        if user32.GetForegroundWindow() != root:              # 포그라운드 잠금에 막히면 Alt 입력 후 재시도
            _key(VK_MENU)
            user32.SetForegroundWindow(root)
        time.sleep(0.15)
        return user32.GetForegroundWindow() == root
    except Exception:
        return False


def virtual_screen():
    """가상 화면 전체 (x, y, 폭, 높이) — 모든 모니터를 합친 영역."""
    gm = user32.GetSystemMetrics
    return gm(76), gm(77), gm(78), gm(79)


def grab(box):
    """화면 영역 캡처 (모든 모니터 좌표계)."""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")


def copy_image_to_clipboard(img):
    """이미지를 클립보드(CF_DIB)에 넣는다. 엑셀에서 Ctrl+V 하면 그림으로 붙는다."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]               # BMP 파일 헤더(14바이트) 제외 = DIB
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    handle = kernel32.GlobalAlloc(0x0042, len(data))       # GMEM_MOVEABLE | GMEM_ZEROINIT
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    for _ in range(10):                                    # 다른 프로그램이 클립보드를 쓰는 중이면 재시도
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("클립보드를 열 수 없습니다.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(8, handle):         # CF_DIB
            raise RuntimeError("클립보드에 이미지를 넣지 못했습니다.")
    finally:
        user32.CloseClipboard()
