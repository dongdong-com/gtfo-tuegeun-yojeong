"""회사/환경에 따라 달라지는 값 모음. 공개 저장소에는 예시 값만 있고, 실제 값은 `local_config.py`(git에 올리지 않음)에 적는다.
`local_config.example.py`를 `local_config.py`로 복사해서 자기 환경에 맞게 고치면 된다."""
try:
    import local_config as _local
except ImportError:                                  # 없으면 아래 예시 값으로 동작 (단축 URL 접속 확인 등은 실제 값이 있어야 의미가 있다)
    _local = None


def _get(name, default):
    return getattr(_local, name, default) if _local is not None else default


# 단축 URL 서버 호스트 (예: 'short.example' → http://short.example/s/<ID>). '접속 확인'은 이 서버로 ID만 보낸다.
SHORT_HOST = _get("SHORT_HOST", "short.example")
SHORT_PREFIX = f"http://{SHORT_HOST}/s/"
# 원본 URL의 호스트 (urlfix가 OCR로 깨진 호스트를 이 값으로 되돌린다)
ORIGIN_HOST = _get("ORIGIN_HOST", "www.example.com")
ORIGIN_BASE = ORIGIN_HOST.split(".")[1] if ORIGIN_HOST.count(".") >= 2 else ORIGIN_HOST   # 'example'
# PG 상점 ID (OCR이 틀려도 이 목록 중 가장 가까운 것으로 보정). STORE_ORDER는 수수료정산 양식의 상점 순서.
STORE_IDS = list(_get("STORE_IDS", ["store001", "store002", "store003"]))
STORE_ORDER = list(_get("STORE_ORDER", list(STORE_IDS)))
# 분개 적요 앞에 붙는 말머리 (예: "[팀명] ")
JOURNAL_PREFIX = _get("JOURNAL_PREFIX", "")
# 작업표시줄 그룹용 앱 ID (바꾸면 이미 고정한 작업표시줄 항목과 그룹이 달라진다)
APP_ID = _get("APP_ID", "GTFO.App")
