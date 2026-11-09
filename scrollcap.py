"""화면 영역 자동 스크롤 캡처 + 이어붙이기.

VDI/원격 데스크톱처럼 UI 요소에 접근할 수 없는 화면을 위해 '화면 픽셀'만 사용한다.
영역을 캡처 → 마우스 휠(또는 키)로 스크롤 → 다시 캡처를 반복하고,
프레임 사이의 이동량(dy)을 이미지 비교로 찾아 겹치는 부분을 제거하며 세로로 이어붙인다.

스크롤이 먹지 않는 경우(VDI 뷰어가 활성 창이 아니거나 마우스 이동을 못 받을 때)를 위해
 - 대상 창을 앞으로 가져오고(클릭 없이), 마우스를 1px 움직여 위치를 알리고,
 - 첫 스크롤에 반응이 없으면 큰 휠 → PageDown → ↓ → Space 순서로 자동 전환한다.
"""
import io
import sys
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

# ---------------------------------------------------------------- 입력 도구 (OS별)
# Windows: sysinput_win (user32) / macOS: sysinput_mac (Quartz). 같은 이름의 함수를 제공한다.
if sys.platform == "win32":
    from sysinput_win import (VK_NEXT, VK_PRIOR, VK_SPACE, VK_UP, VK_DOWN, get_cursor, set_cursor, esc_pressed,
                              esc_tapped, _nudge, _wheel, _key, _click, window_info, _post_wheel,
                              window_client_bottom, focus_window_at, virtual_screen, grab)
else:
    from sysinput_mac import (VK_NEXT, VK_PRIOR, VK_SPACE, VK_UP, VK_DOWN, get_cursor, set_cursor, esc_pressed,
                              esc_tapped, _nudge, _wheel, _key, _click, window_info, _post_wheel,
                              window_client_bottom, focus_window_at, virtual_screen, grab)



# ---------------------------------------------------------------- 이미지 비교
SIG_BINS = 48


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _signature(gray: np.ndarray) -> np.ndarray:
    """행마다 가로를 SIG_BINS칸으로 줄인 평균 밝기 (H x SIG_BINS). 행 단위 매칭용."""
    h, w = gray.shape
    wb = max(SIG_BINS, w // SIG_BINS * SIG_BINS)
    g = gray[:, :wb] if w >= wb else np.pad(gray, ((0, 0), (0, wb - w)), mode="edge")
    return g.reshape(h, SIG_BINS, wb // SIG_BINS).mean(axis=2)


def _same(a: np.ndarray, b: np.ndarray) -> bool:
    return float(np.abs(a - b).mean()) < 0.8


def find_shift(prev: np.ndarray, cur: np.ndarray, hint: int | None = None, thr: float = 6.0,
               prev_full: np.ndarray | None = None, cur_full: np.ndarray | None = None):
    """prev 프레임이 cur 프레임에서 위로 dy픽셀 올라가 있다고 보고 dy를 찾는다.
    prev[dy:] == cur[:H-dy] 가 되는 dy. 글자가 있는 행만 비교해 빈 배경 때문에 생기는 오탐을 막는다.
    prev_full/cur_full(원본 해상도 회색 이미지, prev/cur와 같은 행 범위)가 있으면, 같은 점수로 비기는 후보
    (같은 모양의 줄이 반복되는 목록/문단)를 원본 픽셀 오차로 가른다.
    반환 (dy, 일치율, 비교한 행 수). 못 찾으면 (0, 0.0, 0)."""
    h = prev.shape[0]
    bg = np.median(prev)
    ink = np.abs(prev - bg).mean(axis=1) > 3.0
    cands = []
    for dy in range(1, h - max(24, h // 8) + 1):
        w = ink[dy:]
        cnt = int(w.sum())
        if cnt < 3:
            continue
        match = np.abs(prev[dy:] - cur[:h - dy]).mean(axis=1) < thr
        cands.append((dy, float((match & w).sum()) / cnt, cnt))
    if not cands:
        return 0, 0.0, 0
    top = max(c[1] for c in cands)
    good = [c for c in cands if c[1] >= top - 0.01]
    if len(good) > 1 and prev_full is not None and cur_full is not None:
        # 비기면(반복 구조) 원본 해상도로 겹친 부분을 픽셀 단위로 비교해 오차가 가장 작은 이동량을 고른다.
        # (거친 서명은 '숫자만 다른 줄' 같은 차이를 평균에 묻어 버린다)
        pool = sorted(good, key=lambda c: abs(c[0] - hint) if hint is not None else -c[0])[:120]

        def full_err(c):
            dy = c[0]
            return float(np.abs(prev_full[dy:] - cur_full[:h - dy]).mean())
        return min(pool, key=full_err)
    if hint is not None:                       # 직전 이동량과 가까운 후보 우선 (반복 패턴 오탐 방지)
        return min(good, key=lambda c: abs(c[0] - hint))
    return max(good, key=lambda c: c[2])


# ---------------------------------------------------------------- 캡처
@dataclass
class Params:
    mode: str = "wheel"       # "wheel" | "pagedown"
    notches: int = 2          # 스텝당 휠 칸 수 (적을수록 프레임 간 겹침이 커서 정합이 안정적)
    delay: float = 1.0        # 스크롤 후 최소 대기(초). 이후 화면이 안정될 때까지 자동으로 더 기다린다 — VDI는 길게
    max_steps: int = 100
    to_top: bool = True       # 시작 전에 맨 위로 이동
    click_focus: bool = False  # 시작 전 영역 중앙을 한 번 클릭(포커스)
    include_tail: bool = True  # 끝에서 영역 아래쪽(뷰포트 하단까지) 내용도 포함


def _grab(box) -> Image.Image:
    return grab(box)


def describe(st) -> str:
    if st[0] == "wheel":
        return f"마우스 휠 {st[1]}칸"
    if st[0] == "msg":
        return f"창 메시지 휠 {st[1]}칸"
    return {VK_NEXT: "PageDown 키", VK_DOWN: f"↓ 키 ×{st[2]}", VK_SPACE: "Space 키"}.get(st[1], "키")


_UP_KEY = {VK_NEXT: VK_PRIOR, VK_DOWN: VK_UP, VK_SPACE: VK_PRIOR}


def capture_scroll(box, p: Params, pump=None, log=None):
    """box=(x1,y1,x2,y2) 영역을 자동 스크롤하며 캡처해 한 장으로 이어붙인다.
    반환 (이미지, 정보dict). ESC를 누르면 지금까지 캡처한 것으로 중단."""
    log = log or (lambda s: None)

    def wait(sec):
        end = time.time() + sec
        while time.time() < end:
            if pump:
                pump()
            time.sleep(0.02)

    def settle(min_wait: float, max_wait: float = 2.5, b=None):
        """스크롤 뒤 화면이 안정될 때까지(연속 두 장이 거의 같아질 때까지) 기다리고 마지막 프레임을 돌려준다.
        VDI는 스크롤 직후 화질이 낮았다가 잠시 뒤 선명해지거나, 스크롤 애니메이션이 진행 중일 수 있다.
        고정 대기만 쓰면 그 중간 프레임이 찍혀 정합이 틀어진다. (b: 캡처할 박스, 기본은 지정한 영역)"""
        b = b or box
        wait(min_wait)
        img = _grab(b)
        g = _gray(img)
        t0 = time.time()
        while time.time() - t0 < max_wait:
            wait(0.25)
            img2 = _grab(b)
            g2 = _gray(img2)
            if float(np.abs(g - g2).mean()) < 0.5:
                return img2
            img, g = img2, g2
        return img

    def align(sig, gray):
        """이전 프레임과의 이동량(dy) 계산. 일치율이 낮으면 비교 기준(thr)을 단계적으로 완화한다 (화질 차이 대비).
        gray: 현재 프레임의 원본 해상도 회색 이미지 (같은 점수로 비길 때 후보를 가르는 데 쓴다)."""
        best = (0, 0.0, 0)
        for thr in (6.0, 12.0, 20.0):
            r = find_shift(prev_sig[top:h - bot], sig[top:h - bot], hint, thr,
                           prev_g[top:h - bot], gray[top:h - bot])
            if r[1] > best[1]:
                best = r
            if r[1] >= 0.85 and r[0] > 0:
                return r, thr
        return best, None

    def scroll(st, up=False):
        # 실행 중에 다른 창이 활성화를 가져가면 입력이 엉뚱한 곳으로 간다 → 매번 확인하고 필요할 때만 되돌린다
        if esc_pressed():
            return
        focus_window_at(cx, cy)
        if st[0] == "wheel":
            _nudge(cx, cy)
            time.sleep(0.03)
            _wheel(st[1] if up else -st[1])
        elif st[0] == "msg":
            set_cursor(cx, cy)
            _post_wheel(cx, cy, st[1] if up else -st[1])
        else:
            vk = _UP_KEY.get(st[1], VK_PRIOR) if up else st[1]
            for _ in range(st[2]):
                _key(vk)
                time.sleep(0.02)

    cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    set_cursor(cx, cy)                     # 휠은 커서 아래 창으로 전달된다
    focused = focus_window_at(cx, cy)      # VDI 뷰어를 활성 창으로
    log(f"영역 {box} 중앙 ({cx},{cy}) · 대상 창 {window_info(cx, cy)} · 활성화 {'성공' if focused else '실패'} · "
        f"커서 {get_cursor()}")
    if not focused:
        log("대상 창을 앞으로 가져오지 못했습니다 (그래도 계속 시도)")
    if p.click_focus:
        _click()
    wait(0.3)

    primary = ("key", VK_NEXT, 1) if p.mode == "pagedown" else ("wheel", max(1, p.notches))
    fallbacks = [("wheel", max(10, p.notches * 3)), ("msg", 5), ("key", VK_NEXT, 1), ("key", VK_DOWN, 12),
                 ("key", VK_SPACE, 1)]
    if primary[0] == "wheel":
        fallbacks = [f for f in fallbacks if f != primary]
    else:
        fallbacks = [("wheel", 10), ("msg", 5)] + fallbacks[3:]
    strat = primary

    if p.to_top:
        log("맨 위로 이동 중…")
        prev = _gray(_grab(box))
        for _ in range(80):
            if esc_pressed():
                break
            scroll(("wheel", 10) if strat[0] == "wheel" else strat, up=True)
            wait(p.delay)
            cur = _gray(_grab(box))
            if _same(prev, cur):
                break
            prev = cur

    first = _grab(box)
    pieces = [first]
    h = first.height
    prev_img, prev_g = first, _gray(first)
    prev_sig = _signature(prev_g)
    hint, reason, steps = None, "최대 횟수 도달", 0
    fails = 0
    escalated = False
    top = bot = None      # 스크롤해도 변하지 않는 위/아래 고정 영역(고정 헤더, 테두리, 상태바)의 높이
    while steps < p.max_steps:
        if esc_pressed():
            reason = "ESC로 중단"
            break
        scroll(strat)
        cur_img = settle(p.delay)
        cur_g = _gray(cur_img)
        if _same(prev_g, cur_g):
            if steps == 0 and not escalated:
                # 첫 스크롤에 화면이 전혀 안 변했다 = 끝이 아니라 스크롤 입력이 전달되지 않은 것.
                # 창을 다시 활성화하고, 다른 스크롤 방식을 차례로 시도한다.
                escalated = True
                set_cursor(cx, cy); focus_window_at(cx, cy); wait(0.3)
                found = False
                log(f"첫 스크롤({describe(strat)}) 후 화면 변화 없음 (변화량 {float(np.abs(prev_g - cur_g).mean()):.3f}, "
                    f"기준 0.8) · 활성 창 {window_info(*get_cursor())} · 커서 {get_cursor()}")
                for st in [primary] + fallbacks:
                    scroll(st); wait(max(p.delay, 0.9))
                    cur_img = _grab(box)
                    cur_g = _gray(cur_img)
                    diff = float(np.abs(prev_g - cur_g).mean())
                    log(f"  시도 {describe(st)} → 변화량 {diff:.3f}" + (" (성공)" if diff >= 0.8 else ""))
                    if not _same(prev_g, cur_g):
                        strat, found = st, True
                        break
                if not found:
                    reason = ("스크롤이 반응하지 않았습니다 — 영역 위에 스크롤할 내용이 없거나, VDI 창이 입력을 받지 못하고 있습니다. "
                              "'영역 중앙 클릭(포커스)'을 켜거나 VDI 창을 직접 한 번 클릭한 뒤 다시 시도하세요")
                    break
            else:
                # 끝이라고 단정하기 전에: 화면이 늦게 갱신된 것이거나 입력이 한 번 유실된 것일 수 있다 (VDI 지연).
                changed = False
                for _ in range(2):
                    wait(max(p.delay, 0.8))
                    cur_img = _grab(box); cur_g = _gray(cur_img)
                    if not _same(prev_g, cur_g):
                        changed = True
                        break
                    scroll(strat)                                     # 한 번 더 스크롤
                    cur_img = settle(p.delay); cur_g = _gray(cur_img)
                    if not _same(prev_g, cur_g):
                        changed = True
                        break
                if not changed:
                    reason = "끝까지 스크롤"
                    break
        if top is None:
            # 첫 스크롤 전후에 똑같은 줄이 위/아래에 연속으로 있으면 고정 영역이다.
            # 고정 영역은 이어붙일 때 제외한다 (안 그러면 조각마다 테두리/헤더가 끼어든다).
            eq = np.abs(prev_g - cur_g).mean(axis=1) < 1.0
            t0, b0 = int(np.argmin(eq)), int(np.argmin(eq[::-1]))          # 위/아래에서부터 연속으로 같은 줄 수
            # 빈 흰 줄은 스크롤해도 '같은 줄'이라 고정 영역의 증거가 못 된다 (내용이 듬성듬성한 페이지에서 오인).
            # 글자/선이 있는 줄까지만 고정 영역으로 인정한다.
            ink = np.abs(prev_g - np.median(prev_g)).mean(axis=1) > 3.0
            ti = np.where(ink[:t0])[0]
            top = int(ti.max()) + 1 if len(ti) else 0
            bi = np.where(ink[h - b0:])[0] if b0 else []
            bot = (b0 - int(bi.min())) if len(bi) else 0
            if top + bot > h * 0.5:
                top = bot = 0
            if bot:
                pieces[0] = first.crop((0, 0, first.width, h - bot))
            if top or bot:
                log(f"고정 영역 감지: 위 {top}px / 아래 {bot}px 제외")
        cur_sig = _signature(cur_g)
        (dy, ratio, cnt), thr_used = align(cur_sig, cur_g)
        if ratio < 0.85 or dy <= 0:
            # 1) 화면이 아직 안정되지 않았거나(VDI 화질 보정/애니메이션) 일시적으로 흐렸을 수 있다 → 더 기다린 뒤 다시 계산
            log(f"정합 일치율 {ratio:.0%} (dy={dy}) → 더 기다린 뒤 재계산")
            cur_img = settle(max(p.delay, 1.0) + 0.5, max_wait=4.0)
            cur_g = _gray(cur_img)
            cur_sig = _signature(cur_g)
            (dy, ratio, cnt), thr_used = align(cur_sig, cur_g)
        if ratio < 0.85 or dy <= 0:
            # 2) 이동량이 너무 커서 겹침이 없는 경우: 스크롤 양을 줄여 다시 시도한다.
            #    (되돌린 위치가 이전 화면과 '완전히 같은지'는 따지지 않는다 — VDI는 화질이 달라 같은 위치도 달라 보인다.
            #     이전 프레임은 그대로 두고 다음 스크롤 뒤에 다시 정합하면 되므로 어긋난 위치여도 상관없다)
            fails += 1
            if strat[0] == "wheel" and strat[1] > 1 and fails <= 4:
                scroll(strat, up=True)
                strat = ("wheel", max(1, strat[1] // 2))
                log(f"정합 실패(일치율 {ratio:.0%}) → 휠 {strat[1]}칸으로 줄여 재시도")
                settle(p.delay)
                hint = None
                continue
            reason = (f"이어붙이기 정합 실패 (일치율 {ratio:.0%}) — 휠 칸 수를 1~2로 줄이거나 '스크롤 후 대기'를 "
                      f"1500ms 이상으로 늘리세요")
            break
        if thr_used and thr_used > 6.0:
            log(f"  (화질 차이로 비교 기준을 {thr_used:.0f}로 완화해 정합)")
        pieces.append(cur_img.crop((0, h - bot - dy, cur_img.width, h - bot)))   # 새로 나타난 아래쪽 dy행만
        prev_img, prev_g, prev_sig, hint = cur_img, cur_g, cur_sig, dy
        steps += 1
        log(f"{steps}회 스크롤, 누적 {sum(x.height for x in pieces)}px")

    # ---- 끝에서 영역 '아래쪽' 내용 보충
    # 페이지를 끝까지 내리면 마지막 내용은 뷰포트(창 안의 페이지 화면) 맨 아래에 놓인다. 선택한 영역이 뷰포트보다
    # 짧으면 그 부분(영역 아래~뷰포트 아래)은 스크롤하는 동안 한 번도 영역 안에 들어오지 않아 통째로 빠진다.
    # → 끝 위치에서 영역을 창 아래쪽까지 늘려 한 번 더 찍고, 위로 한 칸 올려 비교해서 '스크롤되는 부분'만 이어붙인다.
    if p.include_tail and reason == "끝까지 스크롤" and steps > 0 and not bot:
        try:
            _vx, _vy, _vw, _vh = virtual_screen()
            cb = min(window_client_bottom(cx, cy), _vy + _vh)
            if cb - box[3] >= 12:
                ext = (box[0], box[1], box[2], int(cb))
                img1 = settle(0.3, 2.5, ext)
                g1 = _gray(img1)
                if float(np.abs(g1[:h] - prev_g).mean()) < 3.0:        # 끝 위치 그대로인지 확인
                    scroll(strat, up=True)
                    g2 = _gray(settle(p.delay, 2.5, ext))
                    scroll(strat)                                       # 다시 아래로 (캡처는 이미 끝났다)
                    changed = np.where(np.abs(g1 - g2).mean(axis=1) > 1.0)[0]
                    bottom = int(changed.max()) + 1 if len(changed) else 0
                    if bottom > h + 4:                                  # 스크롤되는 영역은 거기까지 (이후는 작업표시줄 등 정지 영역)
                        pieces.append(img1.crop((0, h, img1.width, bottom)))
                        log(f"끝 위치에서 영역 아래쪽 {bottom - h}px 추가 (창 아래쪽까지 확장해 스크롤되는 부분만)")
                    else:
                        log("영역 아래쪽에 스크롤되는 내용 없음 (추가 없음)")
                else:
                    log("끝 위치가 달라져 아래쪽 보충을 건너뜀")
        except Exception as ex:
            log(f"아래쪽 보충 실패(무시): {ex}")

    log(f"종료: {reason} · 스크롤 {steps}회 · {describe(strat)} · 총 {sum(x.height for x in pieces)}px")
    total = sum(x.height for x in pieces)
    out = Image.new("RGB", (first.width, total), "white")
    y = 0
    for piece in pieces:
        out.paste(piece, (0, y)); y += piece.height
    return out, {"steps": steps, "reason": reason, "height": total, "frames": len(pieces),
                 "method": describe(strat), "focused": focused}


# ---------------------------------------------------------------- 클립보드 이미지
def copy_image_to_clipboard(img: Image.Image):
    """이미지를 클립보드에 넣는다. 엑셀에서 붙여넣으면 그림으로 붙는다 (Windows: CF_DIB, macOS: PNG/TIFF)."""
    if sys.platform == "win32":
        from sysinput_win import copy_image_to_clipboard as _copy
    else:
        from sysinput_mac import copy_image_to_clipboard as _copy
    _copy(img)

