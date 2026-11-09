"""작업표시줄 표시 설정: python 로고/이름 대신 퇴근요정 아이콘과 이름이 보이게 한다.
창에 AppUserModel 속성(ID, 다시 실행 명령, 아이콘, 표시 이름)을 직접 지정한다.
작업표시줄에 '고정'한 항목은 이 속성이 있는 상태에서 새로 고정해야 반영된다."""
import ctypes
import os
import sys
from ctypes import wintypes

import config

APP_ID = config.APP_ID
APP_NAME = "퇴근요정"


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


def apply(hwnd, here, icon_path):
    """hwnd 창에 퇴근요정 정보를 지정한다. 실패해도 앱 동작에는 영향 없다."""
    try:
        pyw = sys.executable
        if pyw.lower().endswith("python.exe"):
            cand = pyw[:-len("python.exe")] + "pythonw.exe"
            if os.path.exists(cand):
                pyw = cand
        cmd = f'"{pyw}" "{os.path.join(here, "app.py")}"'
        values = {
            5: APP_ID,                       # System.AppUserModel.ID
            2: cmd,                          # RelaunchCommand
            3: f"{icon_path},0",             # RelaunchIconResource
            4: APP_NAME,                     # RelaunchDisplayNameResource
        }
        fmtid = _guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        iid = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        store = ctypes.c_void_p()
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p]
        hr = shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store))
        if hr != 0 or not store.value:
            return False
        vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        SetValue = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(vtbl[6])
        Commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtbl[7])
        Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        keep = []
        for pid, text in values.items():
            key = _PROPERTYKEY(fmtid, pid)
            pv = _PROPVARIANT()
            pv.vt = 31                                            # VT_LPWSTR
            size = (len(text) + 1) * 2
            ctypes.windll.ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
            ctypes.windll.ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
            mem = ctypes.windll.ole32.CoTaskMemAlloc(size)
            ctypes.memmove(mem, ctypes.create_unicode_buffer(text), size)
            pv.ptr = mem
            SetValue(store, ctypes.byref(key), ctypes.byref(pv))
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
        Commit(store)
        Release(store)
        return True
    except Exception as e:
        if os.environ.get("GTFO_DEBUG"):
            print("taskbar_id 실패:", repr(e))
        return False

