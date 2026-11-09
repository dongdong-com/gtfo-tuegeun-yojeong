# 파일 구성

[← README로 돌아가기](../README.md) · [문서 목록](../README.md#문서)

| 파일 | 역할 |
|------|------|
| `app.py` | 창, 상단 캐릭터 헤더, 메뉴(1~3depth), 공용 양식 경로, 창 아이콘 |
| `theme.py` | 캐릭터 색으로 만든 UI 테마 (팔레트 상수만 고치면 색 변경) |
| `make_assets.py` | `assets/source/`의 캐릭터 원본에서 배경을 지우고 아이콘·파비콘·헤더 이미지 생성 |
| `assets/` | `icon.ico`(창/작업표시줄/바로가기), `favicon.ico`, `header.png`(상단), `character.png`(배경 제거 원본 크기), `source/`(원본) |
| `page_prepaid.py` | 선급금/미지급금 처리 화면 |
| `page_fee.py` | PG(이니시스) 수수료 정산 화면 |
| `page_vdi.py` | 운영 > Data&Url캡쳐 > 단축URL 캡처 화면 (스크롤 캡처 공통 부분 포함) |
| `capture_tip.py` | 스크롤 캡처 중 마우스 옆 안내 말풍선 (캡처 제외·클릭 통과·비활성) |
| `clipfmt.py` | 엑셀 붙여넣기용 클립보드 (텍스트 + HTML 서식: 날짜 초 표시, 앞자리 0 유지) |
| `printing.py` | 캡처 이미지 인쇄: 쪽 나누기(글자 없는 줄에서 자름), 옵션 창, Windows 미리보기/인쇄 대화상자 호출 |
| `aillm.py` | 로컬 AI(Ollama·Gemma 4 E2B) 호출: 서버 자동 시작·상태 확인, 스트리밍 응답, 보정/프롬프트 문구, 백그라운드 실행 |
| `page_image.py` | 운영 > AI캡쳐하기 > 이미지 캡쳐하기 화면 (이미지 → 프롬프트) |
| `page_text.py` | 운영 > AI캡쳐하기 > 텍스트 캡쳐하기 화면 (+ AI 보정) (영역/스크롤 캡처·이미지 파일·클립보드 → 텍스트, 줄바꿈·다단·영문 보정) |
| `page_dci.py` | 운영 > Data&Url캡쳐 > DCI 테이블 캡처 화면 (단축URL 캡처를 상속, 표 자동 탐지) |
| `scrollcap.py` | 자동 스크롤 캡처, 프레임 정합·이어붙이기, 이미지 클립보드 복사 |
| `text_picker.py` | 캡처 이미지에서 드래그한 부분/전체를 OCR해 텍스트로 복사 |
| `ocrplus.py` | 일반 텍스트·표용 정밀 OCR: 여러 배율·선명화·어둡게로 읽고 열/줄 단위로 가장 좋은 결과 선택 |
| `sysinput_win.py` / `sysinput_mac.py` | OS별 마우스·키 입력, 창 제어, 화면 캡처, 이미지 클립보드 (Windows: user32 / macOS: Quartz) |
| `ocr_mac.py` | macOS OCR (Apple Vision) |
| `taskbar_id.py` | 작업표시줄 고정 항목에 퇴근요정 아이콘·이름 표시 (Windows) |
| `urlrec.py` | OCR 단어 → (순번, 원본 URL, 단축 URL) 레코드 조립 |
| `urlfix.py` | 원본 URL 구조 보정 (호스트/경로/파라미터) |
| `idfix.py` | 단축 URL ID 글자 모양 보정, I/l 모호 표시 |
| `shortverify.py` | (선택) 단축 URL 서버 접속으로 I/l 확정 |
| `tablegrid.py` | 긴 이미지 OCR(조각 분할), 단어 → 행/열 표 변환, 엑셀 저장 |
| `core.py` | OCR, 파싱, 자동 보정, 분개 생성, 엑셀/클립보드 |
| `ui_common.py` | 영역 드래그 캡처, OCR 호출 |
| `문서 양식.xlsx` | (저장소에 없음) 분개 양식. 시트: `PG사(이니시스) 수수료정산`, `미지급금 및 선급금` — 정산 화면을 쓰려면 직접 준비해 같은 폴더에 둔다 |
| `config.py`, `local_config.example.py` | 환경 값(단축 URL 서버, 상점 ID 등)의 기본값 / 예시 (`local_config.py`는 git에 올리지 않음) |
| `LICENSE` | MIT 라이선스 |
| `docs/`, `CHANGELOG.md` | 기능별 자세한 문서 / 변경 이력 |
| `requirements.txt`, `run.bat` | 설치 목록(OS별 조건부) / Windows 실행 |
| `install_mac.sh`, `run.command` | macOS 설치(가상환경) / 실행 |
| `.gitattributes` | 맥 스크립트의 줄바꿈을 LF로 고정 |
