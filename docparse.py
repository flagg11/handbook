# разбор pdf: текст, таблицы, (необязательно) ocr сканов, координаты слов, нарезка на пункты.
# координаты слов в долях страницы (0..1) - по ним просмотрщик подсвечивает найденное
import os
import re
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np
import pymupdf
from PIL import Image

OCR_DPI = 300
MIN_TEXT_CHARS = 40  # меньше символов на странице - считаем сканом
MAX_CHUNK_CHARS = 1500  # длиннее режем по абзацам
OCR_ENABLED = True  # в настройках можно выключить - тогда сканы остаются картинками
MIN_CONF = 30  # слова ocr с меньшей уверенностью выкидываем (мусор с чертежей)
CELL_MIN_CONF = 10  # в ячейках текст короткий и чистый, порог мягче - иначе теряются артикулы
MAX_OCR_SIDE = 4200  # длинная сторона картинки для ocr, px (а3 в 300 dpi слишком тяжёлая)


@dataclass
class Word:
    page: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Block:
    kind: str  # text или table
    text: str = ""
    rows: list | None = None  # для таблиц - строки, в строке ячейки
    box: tuple | None = None  # для таблиц - рамка (x0, y0, x1, y1) в долях страницы
    fs: float | None = None  # кегль как доля ширины страницы, если известен
    lh: float | None = None  # межстрочный в кеглях (1.0 вплотную, 1.5 полуторный)


@dataclass
class Page:
    number: int
    source: str  # text, ocr, empty (скан без ocr) или drawing (чертёж, не читаем)
    skew: float = 0.0  # на сколько градусов выпрямили скан
    toc: bool = False  # страница содержания
    blocks: list = field(default_factory=list)
    words: list = field(default_factory=list)

    @property
    def text(self):
        parts = []
        for b in self.blocks:
            if b.kind == "text":
                parts.append(b.text)
            else:
                parts.append("\n".join(" | ".join(r) for r in b.rows))
        return "\n".join(parts)

    @property
    def tables(self):
        return sum(1 for b in self.blocks if b.kind == "table")


@dataclass
class Chunk:
    section: str | None
    parent: str | None
    title: str
    page: int
    page_to: int
    text: str
    source: str  # text или ocr
    kind: str = "text"  # text или table
    data: list | None = None  # строки таблицы
    geom: list | None = None  # для таблиц - куски по страницам [{page, box, r0, r1}], r0..r1 - строки data на странице


@dataclass
class ParseResult:
    pages: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ocr_pages(self):
        return sum(1 for p in self.pages if p.source == "ocr")

    @property
    def chars(self):
        return sum(len(p.text) for p in self.pages)

    @property
    def words(self):
        return [w for p in self.pages for w in p.words]


# tesseract
_tess = None  # (pytesseract, язык) или ("", причина почему нет)


def _find_tesseract():
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd and sys.platform == "win32":
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
            if os.path.exists(c):
                return c
    return cmd


def _init_tess():
    global _tess
    if _tess is not None:
        return _tess
    try:
        import pytesseract
        cmd = _find_tesseract()
        if not cmd:
            _tess = ("", "Tesseract не найден (установите его или задайте TESSERACT_CMD)")
            return _tess
        pytesseract.pytesseract.tesseract_cmd = cmd
        langs = set(pytesseract.get_languages(config=""))
        if "rus" not in langs:
            _tess = ("", "в Tesseract нет русского языка (rus.traineddata)")
            return _tess
        _tess = (pytesseract, "rus+eng" if "eng" in langs else "rus")
    except Exception as exc:
        _tess = ("", f"pytesseract: {exc}")
    return _tess


def ocr_status():
    mod, info = _init_tess()
    if not mod:
        return {"engine": None, "detail": info}
    return {"engine": "tesseract", "detail": info}


def _ocr_data(img, psm, min_conf=None):
    mod, lang = _init_tess()
    d = mod.image_to_data(img, lang=lang, config=f"--psm {psm}", output_type=mod.Output.DICT)
    lines, order, words = {}, [], []
    for i, txt in enumerate(d["text"]):
        txt = txt.strip()
        if not txt:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf < (MIN_CONF if min_conf is None else min_conf):
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(txt)
        words.append((txt, d["left"][i], d["top"][i], d["width"][i], d["height"][i]))
    out, last_par = [], None
    for key in order:
        if last_par is not None and key[:2] != last_par:
            out.append("")
        out.append(" ".join(lines[key]))
        last_par = key[:2]
    return out, words


# работа с картинкой скана
def rotate_image(gray, angle):
    if abs(angle) < 0.02:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def estimate_skew(gray):
    scale = 700 / max(gray.shape[1], 1)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = bw.shape

    def score(angle):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rot = cv2.warpAffine(bw, m, (w, h), flags=cv2.INTER_NEAREST)
        return float(np.var(rot.sum(axis=1, dtype=np.float64)))

    coarse = max(np.arange(-4.0, 4.01, 0.25), key=score)
    fine = max(np.arange(coarse - 0.25, coarse + 0.2501, 0.05), key=score)
    if score(fine) < score(0.0) * 1.03:
        return 0.0
    return float(fine)


def _line_masks(gray):
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = max(40, gray.shape[1] // 25)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    return horiz, vert


def remove_lines(gray):
    horiz, vert = _line_masks(gray)
    lines = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((3, 3), np.uint8))
    out = gray.copy()
    out[lines > 0] = 255
    return out


def _positions(profile, min_len, gap=4):
    idx = np.where(profile >= min_len)[0]
    if idx.size == 0:
        return []
    groups, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            groups.append((start, prev))
            start = i
        prev = i
    groups.append((start, prev))
    return [int(round((a + b) / 2)) for a, b in groups]


def detect_tables(gray):
    # таблицы по линиям -> [{'xs', 'ys', 'stamp'}] в пикселях; рамку листа пропускаем, штамп внизу справа помечаем
    horiz, vert = _line_masks(gray)
    h_img, w_img = gray.shape
    for r in np.where(horiz.sum(axis=1) / 255.0 > 0.7 * w_img)[0]:  # верх и низ рамки листа
        if r < 0.05 * h_img or r > 0.95 * h_img:
            horiz[max(0, r - 3):r + 4, :] = 0
    for c in np.where(vert.sum(axis=0) / 255.0 > 0.8 * h_img)[0]:  # боковые линии рамки
        vert[:, max(0, c - 3):c + 4] = 0
    mask = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    tables = []
    for i in range(1, n):
        x, y, w, h, _area = stats[i]
        if w < w_img * 0.15 or h < 30:
            continue
        sub_h = horiz[y:y + h, x:x + w] / 255.0
        sub_v = vert[y:y + h, x:x + w] / 255.0
        ys = _positions(sub_h.sum(axis=1), 0.6 * w)
        xs = _positions(sub_v.sum(axis=0), 0.6 * h)
        cells = (len(ys) - 1) * (len(xs) - 1)
        if len(ys) < 2 or len(xs) < 2 or cells < 2 or cells > 600:
            continue
        t = {"xs": [x + v for v in xs], "ys": [y + v for v in ys], "stamp": False}
        if t["ys"][0] >= 0.9 * h_img:
            t["stamp"] = True
        tables.append(t)
    tables.sort(key=lambda t: t["ys"][0])
    return tables


def _to_norm(left, top, width, height, W, H):
    return left / W, top / H, (left + width) / W, (top + height) / H


def _ocr_band(clean, y0, y1, page_no, W, H):
    band = clean[y0:y1, :]
    if band.shape[0] < 25 or band.min() > 200:
        return [], []
    lines, words = _ocr_data(Image.fromarray(band), psm=3)
    out_words = [Word(page_no, t, *_to_norm(l, y0 + tp, w, h, W, H)) for t, l, tp, w, h in words]
    return lines, out_words


def _ocr_cell(clean, x0, y0, x1, y1, page_no, W, H):
    inset = 3
    crop = clean[y0 + inset:y1 - inset, x0 + inset:x1 - inset]
    if crop.shape[0] < 8 or crop.shape[1] < 8:
        return "", []
    if (crop < 140).mean() < 0.0015:  # пустая ячейка
        return "", []
    scale = 2.0 if crop.shape[0] < 90 else 1.0
    img = Image.fromarray(crop)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    pad = 14
    padded = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 255)
    padded.paste(img, (pad, pad))
    lines, words = _ocr_data(padded, psm=6, min_conf=CELL_MIN_CONF)
    text = " ".join(l for l in lines if l).strip()
    if len(text) < 4 and (crop < 140).mean() > 0.004:
        # короткое значение («1,5 - 2,3») лучше читается одной строкой и покрупнее
        big = img.resize((img.width * 2, img.height * 2), Image.LANCZOS) if scale == 1.0 else \
            img.resize((int(img.width * 1.5), int(img.height * 1.5)), Image.LANCZOS)
        k = big.width / img.width
        padded2 = Image.new("L", (big.width + 2 * pad, big.height + 2 * pad), 255)
        padded2.paste(big, (pad, pad))
        lines2, words2 = _ocr_data(padded2, psm=7, min_conf=CELL_MIN_CONF)
        text2 = " ".join(l for l in lines2 if l).strip()
        if len(text2) > len(text):
            text, lines, words, padded, scale = text2, lines2, words2, padded2, scale * k
    ox, oy = x0 + inset, y0 + inset
    out = []
    for t, l, tp, w, h in words:
        left = ox + (l - pad) / scale
        top = oy + (tp - pad) / scale
        out.append(Word(page_no, t, *_to_norm(left, top, w / scale, h / scale, W, H)))
    return text, out


def _readable_word(w):
    w = w.strip(".,;:()[]«»\"'-–")
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", w)
    if len(letters) < 3 or len(letters) < 0.8 * len(w):
        return False
    return bool(re.search(r"[аеёиоуыэюяaeiouy]", w.lower())) and not (
        re.search(r"[А-Яа-яЁё]", w) and re.search(r"[A-Za-z]", w))


def _stamp_row(row):
    cells = [c for c in row if c]
    return bool(cells) and sum(1 for c in cells if _is_stamp_line(c)) >= 0.7 * len(cells)


def _looks_like_drawing(pg):
    toks = [w.text for w in pg.words if w.text.strip()]
    if len(toks) < 30:
        return False
    sane = sum(1 for t in toks if re.fullmatch(r"[\d.,±%+\-–/()]+", t) or _readable_word(t))
    return sane < 0.4 * len(toks)


def _scan_page(page, number, result):
    if not OCR_ENABLED:
        msg = "Распознавание сканов выключено в настройках"
        if msg not in result.warnings:
            result.warnings.append(msg)
        return Page(number, "empty")
    mod, info = _init_tess()
    if not mod:
        msg = f"Страницы-сканы не распознаны, показаны картинкой и в поиск не попадают: OCR недоступен ({info})"
        if msg not in result.warnings:
            result.warnings.append(msg)
        return Page(number, "empty")

    if max(page.rect.width, page.rect.height) > 900:
        # а3 и больше - чертёж, не читаем, показываем как есть
        return Page(number, "drawing")
    side_in = max(page.rect.width, page.rect.height) / 72.0
    dpi = max(150, min(OCR_DPI, int(MAX_OCR_SIDE / side_in)))
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    lo, hi = np.percentile(gray, (1, 99))
    if hi > lo:
        gray = np.clip((gray.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)

    angle = estimate_skew(gray)
    gray = rotate_image(gray, angle)
    H, W = gray.shape
    clean = remove_lines(gray)

    # вертикальные штампы лежат левее рамки - стираем поле слева
    _h, vert = _line_masks(gray)
    cols = np.where(vert.sum(axis=0) / 255.0 > 0.6 * H)[0]
    if cols.size and cols.min() < 0.25 * W:
        clean[:, :max(int(cols.min()) - 2, 0)] = 255

    tables = []
    for t in detect_tables(gray):
        if t["stamp"]:  # основная надпись - служебка, в текст не берём
            clean[max(t["ys"][0] - 4, 0):t["ys"][-1] + 4, max(t["xs"][0] - 4, 0):t["xs"][-1] + 4] = 255
        else:
            tables.append(t)

    pg = Page(number, "ocr", skew=angle)
    cursor = 0
    segments = []
    for t in tables:
        top = max(0, t["ys"][0] - 3)
        segments.append(("band", cursor, top))
        segments.append(("table", t, None))
        cursor = min(H, t["ys"][-1] + 3)
    segments.append(("band", cursor, H))

    for kind, a, b in segments:
        if kind == "band":
            lines, words = _ocr_band(clean, a, b, number, W, H)
            text = "\n".join(lines).strip()
            if text:
                pg.blocks.append(Block("text", text))
            pg.words.extend(words)
        else:
            xs, ys = a["xs"], a["ys"]
            jobs = [(ri, ci) for ri in range(len(ys) - 1) for ci in range(len(xs) - 1)]

            def run(job, xs=xs, ys=ys):
                ri, ci = job
                return _ocr_cell(clean, xs[ci], ys[ri], xs[ci + 1], ys[ri + 1], number, W, H)

            with ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1))) as pool:
                results = list(pool.map(run, jobs))
            ncols = len(xs) - 1
            rows = [[results[ri * ncols + ci][0] for ci in range(ncols)] for ri in range(len(ys) - 1)]
            cwords = [w for _t, ws in results for w in ws]
            rows = [r for r in rows if any(c for c in r)
                    and not _stamp_row(r)]
            filled = sum(1 for r in rows for c in r if c)
            total = max(1, len(rows) * ncols)
            # сетка чертежа или пустая форма (ячейки пустые/мусор) - не таблица
            if rows and filled / total >= 0.45 and sum(len(c) for r in rows for c in r) / max(filled, 1) >= 3:
                pg.words.extend(cwords)
                tbox = (round(xs[0] / W, 4), round(ys[0] / H, 4), round(xs[-1] / W, 4), round(ys[-1] / H, 4))
                pg.blocks.append(Block("table", rows=rows, box=tbox))
    if not pg.blocks:
        pg.source = "empty"
    elif _looks_like_drawing(pg):
        return Page(number, "drawing")
    return pg


# страницы с текстом
def _clean(text):
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # перенос слова
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _cell_text(raw_words, bbox):
    x0, y0, x1, y1 = bbox
    ws = [w for w in raw_words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    ws.sort(key=lambda w: (w[1] + w[3]) / 2)
    lines = []
    for w in ws:
        yc, h = (w[1] + w[3]) / 2, w[3] - w[1]
        if lines and abs(yc - lines[-1][0]) <= max(2.0, 0.6 * h):
            lines[-1][1].append(w)
        else:
            lines.append([yc, [w]])
    return " ".join(w[4] for _y, l in lines for w in sorted(l, key=lambda w: w[0])).strip()


def _table_rows(table, raw_words):
    rows = []
    try:
        for tr in table.rows:
            rows.append([_cell_text(raw_words, c) if c else "" for c in tr.cells])
    except Exception:
        rows = [[(c or "").strip() for c in r] for r in table.extract()]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    keep = [j for j in range(max(len(r) for r in rows)) if any(j < len(r) and r[j] for r in rows)]
    return [[(r[j] if j < len(r) else "") for j in keep] for r in rows]


def _wmedian(pairs):
    pairs = sorted((v, w) for w, v in pairs if w > 0)
    if not pairs:
        return None
    half = sum(w for _v, w in pairs) / 2
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def _text_page(page, number, continues=False):
    rect = page.rect
    W, H = rect.width, rect.height
    raw = page.get_text("words")

    def norm(x0, y0, x1, y1):
        r = pymupdf.Rect(x0, y0, x1, y1)
        if page.rotation:
            r = r * page.rotation_matrix
        return r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H

    pg = Page(number, "text")
    for w in raw:
        if w[4].strip():
            pg.words.append(Word(number, w[4], *norm(w[0], w[1], w[2], w[3])))

    # таблицы (рамку листа и штамп пропускаем)
    tables = []
    try:
        found = page.find_tables().tables
    except Exception:
        found = []
    for t in found:
        box = pymupdf.Rect(t.bbox)
        if box.width > 0.9 * W and box.height > 0.85 * H:  # рамка листа
            continue
        if box.y0 >= 0.92 * H:
            tables.append({"box": box, "rows": None})
            continue
        rows = [r for r in _table_rows(t, raw) if not _stamp_row(r)]
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            tables.append({"box": box, "rows": rows, "t": t})

    # таблица на след. странице часто без нижней линии - добираем хвост:
    # слова под таблицей до штампа раскладываем по границам столбцов
    footer_y = H * 0.9
    real = [t for t in tables if t["rows"]]
    if continues and real:
        low = max(real, key=lambda t: t["box"].y1)
        if low["box"].y1 < footer_y - 10:
            box = low["box"]
            tail = [w for w in raw if box.x0 - 4 <= (w[0] + w[2]) / 2 <= box.x1 + 4
                    and box.y1 + 1 < (w[1] + w[3]) / 2 < footer_y and w[4].strip()]
            cells_rows = [r for r in low["t"].rows if r.cells]
            if tail and cells_rows:
                widest = max(cells_rows, key=lambda r: sum(1 for c in r.cells if c))
                edges = sorted(c[0] for c in widest.cells if c)
                ncols = len(low["rows"][0])
                tail.sort(key=lambda w: (w[1] + w[3]) / 2)
                lines = []
                for w in tail:
                    yc, h = (w[1] + w[3]) / 2, w[3] - w[1]
                    if lines and abs(yc - lines[-1][0]) <= max(2.0, 0.6 * h):
                        lines[-1][1].append(w)
                    else:
                        lines.append([yc, [w]])
                for _y, ws in lines:
                    cells = [""] * ncols
                    for w in sorted(ws, key=lambda w: w[0]):
                        col = max(0, sum(1 for e in edges if e <= w[0] + 3) - 1)
                        col = min(col, ncols - 1)
                        cells[col] = (cells[col] + " " + w[4]).strip()
                    if not cells[0] and low["rows"]:
                        last = low["rows"][-1]
                        for j, c in enumerate(cells):
                            if c:
                                last[j] = (last[j] + " " + c).strip()
                    else:
                        low["rows"].append(cells)
                low["box"] = pymupdf.Rect(box.x0, box.y0, box.x1, min(footer_y, max(w[3] for w in tail) + 2))

    items = []  # (y, x, text|table, данные)
    spans_all = []  # (вес, кегль, центр) всех горизонтальных кусков
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        lines, sizes, tops = [], [], []
        for ln in b["lines"]:
            if abs(ln["dir"][0]) < 0.9:  # вертикальные надписи (штампы по краю) пропускаем
                continue
            txt = "".join(sp["text"] for sp in ln["spans"])
            if txt.strip():
                lines.append(txt)
                tops.append(ln["bbox"][1])
                for sp in ln["spans"]:
                    n = len(sp["text"].strip())
                    if n:
                        sizes.append((n, sp["size"]))
                        sb = sp["bbox"]
                        spans_all.append((n, sp["size"], ((sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2)))
        if not lines:
            continue
        x0, y0, x1, y1 = b["bbox"]
        c = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
        if any(c in t["box"] for t in tables):
            continue
        fs = None if page.rotation else _wmedian(sizes)
        lh = None
        if fs and len(tops) >= 2:
            steps = [b2 - a2 for a2, b2 in zip(tops, tops[1:]) if 0.6 * fs < b2 - a2 < 3 * fs]
            if steps:
                lh = sorted(steps)[len(steps) // 2] / fs
        items.append((y0, x0, "text", ("\n".join(lines), fs / W if fs else None, sum(n for n, _ in sizes), lh, len(lines))))
    for t in tables:
        if t["rows"]:
            tb, tfs = None, None
            if not page.rotation:
                tb = tuple(round(v, 4) for v in norm(t["box"].x0, t["box"].y0, t["box"].x1, t["box"].y1))
                inside = [(n, sz) for n, sz, c in spans_all if pymupdf.Point(*c) in t["box"]]
                m = _wmedian(inside)
                tfs = round(m / W, 5) if m else None
            items.append((t["box"].y0, t["box"].x0, "table", (t["rows"], tb, tfs)))
    items.sort(key=lambda i: (round(i[0] / 3), i[1]))

    buf, bufs = [], []

    def flush():
        txt = _clean("\n".join(buf))
        if txt:
            fs = _wmedian([(n, f) for f, n, _lh, _k in bufs if f])
            lh = _wmedian([(k, v) for _f, _n, v, k in bufs if v])
            pg.blocks.append(Block("text", txt, fs=round(fs, 5) if fs else None, lh=round(lh, 3) if lh else None))
        buf.clear()
        bufs.clear()

    for _y, _x, kind, payload in items:
        if kind == "text":
            buf.append(payload[0])
            bufs.append((payload[1], payload[2], payload[3], payload[4]))
        else:
            flush()
            pg.blocks.append(Block("table", rows=payload[0], box=payload[1], fs=payload[2]))
    flush()
    return pg


def _extract_pages(path, result, ocr=True):
    doc = pymupdf.open(path)
    try:
        for index, page in enumerate(doc, start=1):
            nxt = doc[index].get_text()[:600].lower() if index < len(doc) else ""
            pg = _text_page(page, index, continues="продолжение таблицы" in nxt)
            if len(pg.text) >= MIN_TEXT_CHARS:
                result.pages.append(pg)
                continue
            has_images = bool(page.get_images(full=True)) or not pg.text
            if ocr and has_images:
                result.pages.append(_scan_page(page, index, result))
            else:
                if not pg.blocks:
                    pg.source = "empty"
                result.pages.append(pg)
    finally:
        doc.close()


# мусор: штампы, колонтитулы, номера листов, содержание
STAMP_WORDS = {"изм", "лист", "листов", "докум", "подп", "дата", "и", "инв", "подл", "дубл", "взам", "n", "no",
               "формат", "а2", "а3", "а4", "подпись", "доким", "дибл", "н", "т", "подн", "инв", "ne", "разраб", "провер", "контр", "утв", "лит", "масса", "масштаб"}
NOT_NOISE = ("таблица", "продолжение", "рисунок", "приложение", "табл")


def _is_stamp_line(line):
    toks = re.findall(r"[а-яёa-z]+", line.lower().replace("№", " "))
    return bool(toks) and len(line) <= 70 and all(t in STAMP_WORDS for t in toks)


def _norm_line(line):
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def _strip_noise(pages):
    texty = [p for p in pages if p.blocks]
    counts = Counter()
    for p in texty:
        counts.update({_norm_line(l) for b in p.blocks if b.kind == "text"
                       for l in b.text.split("\n") if l.strip() and len(l) <= 90})
    threshold = max(4, int(0.3 * len(texty)) + 1) if len(texty) >= 6 else 10 ** 9
    repeated = {k for k, v in counts.items() if v >= threshold and re.search(r"[a-zа-я]", k)
                and not k.startswith(NOT_NOISE) and not re.match(r"^#(\.#)*\s", k)}
    for p in pages:
        text_blocks = [b for b in p.blocks if b.kind == "text"]
        for b in text_blocks:
            b.text = "\n".join(l for l in b.text.split("\n")
                               if not (l.strip() and (_is_stamp_line(l) or _norm_line(l) in repeated)))
        if text_blocks:  # номер листа остаётся последней строкой
            lines = [l for l in text_blocks[-1].text.split("\n")]
            while lines and (not lines[-1].strip() or re.fullmatch(r"\d{1,3}[а-я]?", lines[-1].strip())):
                lines.pop()
            text_blocks[-1].text = "\n".join(lines)
        p.blocks = [b for b in p.blocks if b.kind == "table" or b.text.strip()]


LEADER = re.compile(r"(?:\.{3,}|…{2,}|(?:\.\s){4,})")


def _mark_toc(pages):
    for pg in pages:
        lines = [l.strip() for b in pg.blocks if b.kind == "text" for l in b.text.split("\n") if l.strip()]
        if not lines:
            continue
        head = " ".join(lines[:4]).lower()
        leaders = sum(1 for l in lines if LEADER.search(l))
        if (re.search(r"\b(содержание|оглавление)\b", head) and leaders >= 3) or leaders >= 8:
            entries = []
            for l in lines:
                t = LEADER.split(l)[0].strip(" .…") if LEADER.search(l) else l
                t = re.sub(r"\s+\d{1,3}[а-яa-z]?$", "", t).strip()  # номер страницы без точек
                if re.search(r"[A-Za-zА-Яа-я]", t) and not _is_stamp_line(t):
                    entries.append(t)
            pg.toc = True
            pg.blocks = [Block("text", "\n".join(entries))]


# нарезка на пункты
HEAD_MULTI = re.compile(r"^(\d{1,2}(?:[.,]\d{1,3}){1,5})[.,]?\s+(\S.{1,2500})$")
HEAD_SINGLE = re.compile(r"^(\d{1,2})\.\s+([A-ZА-ЯЁ].{1,200})$")
HEAD_NODOT = re.compile(r"^(\d{1,2})\s+([A-ZА-ЯЁ].{2,100})$")
APPENDIX = re.compile(r"^приложение\s+([А-ЯA-Z6])\b[\s.:\-–]*(.*)$", re.I)
FIGURE_APP = re.compile(r"^рисунок\s+([А-ЯA-Z6])[.,]\s*[\dТTtlIi]", re.I)
CAPTION = re.compile(r"^(?:таблица|табл\.)\s*(\d*)", re.I)
CONT = re.compile(r"^продолжение\s+таблицы\s*(\d+)", re.I)


def _match_heading(line, toc_top=()):
    if " | " in line:
        return None
    m = HEAD_MULTI.match(line)
    if m:
        return m.group(1).replace(",", "."), m.group(2)
    m = HEAD_SINGLE.match(line)
    if m and not line.rstrip().endswith((";", ",")):
        return m.group(1), m.group(2)
    # «1 ТЕХНИЧЕСКОЕ ОПИСАНИЕ» без точки берём, только если такой раздел есть в содержании
    m = HEAD_NODOT.match(line)
    if m and m.group(1) in toc_top and not line.rstrip().endswith((".", ";", ",", ":")):
        return m.group(1), m.group(2)
    return None


def _short(text, limit=110):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _split_long(text):
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n+", text):
        if cur and len(cur) + len(para) > MAX_CHUNK_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _text_segments(pgs, fss):
    # строки фрагмента по страницам: [{page, r0, r1, fs}]
    segs, start = [], 0
    for i in range(1, len(pgs) + 1):
        if i == len(pgs) or pgs[i] != pgs[start]:
            fs = _wmedian([(1, f[0]) for f in fss[start:i] if f and f[0]])
            lh = _wmedian([(1, f[1]) for f in fss[start:i] if f and f[1]])
            segs.append({"page": pgs[start], "r0": start, "r1": i, "fs": round(fs, 5) if fs else None,
                         "lh": round(lh, 3) if lh else None})
            start = i
    return segs


def build_chunks(pages):
    raw = []  # готовые фрагменты по порядку
    titles = {}  # номер пункта -> заголовок
    state = {"cur": None, "tables": 0, "last_table": {}}

    toc_nums = set()
    for pg in pages:
        if pg.toc:
            for b in pg.blocks:
                for l in b.text.split("\n"):
                    m = re.match(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+\S", l.strip())
                    if m:
                        toc_nums.add(m.group(1))
    toc_top = {n for n in toc_nums if "." not in n}

    def parent_of(section):
        if not section or not section[0].isdigit():
            return None
        parts = section.split(".")
        for n in range(len(parts) - 1, 0, -1):
            key = ".".join(parts[:n])
            if key in titles:
                return f"{key} {titles[key]}"
        return None

    def flush():
        cur = state["cur"]
        state["cur"] = None
        if not cur or not cur["lines"]:
            return
        text = "\n".join(cur["lines"])
        idx = 0
        for part in _split_long(text):
            n = len([l for l in part.split("\n") if l.strip()])
            ck = Chunk(cur["section"], parent_of(cur["section"]), cur["title"], cur["page"],
                       cur["page_to"], part, cur["source"])
            ck.geom = _text_segments(cur["pg"][idx:idx + n], cur["fs"][idx:idx + n]) if len(cur["pg"]) == len(cur["lines"]) else None
            idx += n
            raw.append(ck)

    for pg in pages:
        source = "ocr" if pg.source == "ocr" else "text"
        if pg.toc:
            flush()
            raw.append(Chunk(None, None, "Содержание", pg.number, pg.number, "\n".join(b.text for b in pg.blocks), source))
            continue
        for block in pg.blocks:
            if block.kind == "table":
                cur = state["cur"]
                caption, cont = None, None
                if cur and cur["lines"]:
                    m = CONT.match(cur["lines"][-1])
                    if m:
                        cont = m.group(1)
                        cur["lines"].pop(); cur["pg"].pop(); cur["fs"].pop()  # «Продолжение таблицы N» - не заголовок
                    elif CAPTION.match(cur["lines"][-1]):
                        caption = _short(cur["lines"].pop()); cur["pg"].pop(); cur["fs"].pop()  # подпись уходит в заголовок таблицы
                section = cur["section"] if cur else None
                snapshot = dict(cur) if cur else None
                flush()
                rows = [list(r) for r in block.rows]
                prev = state["last_table"].get(cont) if cont else None
                if prev is not None and prev.data and len(rows[0]) == len(prev.data[0]):
                    before = len(prev.data)
                    hdr = rows[0] == prev.data[0]  # шапка повторилась на новой странице
                    prev.data.extend(rows[1:] if hdr else rows)
                    prev.text = "\n".join(" | ".join(r) for r in prev.data)
                    prev.page_to = pg.number
                    if prev.geom is not None and block.box:
                        prev.geom.append({"page": pg.number, "box": list(block.box), "r0": before, "r1": len(prev.data), "hdr": hdr, "fs": block.fs})
                else:
                    state["tables"] += 1
                    ck = Chunk(section, parent_of(section), caption or f"Таблица {state['tables']}",
                               pg.number, pg.number, "\n".join(" | ".join(r) for r in rows), source,
                               kind="table", data=rows)
                    if block.box:
                        ck.geom = [{"page": pg.number, "box": list(block.box), "r0": 0, "r1": len(rows), "fs": block.fs}]
                    raw.append(ck)
                    num = CAPTION.match(caption).group(1) if caption and CAPTION.match(caption) else ""
                    if num:
                        state["last_table"][num] = ck
                if snapshot:  # текст после таблицы - тот же пункт
                    state["cur"] = {"section": snapshot["section"], "title": snapshot["title"], "page": pg.number,
                                    "page_to": pg.number, "source": source, "lines": [], "pg": [], "fs": []}
                continue

            src_lines = [l.strip() for l in block.text.split("\n") if l.strip()]
            merged = []
            for l in src_lines:  # «2.5» на одной строке, название на следующей
                if merged and re.fullmatch(r"\d{1,2}(?:\.\d{1,3}){1,4}\.?", merged[-1]):
                    merged[-1] = merged[-1] + " " + l
                else:
                    merged.append(l)
            for line in merged:
                ap = APPENDIX.match(line)
                fa = FIGURE_APP.match(line) if source == "ocr" else None
                if fa and not ap and (state["cur"] or {}).get("section") != "Прил. " + fa.group(1).upper().replace("6", "Б"):
                    ap = fa  # рисунок «А.1» без заголовка приложения - значит приложение началось
                if ap and len(line) < 90 and not line.rstrip().endswith((",", ";")):
                    flush()
                    section = f"Прил. {ap.group(1).upper().replace('6', 'Б')}"
                    title = _short(line)
                    titles[section] = title
                    state["cur"] = {"section": section, "title": title, "page": pg.number,
                                    "page_to": pg.number, "source": source, "lines": [line],
                                    "pg": [pg.number], "fs": [(block.fs, block.lh)]}
                    continue
                head = _match_heading(line, toc_top)
                if head and "." not in head[0] and not re.match(r"^\d{1,2}\.", line):
                    # раздел без точки («2 ИНСТРУКЦИЯ...») - только следующий по порядку
                    if int(head[0]) != state.get("top", 0) + 1:
                        head = None
                if head:
                    if "." not in head[0]:
                        state["top"] = int(head[0])
                    flush()
                    num, rest = head
                    titles[num] = _short(rest)
                    state["cur"] = {"section": num, "title": _short(rest), "page": pg.number,
                                    "page_to": pg.number, "source": source, "lines": [rest],
                                    "pg": [pg.number], "fs": [(block.fs, block.lh)]}
                else:
                    if state["cur"] is None:
                        state["cur"] = {"section": None, "title": _short(line), "page": pg.number,
                                        "page_to": pg.number, "source": source, "lines": [], "pg": [], "fs": []}
                    state["cur"]["lines"].append(line)
                    state["cur"]["pg"].append(pg.number)
                    state["cur"]["fs"].append((block.fs, block.lh))
                    state["cur"]["page_to"] = pg.number
                    if source == "ocr":
                        state["cur"]["source"] = "ocr"
    flush()
    return raw


def parse_pdf(path, ocr=True):
    result = ParseResult()
    _extract_pages(path, result, ocr=ocr)
    _strip_noise(result.pages)
    _mark_toc(result.pages)
    result.chunks = build_chunks(result.pages)
    if not result.chunks:
        result.warnings.append("В документе не найдено текста")
    return result


# картинки страниц
def render_page_png(path, page_no, width=1100, skew=0.0, ocr_page=False):
    import io
    doc = pymupdf.open(path)
    try:
        page = doc[page_no - 1]
        zoom = width / page.rect.width
        if ocr_page:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
            gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
            img = Image.fromarray(rotate_image(gray, skew))
        else:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=False)
        return buf.getvalue(), img.width, img.height
    finally:
        doc.close()


# рисунки из документа
def _merge_rects(rects, gap=8):
    rects = [pymupdf.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        for r in rects:
            for o in out:
                if (o + (-gap, -gap, gap, gap)).intersects(r):
                    o |= r
                    changed = True
                    break
            else:
                out.append(pymupdf.Rect(r))
        rects = out
    return rects


def _page_figure_rects(page):
    W, H = page.rect.width, page.rect.height
    rects = []
    for d in page.get_image_info():
        r = pymupdf.Rect(d["bbox"]) & page.rect
        if r.width >= 40 and r.height >= 30 and r.get_area() < 0.85 * W * H:
            rects.append(r)
    try:
        tables = [pymupdf.Rect(t.bbox) for t in page.find_tables().tables]
    except Exception:
        tables = []
    keep = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 0.85 * W or r.height > 0.85 * H:  # линии рамки листа
            continue
        if r.y0 >= 0.92 * H or r.x1 <= 0.1 * W or r.x0 >= 0.95 * W:  # штамп, поля
            continue
        c = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if any(c in (t + (-3, -3, 3, 3)) for t in tables):
            continue
        keep.append(d)
    if keep:
        try:
            for r in page.cluster_drawings(drawings=keep):
                if not (r.width >= 50 and r.height >= 40 and r.get_area() < 0.8 * W * H):
                    continue
                inside = [d for d in keep if d["rect"].intersects(r)]
                # сетка из тонких линий без кривых и заливки - это форма или таблица, не рисунок
                thin = sum(1 for d in inside if min(d["rect"].width, d["rect"].height) < 2.5
                           and all(it[0] in ("l", "re") for it in d["items"]))
                grid = bool(inside) and thin >= 0.9 * len(inside)
                if not grid:
                    rects.append(r)
        except Exception:
            pass
    out = []
    for r in _merge_rects(rects):
        r = (r + (-4, -4, 4, 4)) & page.rect
        if r.width >= 50 and r.height >= 40:
            out.append(r)
    out.sort(key=lambda r: (r.y0, r.x0))
    return out


def extract_figures(path, outdir, sources=None):
    # картинки документа в png. сканы а4 с текстом не режем, а3 и страницы без текста берём целиком
    sources = sources or {}
    os.makedirs(outdir, exist_ok=True)
    result = []
    doc = pymupdf.open(path)
    try:
        for number, page in enumerate(doc, start=1):
            W, H = page.rect.width, page.rect.height
            src = sources.get(number, "text")
            if src == "drawing":
                rects = [page.rect]
            elif src == "ocr":
                rects = [page.rect] if max(W, H) > 900 else []
            elif src == "empty":
                has = bool(page.get_images()) or bool(page.get_drawings())
                rects = [page.rect] if has else []
            elif page.rotation:
                rects = []
            else:
                rects = _page_figure_rects(page)
                # страница почти вся в растре - это скан с текстовым слоем, отдельные картинки не нужны
                covered = sum(pymupdf.Rect(d["bbox"]).get_area() for d in page.get_image_info())
                if covered > 0.5 * W * H:
                    rects = []
            for k, r in enumerate(rects[:6]):
                dpi = max(72, min(160, int(1500 / max(r.width, 1) * 72)))
                pix = page.get_pixmap(dpi=dpi, clip=r)
                name = f"{number}_{k}.png"
                pix.save(os.path.join(outdir, name))
                result.append({"id": f"{number}_{k}", "page": number, "file": name,
                               "box": [round(r.x0 / W, 4), round(r.y0 / H, 4), round(r.x1 / W, 4), round(r.y1 / H, 4)],
                               "w": pix.width, "h": pix.height})
    finally:
        doc.close()
    return result


def page_sizes(path):
    doc = pymupdf.open(path)
    try:
        return [[round(p.rect.width, 1), round(p.rect.height, 1)] for p in doc]
    finally:
        doc.close()


if __name__ == "__main__":
    import json
    res = parse_pdf(sys.argv[1])
    print(json.dumps({"ocr": ocr_status(), "pages": len(res.pages), "ocr_pages": res.ocr_pages,
                      "skew": [round(p.skew, 2) for p in res.pages], "words": len(res.words),
                      "warnings": res.warnings}, ensure_ascii=False))
    for c in res.chunks:
        print(f"[{c.section or '-'}] стр.{c.page} ({c.source}, {c.kind}) {c.title}")
        if c.kind == "table":
            for r in c.data:
                print("      ", r)
