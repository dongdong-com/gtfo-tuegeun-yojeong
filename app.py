"""GTFO (Gracefully Terminate Formal Obligations)
PG 정산 캡처 → 엑셀 분개 양식 → 영림원 붙여넣기 도구 (100% 로컬 처리).

메뉴 구조 (1depth > 2depth > 3depth, 2depth에서 바로 화면이 열리는 항목도 가능)
  정산 (1depth)
   └ 포스티니 (2depth)
      ├ 선급금/미지급금 처리 (3depth)
      └ PG(이니시스) 수수료 정산 (3depth)
  운영 (1depth)
   ├ Data&Url캡쳐 (2depth)
   │  ├ 단축URL 캡처 (3depth)
   │  └ DCI 테이블 캡처 (3depth)
   └ AI캡쳐하기 (2depth)
      ├ 텍스트 캡쳐하기 (3depth, + 로컬 AI 보정)
      └ 이미지 캡쳐하기 (3depth, 이미지 → 프롬프트)
새 기능은 MENU에 (이름, 페이지 클래스)를 추가하면 된다. 2depth 항목이 하위 목록을 가지면 3depth 메뉴,
페이지 클래스를 직접 주면 2depth에서 바로 화면이 열린다.
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk

import ctypes

import ui_common  # noqa: F401  (DPI 설정)
import theme
from page_fee import FeeSettlePage
from page_prepaid import PrepaidPage
from page_image import ImagePromptPage
from page_text import TextExtractPage
from page_dci import DciTablePage
from page_vdi import VdiTablePage

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "문서 양식.xlsx")
ASSETS = os.path.join(HERE, "assets")
VERSION = "3.0"             # 기능을 고칠 때마다 올린다 (표시: 창 제목줄, 상단 헤더)
BUILD_DATE = "2026-11-09"
APP_TITLE = f"퇴근요정 ver {VERSION} (GTFO: Gracefully Terminate Formal Obligations)"

try:   # 작업표시줄에 python 아이콘 대신 GTFO 아이콘이 보이도록 별도 앱으로 등록
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(__import__('config').APP_ID)
except Exception:
    pass

# (1depth, [(2depth, [(3depth, 페이지클래스), ...]) 또는 (2depth, 페이지클래스), ...])
MENU = [
    ("정산", [
        ("포스티니", [
            (PrepaidPage.TITLE, PrepaidPage),
            (FeeSettlePage.TITLE, FeeSettlePage),
        ]),
    ]),
    ("운영", [
        ("Data&Url캡쳐", [
            (VdiTablePage.TITLE, VdiTablePage),       # 단축URL 캡처
            (DciTablePage.TITLE, DciTablePage),       # DCI 테이블 캡처
        ]),
        ("AI캡쳐하기", [
            (TextExtractPage.TITLE, TextExtractPage),     # 텍스트 캡쳐하기 (+ AI 보정)
            (ImagePromptPage.TITLE, ImagePromptPage),     # 이미지 캡쳐하기 → 프롬프트 만들기
        ]),
    ]),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x860")
        theme.apply(self)
        self._set_icon()
        self.template = tk.StringVar(value=DEFAULT_TEMPLATE)   # 모든 페이지 공용 양식
        self.pages = {}       # iid -> 생성된 페이지
        self.leaf = {}        # iid -> 페이지 클래스
        self._ui()
        self.update_idletasks()
        try:   # 작업표시줄 고정 항목에 python 대신 퇴근요정 아이콘/이름이 보이게 한다
            import taskbar_id
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            taskbar_id.apply(hwnd, HERE, os.path.join(ASSETS, "icon.ico"))
        except Exception:
            pass

    def _set_icon(self):
        """창/작업표시줄/Alt+Tab 아이콘(저해상도 캐릭터). 하위 창(텍스트 선택 등)도 같은 아이콘을 쓴다."""
        ico = os.path.join(ASSETS, "icon.ico")
        try:
            self.iconbitmap(default=ico)
        except tk.TclError:
            try:
                from PIL import ImageTk, Image
                self._icon_img = ImageTk.PhotoImage(Image.open(os.path.join(ASSETS, "icon.png")))
                self.iconphoto(True, self._icon_img)
            except Exception:
                pass

    def _header(self):
        """프로그램 상단: 캐릭터(배경 제거된 고해상도 이미지) + 제목. 아래에 코랄/노랑 띠."""
        hd = ttk.Frame(self, style="Header.TFrame"); hd.pack(fill="x")
        try:
            from PIL import Image, ImageTk
            img = Image.open(os.path.join(ASSETS, "header.png"))
            self._header_img = ImageTk.PhotoImage(img)           # 참조를 들고 있어야 사라지지 않는다
            ttk.Label(hd, image=self._header_img, style="Header.TLabel").pack(side="left", padx=(14, 10), pady=(4, 4))
        except Exception:
            pass
        box = ttk.Frame(hd, style="Header.TFrame"); box.pack(side="left", pady=6)
        title = ttk.Frame(box, style="Header.TFrame"); title.pack(anchor="w")
        ttk.Label(title, text="퇴근요정", style="Header.TLabel", foreground=theme.CORAL_DARK,
                  font=(theme.FONT[0], 26, "bold")).pack(side="left")
        ttk.Label(title, text=f"ver {VERSION}", style="Header.TLabel", foreground=theme.NAVY,
                  font=(theme.FONT[0], 11, "bold")).pack(side="left", padx=(8, 0), pady=(12, 0))
        ttk.Label(box, text="GTFO · Gracefully Terminate Formal Obligations", style="Header.TLabel",
                  foreground=theme.PLUM, font=(theme.FONT[0], 10)).pack(anchor="w")
        ttk.Label(box, text="PG 정산 · 화면 캡처 · 분개 · 붙여넣기를 한 번에", style="Header.TLabel",
                  foreground=theme.NAVY, font=(theme.FONT[0], 9)).pack(anchor="w", pady=(2, 0))
        ttk.Label(hd, text=f"ver {VERSION} · {BUILD_DATE}", style="Header.TLabel", foreground=theme.NAVY,
                  font=(theme.FONT[0], 9)).pack(side="right", anchor="s", padx=14, pady=8)
        tk.Frame(self, height=4, bg=theme.CORAL).pack(fill="x")
        tk.Frame(self, height=2, bg=theme.YELLOW_DARK).pack(fill="x")

    def _ui(self):
        self._header()
        bar = ttk.Frame(self, padding=(6, 6, 6, 0)); bar.pack(fill="x")
        ttk.Label(bar, text="양식 파일").pack(side="left")
        ttk.Entry(bar, textvariable=self.template, width=70).pack(side="left", padx=4)
        ttk.Button(bar, text="…", width=3, command=self._pick_tpl).pack(side="left")

        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, padx=6, pady=6)
        self.nav = ttk.Treeview(body, show="tree", selectmode="browse")
        self.nav.column("#0", width=230)
        body.add(self.nav, weight=0)
        self.holder = ttk.Frame(body); body.add(self.holder, weight=1)
        self.hint = ttk.Label(self.holder, text="왼쪽 메뉴에서 하위 항목을 선택하세요.", foreground="gray")

        first = None
        for d1, l2 in MENU:
            i1 = self.nav.insert("", "end", text=d1, open=True)
            for d2, l3 in l2:
                i2 = self.nav.insert(i1, "end", text=d2, open=True)
                if isinstance(l3, (list, tuple)):             # 3depth 메뉴가 있는 2depth
                    for d3, cls in l3:
                        i3 = self.nav.insert(i2, "end", text=d3)
                        self.leaf[i3] = cls
                        first = first or i3
                else:                                         # 페이지 클래스를 직접 준 2depth: 여기서 바로 화면이 열린다
                    self.leaf[i2] = l3
                    first = first or i2
        self.nav.bind("<<TreeviewSelect>>", self._on_select)
        if first:
            self.nav.selection_set(first)

    def _pick_tpl(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if p:
            self.template.set(p)

    def _on_select(self, _e=None):
        sel = self.nav.selection()
        if not sel:
            return
        for w in self.holder.winfo_children():
            w.pack_forget()
        iid = sel[0]
        if iid in self.leaf:
            if iid not in self.pages:                 # 처음 열 때 한 번만 생성 (입력값 유지)
                self.pages[iid] = self.leaf[iid](self.holder, self)
            self.pages[iid].pack(fill="both", expand=True)
        else:
            self.hint.pack(pady=40)


if __name__ == "__main__":
    App().mainloop()
