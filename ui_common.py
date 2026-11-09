"""여러 화면(페이지)이 공유하는 UI 도구: 화면 영역 선택 + 로컬 OCR."""
import ctypes
import time
import tkinter as tk
from tkinter import messagebox

from PIL import ImageGrab

import core

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 캡처 좌표와 화면 좌표 일치
except Exception:
    pass


def select_region(root):
    """모든 모니터(가상 화면 전체)를 반투명 오버레이로 덮고 드래그로 영역 선택. (x1,y1,x2,y2) 또는 None.
    좌표는 가상 화면 기준이라 주 모니터 왼쪽/위쪽 모니터는 음수가 될 수 있다."""
    result = {}
    gm = ctypes.windll.user32.GetSystemMetrics
    vx, vy, vw, vh = gm(76), gm(77), gm(78), gm(79)        # SM_X/Y/CXVIRTUALSCREEN
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.geometry(f"{vw}x{vh}{vx:+d}{vy:+d}")
    top.attributes("-alpha", 0.3, "-topmost", True)
    top.configure(bg="black", cursor="crosshair")
    cv = tk.Canvas(top, bg="black", highlightthickness=0)
    cv.pack(fill="both", expand=True)
    st = {}

    def down(e):
        st["x"], st["y"] = e.x_root, e.y_root
        st["id"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)
        st["cx"], st["cy"] = e.x, e.y

    def move(e):
        cv.coords(st["id"], st["cx"], st["cy"], e.x, e.y)

    def up(e):
        x1, x2 = sorted((st["x"], e.x_root)); y1, y2 = sorted((st["y"], e.y_root))
        if x2 - x1 > 5 and y2 - y1 > 5:
            result["box"] = (x1, y1, x2, y2)
        top.destroy()

    cv.bind("<ButtonPress-1>", down); cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up); top.bind("<Escape>", lambda e: top.destroy())
    top.focus_force()
    root.wait_window(top)
    return result.get("box")


def capture_image(widget):
    """앱 창을 숨기고 영역을 드래그로 선택해 이미지를 반환. 취소 시 None."""
    root = widget.winfo_toplevel()
    root.withdraw(); root.update(); time.sleep(0.25)
    try:
        box = select_region(root)
        return ImageGrab.grab(bbox=box, all_screens=True) if box else None
    finally:
        root.deiconify()


def capture_rows(widget, kind):
    """캡처 → 로컬 OCR(여러 배율 중 합계 검증이 맞는 결과 채택).
    kind: 'settle'(통합정산내역) | 'tax'(세금계산서). 반환 (rows, ocr_text) 또는 취소/실패 시 None."""
    img = capture_image(widget)
    if img is None:
        return None
    try:
        return (core.read_settle_rows if kind == "settle" else core.read_tax_rows)(img)
    except Exception as ex:
        messagebox.showerror("OCR 실패", str(ex))
        return None
