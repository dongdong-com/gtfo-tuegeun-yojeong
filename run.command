#!/bin/bash
# 퇴근요정 macOS 실행 (Finder에서 더블클릭하거나 터미널에서 ./run.command)
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "먼저 ./install_mac.sh 를 실행하세요."; read -n 1 -s -r -p "아무 키나 누르면 닫힙니다"; exit 1
fi
exec .venv/bin/python app.py
