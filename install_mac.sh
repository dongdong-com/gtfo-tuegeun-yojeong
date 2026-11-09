#!/bin/bash
# 퇴근요정 macOS 설치: 가상환경(.venv)을 만들고 필요한 패키지를 설치한다. 한 번만 실행하면 된다.
set -e
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then
  echo "이 스크립트는 macOS용입니다 (Windows는 run.bat 사용)."; exit 1
fi

# tkinter가 들어 있는 Python 3.10+ 찾기 (python.org 설치본 권장)
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import tkinter, sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "tkinter가 포함된 Python 3.10 이상을 찾지 못했습니다."
  echo "  1) https://www.python.org/downloads/macos/ 에서 Python 3.12 설치 (tkinter 포함), 또는"
  echo "  2) brew install python@3.12 python-tk@3.12"
  exit 1
fi
echo "사용할 Python: $($PY --version) ($(command -v $PY))"

$PY -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

chmod +x run.command 2>/dev/null || true
echo
echo "설치 완료. 실행: ./run.command  (또는 Finder에서 run.command 더블클릭)"
echo "처음 캡처할 때 시스템 설정 > 개인정보 보호 및 보안에서 '화면 및 시스템 오디오 녹음', '손쉬운 사용'을"
echo "터미널(또는 사용하는 앱)에 허용하세요. 자세한 내용: docs/macos.md"
