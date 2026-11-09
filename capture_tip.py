"""스크롤 캡처 중에 마우스 커서 옆에 띄우는 안내 말풍선: "퇴근요정이 화면캡쳐중입니다. 잠시만 기다려주세요".

말풍선이 캡처 결과에 찍히거나 입력을 방해하면 안 되므로
 - 화면 캡처에서 제외 (SetWindowDisplayAffinity WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+)
   → 영역 안에 떠 있어도 캡처 이미지에는 보이지 않는다. 지원되지 않으면 캡처하는 순간에만 잠시 숨긴다.
 - 클릭/휠 통과 (WS_EX_TRANSPARENT) — 말풍선 아래 창으로 휠 입력이 그대로 간다
 - 활성화되지 않음 (WS_EX_NOACTIVATE) — VDI 창의 포커스를 빼앗지 않는다
 - 커서에서 조금 떨어진 곳에 표시 (커서를 가리지 않도록)
"""
import ctypes
import os
import re
import tkinter as tk

import theme

user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.SetWindowDisplayAffinity.restype = ctypes.c_int

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x00000080, 0x08000000
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
LINES = ("퇴근요정이 화면캡쳐중입니다.", "잠시만 기다려주세요")


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor():
    p = _POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


class CaptureTip:
    def __init__(self, root: tk.Misc, offset=(26, 30)):
        self.root, self.offset, self._pos = root, offset, None
        self.win = tk.Toplevel(root)
        w = self.win
        w.overrideredirect(True)
        w.attributes("-topmost", True, "-alpha", 0.97)
        w.configure(bg=theme.CORAL)
        inner = tk.Frame(w, bg=theme.BLUSH)
        inner.pack(padx=2, pady=2)
        self._img = None
        try:
            from PIL import Image, ImageTk
            self._img = ImageTk.PhotoImage(Image.open(os.path.join(ASSETS, "icon_small.png")).resize((46, 46)))
            tk.Label(inner, image=self._img, bg=theme.BLUSH).pack(side="left", padx=(8, 4), pady=6)
        except Exception:
            pass
        box = tk.Frame(inner, bg=theme.BLUSH)
        box.pack(side="left", padx=(2, 12), pady=6)
        tk.Label(box, text=LINES[0], bg=theme.BLUSH, fg=theme.CORAL_DARK,
                 font=(theme.FONT[0], 11, "bold")).pack(anchor="w")
        tk.Label(box, text=LINES[1], bg=theme.BLUSH, fg=theme.PLUM, font=(theme.FONT[0], 10)).pack(anchor="w")
        self.status = tk.Label(box, text="ESC = 중단", bg=theme.BLUSH, fg=theme.NAVY, font=(theme.FONT[0], 8))
        self.status.pack(anchor="w", pady=(2, 0))

        self.win.update_idletasks()
        self.hwnd = user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE,
                                 ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        # 캡처에서 제외. 실패(구버전 Windows)하면 캡처 순간에만 숨기는 방식으로 대신한다.
        self.excluded = bool(user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE))
        self._orig_grab = None
        self.tick()

    # ---------------------------------------------------------------- 위치/문구
    def tick(self):
        """커서 옆으로 위치를 맞춘다 (pump에서 자주 불러도 위치가 같으면 아무것도 하지 않는다)."""
        x, y = _cursor()
        gm = user32.GetSystemMetrics
        vx, vy, vw, vh = gm(76), gm(77), gm(78), gm(79)
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        px, py = x + self.offset[0], y + self.offset[1]
        if px + w > vx + vw:                       # 화면 오른쪽/아래를 넘으면 반대쪽으로
            px = x - self.offset[0] - w
        if py + h > vy + vh:
            py = y - self.offset[1] - h
        if self._pos != (px, py):
            self._pos = (px, py)
            self.win.geometry(f"+{px}+{py}")

    def on_log(self, msg: str):
        """scrollcap 로그에서 진행 상황을 뽑아 말풍선에 표시한다."""
        m = re.match(r"(\d+)회 스크롤", msg)
        if m:
            self.status.config(text=f"스크롤 {m.group(1)}회 · ESC = 중단")

    # ---------------------------------------------------------------- 캡처 제외가 안 될 때의 대체 수단
    def install_grab_hook(self, scrollcap_module):
        """캡처 제외를 지원하지 않는 환경: 캡처하는 순간에만 말풍선을 숨긴다."""
        if self.excluded or self._orig_grab is not None:
            return
        self._scap = scrollcap_module
        self._orig_grab = scrollcap_module._grab

        def grab(box):
            self.win.attributes("-alpha", 0.0)
            try:
                return self._orig_grab(box)
            finally:
                self.win.attributes("-alpha", 0.97)
        scrollcap_module._grab = grab

    def close(self):
        if self._orig_grab is not None:
            self._scap._grab = self._orig_grab
            self._orig_grab = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
