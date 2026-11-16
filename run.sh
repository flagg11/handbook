#!/usr/bin/env bash
# Handbook: запуск. Сначала один раз нужен ./setup.sh.
# Настройки сети (HANDBOOK_HOST, HANDBOOK_PASSWORD и т.д.) можно записать
# строками export в файл handbook.env рядом со скриптом, он подхватится сам.
# HANDBOOK_NO_BROWSER=1 отключает открытие браузера.
cd "$(dirname "$0")" || exit 1

[ -f handbook.env ] && . ./handbook.env
export PYTHONUTF8=1
PORT="${HANDBOOK_PORT:-5000}"

[ -x .venv/bin/python ] || { echo "Окружение не найдено. Сначала запусти ./setup.sh"; exit 1; }

HOST="${HANDBOOK_HOST:-127.0.0.1}"
if [ -z "${HANDBOOK_NO_BROWSER:-}" ] && [ "$HOST" = "127.0.0.1" ]; then
  opener=""
  command -v xdg-open >/dev/null 2>&1 && opener=xdg-open
  command -v open >/dev/null 2>&1 && opener=open
  [ -n "$opener" ] && ( sleep 3; "$opener" "http://127.0.0.1:$PORT" >/dev/null 2>&1 ) &
fi

echo "Handbook запускается: http://127.0.0.1:$PORT"
echo "Остановить: Ctrl+C"
echo
exec .venv/bin/python app.py
