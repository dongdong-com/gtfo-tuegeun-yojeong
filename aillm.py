"""로컬 AI(Gemma 4 E2B, Ollama) 호출 도우미 — 이 PC 안(localhost)에서만 동작하고 이미지/텍스트는 밖으로 나가지 않는다.

쓰임새
 - correct_prompt(): Windows OCR 초안 + 이미지 → 틀린 글자/빠진 글자(로고·작은 글자·날짜)를 고친 텍스트 (텍스트 캡쳐하기의 'AI로 보정')
 - IMAGE_PROMPTS: 이미지 → 프롬프트/설명 (이미지 캡쳐하기)
쓰면 안 되는 곳: 단축 URL ID, 정산 금액 (모델이 그럴듯한 값을 만들 수 있다 — 결정적 검증이 있는 곳은 그대로 둔다)

시험 결과(i7-1360P, GPU 없음): 글자 읽기 1배 7~11초, 2배 확대 9~32초. 생각(thinking)은 꺼야 3배 빠르다."""
import base64
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from PIL import Image

HOST = "http://127.0.0.1:11434"
MODEL = "gemma4:e2b"
def _find_ollama() -> str:
    """Ollama 실행 파일 경로 (없으면 빈 문자열). Windows: 사용자 설치 위치 / macOS: Homebrew·앱 번들·PATH."""
    import shutil
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama"):
        if os.path.exists(p):
            return p
    return shutil.which("ollama") or ""


OLLAMA_EXE = _find_ollama()
INSTALL_HINT = ("winget install Ollama.Ollama" if sys.platform == "win32"
                else "brew install ollama  (또는 https://ollama.com/download 에서 Ollama.app 설치)")


class AIError(Exception):
    pass


# ---------------------------------------------------------------- 서버 상태
def _get(path: str, timeout: float = 3.0):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return json.load(r)


def server_up() -> bool:
    try:
        urllib.request.urlopen(HOST, timeout=2).read()
        return True
    except Exception:
        return False


def ensure_server(wait: float = 20.0) -> None:
    """Ollama 서버가 꺼져 있으면 숨김 창으로 켠다. 설치가 안 되어 있으면 AIError."""
    if server_up():
        return
    if not OLLAMA_EXE or not os.path.exists(OLLAMA_EXE):
        raise AIError(f"Ollama가 설치되어 있지 않습니다.\n설치: {INSTALL_HINT}  →  ollama pull " + MODEL)
    try:
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW
        subprocess.Popen([OLLAMA_EXE, "serve"], **flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except OSError as ex:
        raise AIError(f"Ollama를 시작하지 못했습니다: {ex}")
    t0 = time.time()
    while time.time() - t0 < wait:
        if server_up():
            return
        time.sleep(0.5)
    raise AIError("Ollama 서버가 시작되지 않았습니다. 잠시 뒤 다시 시도하세요.")


def model_ready() -> bool:
    try:
        names = [m.get("name", "") for m in _get("/api/tags").get("models", [])]
    except Exception:
        return False
    return any(n == MODEL or n.startswith(MODEL.split(":")[0] + ":" + MODEL.split(":")[1]) for n in names)


def check() -> str:
    """사용 가능하면 '', 아니면 안내 문구."""
    try:
        ensure_server()
    except AIError as ex:
        return str(ex)
    if not model_ready():
        return f"AI 모델({MODEL})이 없습니다.\n설치: ollama pull {MODEL}"
    return ""


# ---------------------------------------------------------------- 이미지/호출
def prep_image(img: Image.Image) -> Image.Image:
    """모델이 작은 글자까지 읽도록 작은 이미지는 키우고(최대 2배, 긴 변 2000px까지), 너무 큰 이미지는 줄인다(긴 변 2600px)."""
    img = img.convert("RGB")
    long = max(img.size)
    if long < 2000:
        s = min(2.0, 2000 / long)
    else:
        s = min(1.0, 2600 / long)
    if abs(s - 1) > 0.05:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    return img


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def chat(prompt: str, img: "Image.Image | list | None" = None, on_token=None, cancel: threading.Event | None = None,
         num_predict: int = 1200, timeout: float = 600.0, prep: bool = True) -> str:
    """프롬프트(+이미지 한 장 또는 여러 장)를 보내 답을 스트리밍으로 받는다. on_token(누적문자열)이 토큰마다 불린다. 항상 temperature 0, 생각 끔."""
    msg = {"role": "user", "content": prompt}
    if img is not None:
        imgs = img if isinstance(img, (list, tuple)) else [img]
        msg["images"] = [_b64(prep_image(i) if prep else i.convert("RGB")) for i in imgs]     # prep=False: 호출한 쪽이 크기를 이미 정했다
    body = {"model": MODEL, "stream": True, "think": False, "messages": [msg],
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": num_predict}}
    req = urllib.request.Request(HOST + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    out = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                if cancel is not None and cancel.is_set():
                    raise AIError("중단했습니다.")
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise AIError(str(d["error"]))
                out += d.get("message", {}).get("content", "")
                if on_token:
                    on_token(out)
                if d.get("done"):
                    break
    except urllib.error.URLError as ex:
        raise AIError(f"AI 서버에 연결하지 못했습니다: {ex}")
    return out.strip()


def clean_answer(text: str) -> str:
    """모델이 붙이는 코드펜스/머리말을 걷어낸다."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


# ---------------------------------------------------------------- 프롬프트
def correct_prompt(draft: str) -> str:
    return ("아래는 OCR이 이 이미지에서 읽은 초안이다. 이미지를 보고 틀린 글자만 고치고, 빠진 글자(로고, 작은 글자, 날짜)를 "
            "추가해서 최종 텍스트만 출력해라. 줄바꿈 구조는 초안을 따르고, 설명은 쓰지 마라. 이미지에 없는 내용은 만들지 마라.\n\n"
            "초안:\n" + draft)


IMAGE_PROMPTS = {
    "이미지 생성 AI용 프롬프트": (
        "이 이미지를 이미지 생성 AI(Midjourney, DALL·E, Stable Diffusion 등)로 비슷하게 다시 만들 수 있는 프롬프트를 써라. "
        "피사체와 배경, 구도·시점, 스타일(사진/일러스트/3D 등), 색감, 조명, 분위기를 쉼표로 이어 한 단락으로 구체적으로 적어라. "
        "이미지 속 글자는 큰따옴표로 그대로 포함해라. 프롬프트 본문만 출력해라."),
    "화면(UI) 구현용 프롬프트": (
        "이 이미지는 웹/앱 화면이다. 개발자나 코딩 AI에게 이 화면을 똑같이 구현하라고 지시하는 프롬프트를 써라. "
        "전체 레이아웃(영역 배치), 각 구성요소(헤더, 카드, 버튼, 표, 입력창 등)와 그 안의 글자(그대로), 색상(대략의 색 이름), "
        "간격·정렬 특징을 항목별로 정리해라. 프롬프트 본문만 출력해라."),
    "이미지 설명 (대체 텍스트)": (
        "이 이미지에 무엇이 있는지 보이지 않는 사람에게 설명하듯 간결하게 써라. 보이는 글자는 그대로 인용하고, "
        "추측은 하지 마라. 설명 본문만 출력해라."),
    "직접 지시": "",
}


def image_prompt(kind: str, lang: str, custom: str = "") -> str:
    base = IMAGE_PROMPTS.get(kind, "") if kind != "직접 지시" else custom.strip()
    if kind == "직접 지시" and not base:
        raise AIError("직접 지시를 입력하세요.")
    out_lang = "영어로" if lang == "English" else "한국어로"
    if kind == "직접 지시":
        return base
    return f"{base}\n\n답은 {out_lang} 작성해라. 머리말·맺음말·구분선(---)·'다음은 …입니다' 같은 문장 없이 본문만 써라."


# ---------------------------------------------------------------- 백그라운드 실행 (화면이 멈추지 않게)
def run_async(widget, work, on_token=None, on_done=None, on_error=None) -> threading.Event:
    """work(cancel_event, emit)를 스레드에서 실행하고 결과를 widget(tk) 스레드로 전달한다.
    work는 emit(누적문자열)로 진행을 알리고 최종 문자열을 돌려준다. 반환값(Event).set()으로 중단."""
    q: queue.Queue = queue.Queue()
    cancel = threading.Event()

    def runner():
        try:
            res = work(cancel, lambda s: q.put(("tok", s)))
            q.put(("done", res))
        except Exception as ex:                              # AIError 포함
            q.put(("err", ex))

    def poll():
        last = None
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "tok":
                    last = val
                elif kind == "done":
                    if last is not None and on_token:
                        on_token(last)
                    if on_done:
                        on_done(val)
                    return
                else:
                    if on_error:
                        on_error(val)
                    return
        except queue.Empty:
            pass
        if last is not None and on_token:
            on_token(last)
        try:
            widget.after(150, poll)
        except Exception:
            pass

    threading.Thread(target=runner, daemon=True).start()
    widget.after(150, poll)
    return cancel
