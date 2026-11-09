# 커스터마이징: 메뉴와 기능 바꾸기

[← README로 돌아가기](../README.md) · [문서 목록](../README.md#문서)

코드는 파이썬 파일 몇 개로 나뉘어 있어서 메뉴·화면·AI·색을 파일 한두 군데만 고쳐서 바꿀 수 있습니다. 고친 뒤에는 **앱을 껐다 켜야** 반영됩니다. (아래 예제는 모두 실제로 실행해서 확인했습니다.)

## 1. 메뉴 바꾸기 — `app.py`의 `MENU`

메뉴는 `app.py` 위쪽의 `MENU` 목록 하나로 정해집니다. 왼쪽 트리의 글자는 아래 문자열이고, 화면은 페이지 클래스입니다.

```python
MENU = [
    ("정산", [                                   # 1depth (폴더)
        ("포스티니", [                            # 2depth (폴더)
            (PrepaidPage.TITLE, PrepaidPage),     # 3depth (화면)
            (FeeSettlePage.TITLE, FeeSettlePage),
        ]),
    ]),
    ("운영", [
        ("AI캡쳐하기", [(TextExtractPage.TITLE, TextExtractPage),
                        (ImagePromptPage.TITLE, ImagePromptPage)]),
        (VdiTablePage.TITLE, VdiTablePage),       # 2depth에서 바로 열리는 화면 (하위 목록 대신 클래스를 직접 줌)
    ]),
]
```

| 하고 싶은 일 | 방법 |
|---|---|
| 메뉴 이름 바꾸기 | 문자열을 고친다 (`"운영"` → `"내 도구"`). 3depth 화면 이름은 `페이지클래스.TITLE`이므로 이름을 바꾸려면 문자열을 직접 쓰거나 그 클래스의 `TITLE`을 고친다 |
| 메뉴 숨기기/지우기 | 그 줄을 지우거나 `#`으로 주석 처리한다 (`import`는 그대로 둬도 된다). 쓰지 않는 AI 메뉴를 빼려면 `AI캡쳐하기` 줄을 지운다 |
| 순서 바꾸기 | 목록 순서를 바꾼다. **맨 처음 화면이 앱을 켰을 때 기본으로 선택**된다 |
| 화면을 다른 폴더로 옮기기 | 항목(튜플)을 다른 폴더의 목록으로 옮긴다 |
| 2depth에서 바로 열기 | `("이름", 페이지클래스)`처럼 하위 목록 없이 클래스를 직접 적는다 |
| 1depth를 새로 만들기 | `("새 폴더", [("하위 폴더 또는 화면", ...)])` 구조를 목록에 추가한다 |

## 2. 새 화면 추가하기

화면은 `ttk.Frame`을 상속한 클래스입니다. `__init__(self, master, ctx)`를 받으면 되고, `ctx`는 앱 자신입니다(`ctx.template`은 모든 화면이 공유하는 양식 파일 경로 `tk.StringVar`). 화면은 메뉴를 **처음 열 때 한 번만** 만들어지고 이후엔 입력값이 그대로 유지됩니다.

```python
# my_pages.py  (새 파일)
from tkinter import ttk

class HelloPage(ttk.Frame):
    TITLE = "안녕 페이지"

    def __init__(self, master, ctx):
        super().__init__(master)
        ttk.Label(self, text="안녕하세요! 양식 파일:").pack(pady=(40, 4))
        ttk.Label(self, textvariable=ctx.template).pack()
```

`app.py`에서 불러와 `MENU`에 넣으면 끝입니다.

```python
from my_pages import HelloPage            # app.py 위쪽 import 근처
MENU = [("내 도구", [("안녕", HelloPage)])] + MENU     # MENU 정의 아래에 두면 맨 위에 새 폴더가 생긴다
```

> **업데이트를 받아도 내 코드가 덜 충돌하게**: 새 화면과 확장은 `my_pages.py` 같은 **새 파일**에 만들고 `app.py`에는 import와 메뉴 한 줄만 추가하세요. 회사/환경 값은 `local_config.py`(아래)에 두면 git에 올라가지 않습니다.

## 3. 캡처 화면을 가져다 변형하기 (상속)

캡처·OCR·표 만들기·복사·저장·인쇄는 이미 만들어져 있어서, 기존 화면을 **상속해서 설정만 바꾸는 것**이 가장 쉽습니다.

| 부모 클래스 | 파일 | 용도 |
|---|---|---|
| `VdiTablePage` | `page_vdi.py` | 스크롤 캡처 + OCR + 표/단축 URL (모든 캡처 화면의 기본) |
| `DciTablePage` | `page_dci.py` | 일반 표 → 엑셀 행/열 (행 구분선, 정밀 OCR, AI 보정) |
| `TextExtractPage` | `page_text.py` | 글자 추출 (다단 읽기, 문단 합치기, AI 보정) |
| `ImagePromptPage` | `page_image.py` | 이미지 → 프롬프트 만들기 (로컬 AI) |

```python
from page_dci import DciTablePage

class MyTablePage(DciTablePage):
    TITLE = "내 표 캡처"        # 메뉴 이름
    DEFAULT_SCALE = "4.0"       # OCR 배율 기본값 (글자가 작으면 올린다)
    FLAG_CELLS = False          # 복사할 때 확인 필요 칸을 엑셀에서 노란색으로 칠할지
    INTRO = "내 표 전용 화면입니다."   # 처음 상태줄에 보이는 안내
```

바꿀 수 있는 **클래스 값**: `TITLE`, `URL_TOOLS`(단축 URL 전용 도구 표시), `OCR_TILE`(넓은 이미지를 가로 타일로 나눠 읽기), `FLAG_CELLS`, `DEFAULT_SCALE`, `INTRO`, `HINT`.
덮어쓸 수 있는 **훅(함수)**:

| 훅 | 언제 불리나 / 용도 |
|---|---|
| `_init_extra(self)` | 화면을 만들기 전 — 변수(`tk.StringVar` 등) 추가 |
| `_extra_bar(self, bar, bar2)` | 표 옵션 줄(`bar`, `bar2`)에 체크박스·버튼 추가 |
| `_make_table(self)` | OCR 단어 → `(표, 설명)`. **결과 표를 가공**하려면 부모 것을 부르고 고친다 |
| `_prepare_for_ocr(self, img)` | OCR 전에 이미지 가공 (좌표는 바뀌면 안 됨) |
| `_ocr_words(self, img, progress)` | OCR을 통째로 바꾸고 싶을 때 |
| `_ocr_lang(self)` | OCR 언어 태그 (`"ko"`) |
| `_extra_flags(self, table)` | 복사 때 노란색으로 칠할 칸 `{(행, 열), …}` 추가 |

```python
class MyTablePage(DciTablePage):
    TITLE = "금액 표 캡처"

    def _make_table(self):
        table, mode = super()._make_table()
        table = [[c.replace("원", "") for c in row] for row in table]   # 예: 모든 칸에서 '원' 글자 제거
        return table, mode
```

## 4. 회사/환경 값 — `local_config.py`

`local_config.example.py`를 `local_config.py`로 복사해 고칩니다 (git에 올라가지 않음). 없으면 `config.py`의 예시 값을 씁니다.

| 값 | 의미 |
|---|---|
| `SHORT_HOST` | 단축 URL 서버 호스트. `http://<호스트>/s/<ID>` 형식을 인식·접속 확인 |
| `ORIGIN_HOST` | 원본 URL 호스트 (OCR로 깨진 호스트를 되돌림) |
| `STORE_IDS`, `STORE_ORDER` | PG 상점 ID 목록, 수수료정산 양식의 상점 순서 |
| `JOURNAL_PREFIX` | 분개 적요 앞 말머리 (예: `"[팀명] "`) |
| `APP_ID` | 작업표시줄 그룹 ID (바꾸면 이미 고정한 항목과 그룹이 달라짐) |

단축 URL의 경로·파라미터 이름·고정값은 `urlfix.py` 위쪽 상수(`PATH_SEGS`, `KEYS`, `VALUES`, `DIGITS`), 분개 규칙과 양식 시트 이름은 `core.py`, 기본 양식 파일 경로는 `app.py`의 `DEFAULT_TEMPLATE`입니다.

## 5. AI 기능 바꾸기

| 바꾸려는 것 | 위치 |
|---|---|
| 사용할 모델 / 서버 | `aillm.py`의 `MODEL = "gemma4:e2b"`, `HOST`. 다른 Ollama 모델을 `ollama pull` 한 뒤 `MODEL`만 바꾸면 된다 (이미지 입력을 받는 모델이어야 함) |
| **이미지 캡쳐하기의 프롬프트 종류 추가·수정** | `aillm.py`의 `IMAGE_PROMPTS` 딕셔너리에 `"이름": "지시문"` 한 줄을 넣으면 콤보박스에 나타난다 (예: `"회의록 요약": "이 화면의 내용을 회의록 형식으로 요약해라."`). 프로그램을 시작할 때 읽으므로 `aillm.py`를 **직접 고쳐야** 한다 |
| 텍스트 `AI로 보정` 지시문 | `aillm.py`의 `correct_prompt()` |
| DCI 칸 읽기 AI의 정확도/속도 | `page_dci.py` 위쪽 `READ_TARGETS`(글자 높이 배율, 크면 정확하지만 느림), `CELL_PROMPT`, 동시 읽기 수(`ai_fix` 안 `ThreadPoolExecutor(2)`, 이 PC에서는 2가 최적) |
| OCR을 여러 설정으로 읽는 조합 | `ocrplus.py`의 `VARIANTS_FULL/MID/BIG` (배율, 선명화, 어둡게) |
| AI를 아예 쓰지 않기 | `MENU`에서 `AI캡쳐하기`를 지우고, DCI의 AI 버튼이 필요 없으면 `page_dci.py`의 `_extra_bar`에서 해당 버튼 줄을 지운다 (Ollama가 없으면 버튼을 눌렀을 때 안내만 나옴) |


## 6. 모양 바꾸기

| 바꾸려는 것 | 위치 |
|---|---|
| 색 | `theme.py` 위쪽 색 상수 (`CORAL`, `NAVY` …). 체크박스 모양은 `_check_images` |
| 캐릭터·아이콘 | `assets/source/`의 원본을 바꾸고 `python make_assets.py` |
| 창 제목·버전·헤더 글자 | `app.py`의 `APP_TITLE`, `VERSION`, `BUILD_DATE`, `_header()` |
| 창 크기 | `app.py`의 `self.geometry("1360x860")` |
| 작업표시줄 이름 | `taskbar_id.py`의 `APP_NAME` |
- 저해상도 캐릭터(`assets/source/character_small.png`) → 창/작업표시줄 아이콘, 파비콘, 고해상도 캐릭터(`assets/source/character_large.webp`) → 상단 헤더. 원본을 바꾼 뒤 `python make_assets.py`.
- UI 색은 캐릭터에서 가져왔습니다: 머리띠 코랄 `#F56B76`, 진한 코랄 `#993E44`, 외곽선 플럼 `#2A151B`, 날개 하늘색 `#E3EFFD`, 목걸이 네이비 `#4A68B4`, 별 노랑 `#FEEC95`.
