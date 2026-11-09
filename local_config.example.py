"""환경 설정 예시. 이 파일을 `local_config.py`로 복사해서 값을 고치세요 (local_config.py는 git에 올라가지 않습니다).
설정하지 않으면 config.py의 예시 값으로 동작합니다."""
SHORT_HOST = "short.example"                 # 단축 URL 서버 호스트 → http://short.example/s/<ID>
ORIGIN_HOST = "www.example.com"              # 원본 URL의 호스트
STORE_IDS = ["store001", "store002", "store003"]     # PG 상점 ID
STORE_ORDER = ["store001", "store002", "store003"]   # 수수료정산 양식의 상점 순서
JOURNAL_PREFIX = ""                          # 분개 적요 말머리 (예: "[팀명] ")
APP_ID = "GTFO.App"                          # 작업표시줄 그룹 ID
