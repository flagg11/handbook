#!/usr/bin/env bash
# Handbook: установка и первый запуск (Linux и macOS).
# Кладётся в корень проекта рядом с app.py. Ищет Python 3.10+, создаёт .venv,
# ставит зависимости, запускает.  ./setup.sh --no-run  только установить.
set -u
cd "$(dirname "$0")"

NORUN=0
[ "${1:-}" = "--no-run" ] && NORUN=1

fail() { echo; echo "$1"; exit 1; }

[ -f app.py ] && [ -f requirements.txt ] || fail "Не вижу app.py и requirements.txt рядом со скриптом. Положи setup.sh и run.sh в корень проекта Handbook."

echo "[1/4] Ищу Python 3.10 или новее..."
PY=""
for c in python3 python3.13 python3.12 python3.11 python3.10 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.10 или новее не найден. Поставь его (например: sudo apt install python3 python3-venv python3-pip) и запусти setup.sh снова."
echo "     Найден: $($PY --version) ($(command -v $PY))"
echo

if [ -x .venv/bin/python ]; then
  echo "[2/4] Окружение .venv уже есть."
  .venv/bin/python -c 'import sys' >/dev/null 2>&1 || fail "Папка .venv повреждена или создана на другом компьютере. Удали её (rm -rf .venv) и запусти setup.sh снова."
else
  echo "[2/4] Создаю виртуальное окружение .venv..."
  "$PY" -m venv .venv || fail "Не удалось создать окружение. На Debian и Ubuntu нужен пакет python3-venv (sudo apt install python3-venv)."
fi
echo

if cmp -s requirements.txt .venv/requirements.installed; then
  echo "[3/4] Зависимости уже установлены."
else
  echo "[3/4] Ставлю зависимости, это может занять несколько минут..."
  .venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  .venv/bin/python -m pip install -r requirements.txt || fail "Не удалось установить зависимости. Проверь интернет и сообщение pip выше."
  cp requirements.txt .venv/requirements.installed
fi
echo

echo "[4/4] Проверяю Tesseract, он нужен только для распознавания сканов..."
if command -v tesseract >/dev/null 2>&1 || [ -n "${TESSERACT_CMD:-}" ]; then
  echo "     Tesseract найден."
else
  echo "     Tesseract не найден. Это не ошибка: документы с текстом читаются как обычно,"
  echo "     а страницы-сканы будут показываться картинкой без поиска по ним."
  echo "     Чтобы читать сканы: sudo apt install tesseract-ocr tesseract-ocr-rus"
fi
echo

echo "Установка завершена."
if [ "$NORUN" = 1 ]; then exit 0; fi
echo "Запускаю Handbook..."
echo
exec ./run.sh
