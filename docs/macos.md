# macOS에서 쓰기

[← README로 돌아가기](../README.md) · [문서 목록](../README.md#문서)

> ⚠️ **macOS 지원은 3.2에서 추가되었고, 개발 PC(Windows)에는 Mac이 없어 실제 Mac에서의 동작은 아직 확인하지 못했습니다.**
> Windows 쪽 동작은 그대로 확인했고, Mac용 코드는 Apple 공식 API(Vision·Quartz·AppKit) 사용법에 맞춰 작성했습니다.
> 써 보시고 안 되는 부분은 [이슈](https://github.com/dongdong-com/gtfo-tuegeun-yojeong/issues)로 알려 주세요. 아래 [알려진 차이](#windows와-다른-점)도 참고하세요.

## 설치

**필요한 것**: macOS 13(Ventura) 이상 권장 · Python 3.10 이상(**tkinter 포함**)

1. **Python 설치** — [python.org](https://www.python.org/downloads/macos/)의 설치 프로그램을 쓰면 tkinter가 들어 있습니다. Homebrew를 쓴다면 `brew install python@3.12 python-tk@3.12`.
2. **내려받기와 설치**

```bash
git clone https://github.com/dongdong-com/gtfo-tuegeun-yojeong.git
cd gtfo-tuegeun-yojeong
./install_mac.sh
```

3. **실행**

```bash
./run.command
```

Finder에서 `run.command`를 더블클릭해도 됩니다. (처음에는 *우클릭 > 열기*가 필요할 수 있습니다.)

`install_mac.sh`는 폴더 안에 `.venv`(가상환경)를 만들고 `requirements.txt`의 맥용 패키지(`pyobjc-*`, `pillow`, `numpy`, `openpyxl`)를 설치합니다.

## 권한 설정 (처음 한 번)

*시스템 설정 > 개인정보 보호 및 보안*에서 **퇴근요정을 실행한 앱(터미널, iTerm, VS Code 등)** 을 허용하세요. 허용한 뒤에는 그 앱을 완전히 종료했다가 다시 열어야 적용됩니다.

| 권한 | 필요한 기능 | 없으면 |
|---|---|---|
| **화면 및 시스템 오디오 녹음** | 모든 화면 캡처 | 바탕화면만 찍히거나 빈 이미지가 나옵니다 |
| **손쉬운 사용** | 스크롤 캡처(휠·키 입력을 다른 창에 보냄) | 스크롤이 되지 않습니다 |
| **입력 모니터링** | 스크롤 캡처·접속 확인 중 `ESC` 중단 | `ESC`가 먹지 않을 수 있습니다 |

## Windows와 다른 점

| 항목 | Windows | macOS |
|---|---|---|
| OCR | Windows 내장 OCR | **Apple Vision** (이 Mac 안에서 동작, 인터넷 전송 없음). 한국어는 macOS 13 이상 |
| 화면 캡처 | 화면 그대로 | Retina는 **2배 해상도**로 캡처되어 OCR에 유리 (`screencapture` 사용) |
| 엑셀 붙여넣기 | 텍스트 + HTML 서식(`mso-number-format`) | 텍스트 + HTML. **Mac용 엑셀이 날짜·앞자리 0 서식을 얼마나 따르는지는 확인이 필요합니다** — 달라 보이면 엑셀의 붙여넣기 옵션을 확인하세요 |
| 이미지 복사 | 클립보드 비트맵 | PNG/TIFF |
| 인쇄 | 인쇄 미리보기 창 / 프린터 선택 창 | **미리보기(Preview) 앱**에서 A4 PDF가 열립니다 → `⌘P`로 인쇄 |
| 안내 말풍선 | 캡처에서 제외·클릭 통과 | 캡처하는 순간에만 잠시 숨김 |
| 글꼴 | 맑은 고딕 | Apple SD Gothic Neo |
| 창 아이콘 | 작업표시줄 아이콘 | Dock 아이콘은 Python 기본값일 수 있음 |
| 로컬 AI | `winget install Ollama.Ollama` | `brew install ollama` 또는 [Ollama.app](https://ollama.com/download), 이어서 `ollama pull gemma4:e2b` |

## 문제 해결

| 증상 | 확인 |
|---|---|
| `No module named '_tkinter'` | tkinter가 없는 Python입니다. python.org 설치본을 쓰거나 `brew install python-tk@3.12` |
| 캡처가 바탕화면만 나옴 | *화면 및 시스템 오디오 녹음* 권한 + 앱 재시작 |
| 스크롤 캡처에서 스크롤이 안 됨 | *손쉬운 사용* 권한. 안 되면 `scroll_capture.log`(폴더 안)의 진단 로그를 확인 |
| 스크롤이 **반대 방향**으로 감 | 휠 방향 설정(자연스러운 스크롤)과 합성 입력의 방향이 다를 수 있습니다. 이 경우 `이어붙이기 정합 실패`가 나옵니다 — 이슈로 알려 주세요 |
| 한국어가 안 읽힘 | macOS 13 이상인지 확인 (그 미만은 Vision이 한국어를 지원하지 않습니다) |
| 영역 선택 화면이 메뉴바 아래에서 시작함 | macOS가 창 위치를 보정한 것입니다. 메뉴바 영역은 선택할 수 없습니다 |

## 개발자용: 구조

운영체제에 따라 달라지는 부분만 따로 두었습니다.

| 기능 | Windows | macOS |
|---|---|---|
| OCR | `core.py`의 winrt | `ocr_mac.py` (Vision) |
| 마우스·키·창·화면 캡처·이미지 클립보드 | `sysinput_win.py` (user32) | `sysinput_mac.py` (Quartz·AppKit) |
| 엑셀용 텍스트+HTML 클립보드 | `clipfmt.py` | `sysinput_mac.set_text_html` |
| 인쇄 | `printing.py`의 PowerShell | `printing._launch_mac` (PDF → Preview) |

`scrollcap.py`는 두 모듈 중 하나를 `sys.platform`으로 골라 같은 이름의 함수(`get_cursor`, `set_cursor`, `_wheel`, `grab` …)를 쓰므로, 스크롤·이어붙이기 알고리즘은 두 OS가 공유합니다.
