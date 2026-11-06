# полный сброс: настройки, индекс и кэши уезжают в _backup_<время> (ничего не стирается).
# дальше при запуске снова мастер первой настройки; остановите программу перед сбросом. файлы в папке хранилища не трогаем
# запуск: python tools/reset_data.py
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(ROOT, f"_backup_{stamp}")
    moved = []
    for name in ("data", "uploads"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            os.makedirs(backup, exist_ok=True)
            shutil.move(src, os.path.join(backup, name))
            moved.append(name)
    print("Перенесено в", backup if moved else "- нечего переносить:", ", ".join(moved))


if __name__ == "__main__":
    main()
