"""macOS OCR: Apple Vision(VNRecognizeTextRequest) — 이 Mac 안에서만 동작한다 (인터넷 전송 없음).
core.py가 macOS에서 Windows OCR(winrt) 대신 불러온다. 반환 형식은 core._recognize와 같다:
    [(text, x, y중심, 높이, 너비)]  — 좌표는 '넘겨 받은 이미지' 기준 픽셀, 원점 왼쪽 위.

필요: pip install pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa  (macOS 12 이상, 한국어는 13 이상 권장)
"""
import re

# 언어 태그 정리: Windows 쪽 코드가 쓰는 'ko', 'en-US' 같은 태그를 Vision 태그로 바꾼다.
_VISION_TAG = {"ko": "ko-KR", "en": "en-US", "ja": "ja-JP", "zh": "zh-Hans", "zh-Hans": "zh-Hans", "zh-Hant": "zh-Hant"}
_NAMES = {"ko-KR": "한국어", "en-US": "English", "ja-JP": "日本語", "zh-Hans": "简体中文", "zh-Hant": "繁體中文"}

# 언어 보정: 켜면 사전에 있는 단어로 고쳐 읽는다. 상점 ID·단축 URL 같은 코드 글자는 오히려 망가지므로 기본은 끈다.
LANG_CORRECTION = False


def _tag(lang: str) -> list:
    if lang in ("", "auto", None):
        return ["ko-KR", "en-US"]
    t = _VISION_TAG.get(lang) or _VISION_TAG.get(lang.split("-")[0]) or lang
    return [t] if t == "en-US" else [t, "en-US"]          # 한글 문서 속 영문/숫자도 함께 읽도록 영어를 덧붙인다


def languages() -> list:
    """[(태그, 표시 이름)] — Windows와 맞춘 짧은 태그('ko', 'en-US')."""
    return [("ko", "한국어"), ("en-US", "English")]


def recognize(png_bytes: bytes, width: int, height: int, lang: str = "ko") -> list:
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(LANG_CORRECTION)
    try:
        req.setRecognitionLanguages_(_tag(lang))
    except Exception:
        pass
    try:                                                    # 작은 글자도 놓치지 않도록 (기본값은 3% 높이 이상만 읽는다)
        req.setMinimumTextHeight_(0.0)
    except Exception:
        pass
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Apple Vision OCR 실패: {err}")

    words = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        cand = cands[0]
        text = str(cand.string())
        for m in re.finditer(r"\S+", text):
            box = None
            try:                                            # 글자 위치(UTF-16 단위)로 단어별 상자를 얻는다
                u16 = lambda n: len(text[:n].encode("utf-16-le")) // 2
                start, end = u16(m.start()), u16(m.end())
                rect_obs, _e = cand.boundingBoxForRange_error_((start, end - start), None)
                if rect_obs is not None:
                    box = rect_obs.boundingBox()
            except Exception:
                box = None
            if box is None:                                 # 실패하면 줄 상자를 글자 수 비율로 나눠 쓴다
                lb = obs.boundingBox()
                n = max(1, len(text))
                x0 = lb.origin.x + lb.size.width * m.start() / n
                w = lb.size.width * (m.end() - m.start()) / n
                bx, by, bw, bh = x0, lb.origin.y, w, lb.size.height
            else:
                bx, by, bw, bh = box.origin.x, box.origin.y, box.size.width, box.size.height
            # Vision 좌표: 0~1 정규화, 원점 왼쪽 아래 → 이미지 픽셀(원점 왼쪽 위)로
            x = bx * width
            h = bh * height
            yc = (1.0 - (by + bh / 2)) * height
            words.append((m.group(), x, yc, h, bw * width))
    return words
