# демо-документ с фотографиями и графиком -> demo_upload/Акт осмотра с фотографиями.pdf
# запуск: python tools/make_photo_doc.py
import io
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo_upload", "Акт осмотра с фотографиями.pdf")
font_dir = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DV", os.path.join(font_dir, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", os.path.join(font_dir, "DejaVuSans-Bold.ttf")))


def fake_photo(seed, label):
    """Фотография-имитация: градиент, шум, размытые пятна."""
    rng = np.random.default_rng(seed)
    h, w = 420, 640
    y, x = np.mgrid[0:h, 0:w]
    base = 110 + 70 * np.sin(x / 90.0 + seed) * np.cos(y / 70.0) + rng.normal(0, 9, (h, w))
    rgb = np.stack([base * 0.95, base * 1.0, base * 0.8], axis=2).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(rgb)
    d = ImageDraw.Draw(img)
    for _ in range(9):
        cx, cy, r = rng.integers(40, w - 40), rng.integers(40, h - 40), rng.integers(30, 90)
        col = tuple(int(v) for v in rng.integers(40, 220, 3))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    d.rectangle([0, h - 34, w, h], fill=(20, 20, 20))
    d.text((12, h - 26), label, fill=(240, 240, 240))
    return img.filter(ImageFilter.GaussianBlur(1.6))


def chart_png():
    fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=150)
    days = np.arange(1, 11)
    ax.plot(days, [21.0, 21.4, 22.1, 23.0, 24.2, 24.9, 24.1, 23.2, 22.4, 21.8], marker="o", color="#2563eb")
    ax.set_xlabel("День наблюдения")
    ax.set_ylabel("Температура в салоне, °C")
    ax.set_title("Температура в салоне после ремонта")
    ax.grid(alpha=.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


def para(c, x, y, text, size=10.5, bold=False, width=88):
    c.setFont("DV-B" if bold else "DV", size)
    import textwrap
    for line in textwrap.wrap(text, width):
        c.drawString(x, y, line)
        y -= size * 1.5
    return y


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    c = canvas.Canvas(OUT, pagesize=A4)
    W, H = A4
    y = H - 60
    c.setFont("DV-B", 15)
    c.drawString(50, y, "АКТ ОСМОТРА СИСТЕМЫ ВЕНТИЛЯЦИИ № 18")
    y -= 26
    y = para(c, 50, y, "1. Общие сведения", 12, True)
    y = para(c, 50, y, "1.1 Осмотр выполнен комиссией депо после замены фильтроэлементов вентиляции вагона. Состояние корпуса, "
                      "креплений и воздуховодов зафиксировано на фотографиях.")
    y -= 6
    y = para(c, 50, y, "2. Результаты осмотра", 12, True)
    y = para(c, 50, y, "2.1 Следы загрязнения на входном патрубке до замены показаны на рисунке 1.")
    y -= 4
    img = fake_photo(3, "Фото 1 - входной патрубок до замены")
    c.drawImage(ImageReader(img), 70, y - 200, width=300, height=197)
    y -= 214
    para(c, 70, y, "Рисунок 1 - Входной патрубок до замены фильтроэлементов", 9.5)
    y -= 30
    y = para(c, 50, y, "2.2 После замены фильтроэлементов состояние патрубка соответствует требованиям. Крепления затянуты, "
                      "следов конденсата нет.")
    y -= 4
    img2 = fake_photo(11, "Фото 2 - патрубок после замены")
    c.drawImage(ImageReader(img2), 70, y - 200, width=300, height=197)
    y -= 214
    para(c, 70, y, "Рисунок 2 - Входной патрубок после замены", 9.5)
    c.showPage()

    y = H - 60
    y = para(c, 50, y, "2.3 Температура в салоне контролировалась в течение десяти дней, результаты приведены на рисунке 3.")
    y -= 4
    ch = chart_png()
    wpt = 440
    hpt = wpt * ch.height / ch.width
    c.drawImage(ImageReader(ch), 60, y - hpt, width=wpt, height=hpt)
    y -= hpt + 14
    para(c, 60, y, "Рисунок 3 - График температуры в салоне", 9.5)
    y -= 34
    y = para(c, 50, y, "3. Заключение", 12, True)
    y = para(c, 50, y, "3.1 Система вентиляции исправна, замечаний по результатам осмотра нет. Следующий осмотр проводится "
                      "при очередном техническом обслуживании ТО-3.")
    c.showPage()
    c.save()
    print("готово:", OUT)


if __name__ == "__main__":
    main()
