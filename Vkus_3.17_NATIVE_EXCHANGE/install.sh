#!/usr/bin/env bash
set -e
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-tk firefox-esr ffmpeg
# Optional fingerprint stack. If hardware/driver is unsupported, the app simply disables fingerprint login.
sudo apt-get install -y fprintd libfprint-2-2 || true
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
printf '\nVkus установлен. Запуск: ./run.sh\n'
