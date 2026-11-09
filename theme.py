"""GTFO 캐릭터(흰 고양이 요정)에서 뽑은 색으로 만든 UI 테마.
 머리띠 코랄 / 진한 코랄 / 외곽선 플럼 / 날개 하늘색 / 목걸이 네이비 / 별 노랑 / 크림
색을 바꾸려면 아래 팔레트만 고치면 된다."""
import tkinter as tk
from tkinter import ttk

CORAL = "#F56B76"        # 머리띠
CORAL_DARK = "#993E44"   # 머리띠 그림자 (제목/강조 글자)
CORAL_LIGHT = "#FFC9CE"  # 선택 배경
BLUSH = "#FFECEE"        # 볼터치 (헤더 배경)
PLUM = "#2A151B"         # 외곽선 (기본 글자색)
SKY = "#E3EFFD"          # 날개 (패널/트랙)
SKY_DARK = "#B9CBEA"
NAVY = "#4A68B4"         # 목걸이 (버튼)
NAVY_HOVER = "#6280CC"
NAVY_PRESS = "#3A5394"
YELLOW = "#FEEC95"       # 별
YELLOW_DARK = "#F2C94C"
CREAM = "#FFF9F7"        # 창 바탕
LINE = "#F3C4C8"         # 테두리
DISABLED = "#C9CFDC"

FONT = ("맑은 고딕", 9)


def _check_box(size: int, checked: bool, border: str, fill: str, mark: str = "white"):
    """체크박스 그림: 켜짐 = 색 채운 칸 안에 흰 V 표시, 꺼짐 = 빈 칸. (clam 기본 모양은 켜짐이 'X'라 헷갈려서 직접 그린다)"""
    from PIL import Image, ImageDraw
    k = 6                                                     # 크게 그린 뒤 줄여서 가장자리를 부드럽게
    s = size * k
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((k, k, s - k - 1, s - k - 1), radius=3 * k, fill=fill, outline=border, width=max(1, int(1.4 * k)))
    if checked:
        pts = [(0.27 * s, 0.53 * s), (0.43 * s, 0.70 * s), (0.75 * s, 0.31 * s)]
        d.line(pts, fill=mark, width=int(0.15 * s), joint="curve")
        for x, y in (pts[0], pts[-1]):                         # 선 끝을 둥글게
            r = 0.075 * s
            d.ellipse((x - r, y - r, x + r, y + r), fill=mark)
    return im.resize((size, size), Image.LANCZOS)


def _check_images(root: tk.Tk, st: ttk.Style):
    """TCheckbutton의 칸을 V 표시 그림으로 바꾼다. 실패하면 기본 모양을 그대로 쓴다."""
    try:
        from PIL import ImageTk
        size = max(14, int(round(16 * root.winfo_fpixels("1i") / 96)))      # 화면 배율(DPI)에 맞춰 키움
        mk = lambda checked, border, fill, mark="white": ImageTk.PhotoImage(_check_box(size, checked, border, fill, mark))
        root._check_imgs = imgs = {                              # 참조를 들고 있어야 그림이 사라지지 않는다
            "off": mk(False, "#B8888E", "white"),
            "off_hot": mk(False, CORAL, BLUSH),
            "on": mk(True, CORAL_DARK, CORAL),
            "on_hot": mk(True, CORAL_DARK, "#F98089"),
            "off_dis": mk(False, DISABLED, "#F4F5F8"),
            "on_dis": mk(True, DISABLED, "#D5DAE5", "white"),
        }
        st.element_create("gtfo.check", "image", imgs["off"],
                          ("disabled", "selected", imgs["on_dis"]), ("disabled", imgs["off_dis"]),
                          ("selected", "active", imgs["on_hot"]), ("selected", imgs["on"]),
                          ("active", imgs["off_hot"]), width=size + 4, sticky="w")
        st.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("gtfo.check", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    except Exception:
        pass


def apply(root: tk.Tk):
    root.configure(bg=CREAM)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=CREAM, foreground=PLUM, fieldbackground="white", bordercolor=LINE,
                 lightcolor=CREAM, darkcolor=LINE, troughcolor=SKY, focuscolor=CORAL, font=FONT)
    st.configure("TFrame", background=CREAM)
    st.configure("TLabel", background=CREAM, foreground=PLUM)
    st.configure("TLabelframe", background=CREAM, bordercolor=LINE, relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=CREAM, foreground=CORAL_DARK, font=(FONT[0], FONT[1], "bold"))

    st.configure("TButton", background=NAVY, foreground="white", bordercolor=NAVY_PRESS, lightcolor=NAVY,
                 darkcolor=NAVY, padding=(10, 4), relief="flat", focusthickness=1, focuscolor=YELLOW_DARK)
    st.map("TButton",
           background=[("disabled", DISABLED), ("pressed", NAVY_PRESS), ("active", NAVY_HOVER)],
           foreground=[("disabled", "#F5F5F5")],
           bordercolor=[("disabled", DISABLED)],
           lightcolor=[("pressed", NAVY_PRESS), ("active", NAVY_HOVER)],
           darkcolor=[("pressed", NAVY_PRESS), ("active", NAVY_HOVER)])

    _check_images(root, st)
    for name in ("TCheckbutton", "TRadiobutton"):
        st.configure(name, background=CREAM, foreground=PLUM, indicatorbackground="white",
                     indicatorforeground="white")
        st.map(name, background=[("active", BLUSH)],
               indicatorbackground=[("selected", CORAL), ("pressed", CORAL_LIGHT)],
               foreground=[("disabled", "#9AA0AE")])

    for name in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(name, fieldbackground="white", bordercolor=LINE, lightcolor="white", darkcolor="white",
                     padding=3, selectbackground=CORAL_LIGHT, selectforeground=PLUM)
        st.map(name, bordercolor=[("focus", CORAL)], lightcolor=[("focus", CORAL)], darkcolor=[("focus", CORAL)])
    st.configure("TCombobox", arrowcolor=NAVY, background=SKY)
    st.map("TCombobox", fieldbackground=[("readonly", "white")], background=[("active", SKY_DARK)],
           selectbackground=[("readonly", "white")], selectforeground=[("readonly", PLUM)])
    st.configure("TSpinbox", arrowcolor=NAVY, background=SKY)

    st.configure("Treeview", background="white", fieldbackground="white", foreground=PLUM, rowheight=26,
                 bordercolor=LINE, lightcolor="white", darkcolor="white")
    st.map("Treeview", background=[("selected", CORAL_LIGHT)], foreground=[("selected", PLUM)])
    st.configure("Treeview.Heading", background=SKY, foreground=PLUM)

    st.configure("TScrollbar", background=SKY_DARK, troughcolor=SKY, bordercolor=SKY, arrowcolor=NAVY,
                 lightcolor=SKY_DARK, darkcolor=SKY_DARK, gripcount=0)
    st.map("TScrollbar", background=[("active", NAVY_HOVER), ("pressed", NAVY)])
    st.configure("TScale", background=CORAL, troughcolor=SKY_DARK, bordercolor=LINE, lightcolor=CORAL, darkcolor=CORAL)
    st.configure("TPanedwindow", background=CREAM)
    st.configure("Sash", sashthickness=6, background=LINE, gripcount=0)
    st.configure("Header.TFrame", background=BLUSH)
    st.configure("Header.TLabel", background=BLUSH, foreground=PLUM)

    # 일반 tk 위젯(Text, 콤보박스 목록 등)의 색
    root.option_add("*Text.selectBackground", CORAL_LIGHT)
    root.option_add("*Text.selectForeground", PLUM)
    root.option_add("*Text.background", "white")
    root.option_add("*Text.foreground", PLUM)
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", LINE)
    root.option_add("*Text.highlightColor", CORAL)
    root.option_add("*TCombobox*Listbox.background", "white")
    root.option_add("*TCombobox*Listbox.foreground", PLUM)
    root.option_add("*TCombobox*Listbox.selectBackground", CORAL_LIGHT)
    root.option_add("*TCombobox*Listbox.selectForeground", PLUM)
    return st
