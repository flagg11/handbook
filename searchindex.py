# папки, документы, страницы со словами, фрагменты и полнотекстовый поиск.
# в fts лежат основы слов (snowball), поэтому «замена фильтроэлементов» найдёт и «заменить фильтроэлемент».
# исходный текст хранится отдельно - для сниппетов
import html
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache

import snowballstemmer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HANDBOOK_DB", os.path.join(BASE_DIR, "data", "index.sqlite3"))
SCHEMA_VERSION = 4
INBOX = "inbox"

_ru = snowballstemmer.stemmer("russian")
_en = snowballstemmer.stemmer("english")
_lock = threading.Lock()

WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
CYR_RE = re.compile(r"[а-яё]")
SECTION_RE = re.compile(r"^\d{1,2}(?:\.\d{1,3})+\.?$")
STOP = {"и", "в", "во", "на", "с", "со", "по", "при", "для", "из", "к", "о", "об", "от", "до",
        "не", "за", "как", "что", "или", "а", "но", "у", "же", "бы", "то", "это"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders(
    id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL, system INTEGER DEFAULT 0,
    hints TEXT DEFAULT '', created_at TEXT, sort INTEGER DEFAULT 0, rel TEXT
);
CREATE TABLE IF NOT EXISTS docs(
    id TEXT PRIMARY KEY, folder TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
    size_bytes INTEGER, uploaded_at TEXT, author TEXT, date_label TEXT,
    status TEXT NOT NULL DEFAULT 'processing',
    pages INTEGER DEFAULT 0, ocr_pages INTEGER DEFAULT 0, tables INTEGER DEFAULT 0, chunks INTEGER DEFAULT 0,
    chars INTEGER DEFAULT 0, warnings TEXT DEFAULT '', error TEXT DEFAULT '', sample INTEGER DEFAULT 0,
    want_sort INTEGER DEFAULT 0, auto INTEGER DEFAULT 0, confidence REAL DEFAULT 0,
    reason TEXT DEFAULT '', needs_review INTEGER DEFAULT 0, rel TEXT, mtime REAL
);
CREATE TABLE IF NOT EXISTS pages(
    doc_id TEXT NOT NULL, page INTEGER NOT NULL, source TEXT, skew REAL DEFAULT 0, words TEXT,
    PRIMARY KEY(doc_id, page)
);
CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, seq INTEGER,
    section TEXT, parent TEXT, title TEXT, page INTEGER, page_to INTEGER, source TEXT, kind TEXT DEFAULT 'text',
    text TEXT, data TEXT, edited INTEGER DEFAULT 0, geom TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(body, title, tokenize='unicode61 remove_diacritics 2');
"""


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    if ver not in (0, SCHEMA_VERSION):  # старая схема - пересоздаём
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(DB_PATH + suffix)
            except OSError:
                pass
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        cols = [r[1] for r in con.execute("PRAGMA table_info(chunks)")]
        if "geom" not in cols:  # база от старой версии (без геометрии таблиц)
            con.execute("ALTER TABLE chunks ADD COLUMN geom TEXT")
        for table, col, decl in (("folders", "rel", "TEXT"), ("docs", "rel", "TEXT"), ("docs", "mtime", "REAL")):
            if col not in [r[1] for r in con.execute(f"PRAGMA table_info({table})")]:  # база до режима с подключённой папкой
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


# нормализация
@lru_cache(maxsize=200000)
def stem(word):
    w = word.lower().replace("ё", "е")
    if CYR_RE.search(w):
        return _ru.stemWord(w)
    if w.isalpha():
        return _en.stemWord(w)
    return w


def stems(text):
    return [stem(w) for w in WORD_RE.findall(text)]


def _index_text(text):
    return " ".join(stems(text))


def matches(st, q):
    return st.startswith(q) if len(q) >= 3 else st == q


def meta_claim(key):
    with connect() as con:
        cur = con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (key, str(time.time())))
        return cur.rowcount == 1


# папки
def seed_folders(tree):
    with connect() as con:
        for order, (fid, parent, name, hints, system) in enumerate(tree):
            con.execute(
                "INSERT OR IGNORE INTO folders(id, parent_id, name, system, hints, created_at, sort) VALUES (?,?,?,?,?,?,?)",
                (fid, parent, name, 1 if system else 0, json.dumps(hints, ensure_ascii=False) if hints else "",
                 time.strftime("%Y-%m-%d %H:%M:%S"), order))


def _folder_rows(con):
    return [dict(r) for r in con.execute("SELECT * FROM folders ORDER BY sort, name COLLATE NOCASE")]


def list_folders():
    # docs - файлы прямо в папке, total - вместе с вложенными
    with connect() as con:
        rows = _folder_rows(con)
        direct = {r[0]: r[1] for r in con.execute("SELECT folder, COUNT(*) FROM docs GROUP BY folder")}
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])

    def total(fid):
        return direct.get(fid, 0) + sum(total(c) for c in children.get(fid, []))

    for r in rows:
        r["docs"] = direct.get(r["id"], 0)
        r["total"] = total(r["id"])
        r["hints"] = json.loads(r["hints"]) if r["hints"] else None
    return rows


def get_folder(fid):
    with connect() as con:
        row = con.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
        return dict(row) if row else None


def folder_path(fid, rows=None):
    rows = rows or {r["id"]: r for r in list_folders()}
    parts = []
    while fid and fid in rows:
        parts.append(rows[fid]["name"])
        fid = rows[fid]["parent_id"]
    return " / ".join(reversed(parts))


def descendants(fid, rows=None):
    rows = rows or list_folders()
    out, stack = [], [fid]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(r["id"] for r in rows if r["parent_id"] == cur)
    return out


def _clean_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise ValueError("Введите название папки")
    if len(name) > 80:
        raise ValueError("Название слишком длинное (до 80 символов)")
    if re.search(r'[\\/:*?"<>|]', name):
        raise ValueError('В названии нельзя использовать символы \\ / : * ? " < > |')
    return name


def _check_unique(con, parent, name, ignore_id=None):
    for r in con.execute("SELECT id, name FROM folders WHERE parent_id IS ?", (parent,)):
        if r["id"] != ignore_id and r["name"].lower() == name.lower():
            raise ValueError("В этой папке уже есть папка с таким названием")


def create_folder(name, parent_id=None):
    name = _clean_name(name)
    parent_id = parent_id or None
    with connect() as con:
        if parent_id and not con.execute("SELECT 1 FROM folders WHERE id=?", (parent_id,)).fetchone():
            raise ValueError("Родительская папка не найдена")
        _check_unique(con, parent_id, name)
        fid = "f-" + uuid.uuid4().hex[:8]
        order = (con.execute("SELECT COALESCE(MAX(sort), 0) FROM folders").fetchone()[0]) + 1
        con.execute("INSERT INTO folders(id, parent_id, name, system, hints, created_at, sort) VALUES (?,?,?,?,?,?,?)",
                    (fid, parent_id, name, 0, "", time.strftime("%Y-%m-%d %H:%M:%S"), order))
    return get_folder(fid)


def update_folder(fid, name=None, parent_id="__keep__"):
    with connect() as con:
        row = con.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
        if not row:
            raise LookupError("Папка не найдена")
        if row["system"]:
            raise ValueError("Системную папку нельзя изменить")
        new_name = _clean_name(name) if name is not None else row["name"]
        new_parent = row["parent_id"] if parent_id == "__keep__" else (parent_id or None)
        if new_parent != row["parent_id"]:
            if new_parent:
                if not con.execute("SELECT 1 FROM folders WHERE id=?", (new_parent,)).fetchone():
                    raise ValueError("Папка назначения не найдена")
                if new_parent in descendants(fid, _folder_rows(con)):
                    raise ValueError("Нельзя переместить папку саму в себя")
        _check_unique(con, new_parent, new_name, ignore_id=fid)
        con.execute("UPDATE folders SET name=?, parent_id=? WHERE id=?", (new_name, new_parent, fid))
    return get_folder(fid)


def delete_folder(fid):
    with _lock, connect() as con:
        row = con.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
        if not row:
            raise LookupError("Папка не найдена")
        if row["system"]:
            raise ValueError("Системную папку нельзя удалить")
        ids = descendants(fid, _folder_rows(con))
        marks = ",".join("?" * len(ids))
        docs = [dict(r) for r in con.execute(f"SELECT * FROM docs WHERE folder IN ({marks})", ids)]
        for d in docs:
            _drop_doc_rows(con, d["id"])
        con.execute(f"DELETE FROM folders WHERE id IN ({marks})", ids)
    return docs


# документы
def add_document(doc_id, folder, name, path, size_bytes, author, date_label=None, sample=False, want_sort=False,
                 rel=None, mtime=None):
    with connect() as con:
        con.execute(
            "INSERT INTO docs(id, folder, name, path, size_bytes, uploaded_at, author, date_label, status, sample, want_sort, rel, mtime) "
            "VALUES (?,?,?,?,?,?,?,?, 'processing', ?, ?, ?, ?)",
            (doc_id, folder, name, path, size_bytes, time.strftime("%Y-%m-%d %H:%M:%S"), author,
             date_label or time.strftime("%d.%m.%Y", time.localtime(mtime)) if mtime else date_label or time.strftime("%d.%m.%Y"),
             1 if sample else 0, 1 if want_sort else 0, rel, mtime),
        )


def get_document(doc_id):
    with connect() as con:
        row = con.execute("SELECT * FROM docs WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None


def list_documents():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM docs ORDER BY uploaded_at, rowid")]


def pending_documents():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM docs WHERE status IN ('processing','queued')")]


def restart_processing(doc_id):
    with connect() as con:
        con.execute("UPDATE docs SET status='processing', error='', want_sort=0 WHERE id=?", (doc_id,))


def move_document(doc_id, folder_id, auto=False, confidence=0.0, reason="", needs_review=False):
    with connect() as con:
        if not con.execute("SELECT 1 FROM folders WHERE id=?", (folder_id,)).fetchone():
            raise ValueError("Папка назначения не найдена")
        if not con.execute("SELECT 1 FROM docs WHERE id=?", (doc_id,)).fetchone():
            raise LookupError("Файл не найден")
        con.execute("UPDATE docs SET folder=?, auto=?, confidence=?, reason=?, needs_review=? WHERE id=?",
                    (folder_id, 1 if auto else 0, confidence, reason, 1 if needs_review else 0, doc_id))


def rename_document(doc_id, name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name or re.search(r'[\\/:*?"<>|]', name):
        raise ValueError("Недопустимое имя файла")
    with connect() as con:
        row = con.execute("SELECT name FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not name.lower().endswith((".pdf", ".docx")):
            old = os.path.splitext(row["name"] if row else "")[1].lower()
            name += old if old in (".pdf", ".docx") else ".pdf"
        con.execute("UPDATE docs SET name=? WHERE id=?", (name, doc_id))


def index_document(doc_id, pages, chunks):
    with _lock, connect() as con:
        _drop_chunks(con, doc_id)
        con.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
        for pg in pages:
            words = [[w.text, round(w.x0, 4), round(w.y0, 4), round(w.x1, 4), round(w.y1, 4)] for w in pg.words]
            con.execute("INSERT INTO pages(doc_id, page, source, skew, words) VALUES (?,?,?,?,?)",
                        (doc_id, pg.number, pg.source, pg.skew, json.dumps(words, ensure_ascii=False)))
        for seq, c in enumerate(chunks):
            cur = con.execute(
                "INSERT INTO chunks(doc_id, seq, section, parent, title, page, page_to, source, kind, text, data, geom) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, seq, c.section, c.parent, c.title, c.page, c.page_to, c.source, c.kind, c.text,
                 json.dumps(c.data, ensure_ascii=False) if c.data else None,
                 json.dumps(c.geom, ensure_ascii=False) if c.geom else None))
            # номер пункта кладём в индекс, чтобы «2.5.2.2» тоже находилось
            title_idx = _index_text(f"{c.section or ''} {c.title}")
            con.execute("INSERT INTO chunks_fts(rowid, body, title) VALUES (?,?,?)",
                        (cur.lastrowid, _index_text(c.text), title_idx))


def finish_document(doc_id, pages, ocr_pages, tables, chunks, chars, warnings):
    with connect() as con:
        con.execute(
            "UPDATE docs SET status='indexed', pages=?, ocr_pages=?, tables=?, chunks=?, chars=?, warnings=?, error='' WHERE id=?",
            (pages, ocr_pages, tables, chunks, chars, "\n".join(warnings), doc_id))


def fail_document(doc_id, error):
    with connect() as con:
        con.execute("UPDATE docs SET status='error', error=? WHERE id=?", (str(error)[:500], doc_id))


def _drop_chunks(con, doc_id):
    ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        con.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", part)
    con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))


def _drop_doc_rows(con, doc_id):
    _drop_chunks(con, doc_id)
    con.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
    con.execute("DELETE FROM docs WHERE id=?", (doc_id,))


def delete_document(doc_id):
    with _lock, connect() as con:
        _drop_doc_rows(con, doc_id)


def document_chunks(doc_id):
    with connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, seq, section, parent, title, page, page_to, source, kind, text, data, edited, geom FROM chunks "
            "WHERE doc_id=? ORDER BY seq", (doc_id,))]
    for r in rows:
        r["data"] = json.loads(r["data"]) if r["data"] else None
        r["geom"] = json.loads(r["geom"]) if r["geom"] else None
    return rows


def _rescale_geom(raw, n_rows):
    # после правки строк в таблице может стать больше/меньше - пересчитываем куски по страницам
    if not raw:
        return raw
    try:
        segs = json.loads(raw)
    except ValueError:
        return raw
    total = max((g["r1"] for g in segs), default=0)
    if not total or total == n_rows:
        return raw
    prev = 0
    for i, g in enumerate(segs):
        end = n_rows if i == len(segs) - 1 else max(prev, min(n_rows, round(g["r1"] * n_rows / total)))
        g["r0"], g["r1"] = prev, end
        prev = end
    return json.dumps(segs, ensure_ascii=False)


def update_chunk(chunk_id, text=None, rows=None):
    with _lock, connect() as con:
        row = con.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        if not row:
            raise LookupError("Фрагмент не найден")
        if row["kind"] == "table":
            if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
                raise ValueError("Ожидается таблица: список строк")
            rows = [[re.sub(r"[ \t]+", " ", str(c or "")).strip() for c in r] for r in rows]
            if not rows or len(rows) > 400 or max((len(r) for r in rows), default=0) > 60:
                raise ValueError("Таблица должна содержать от 1 до 400 строк и до 60 столбцов")
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            new_text = "\n".join(" | ".join(c.replace("\n", " ") for c in r) for r in rows)
            data = json.dumps(rows, ensure_ascii=False)
            geom = _rescale_geom(row["geom"], len(rows))
        else:
            if text is None:
                raise ValueError("Ожидается текст")
            new_text = "\n".join(l.rstrip() for l in str(text).replace("\r", "").split("\n")).strip()
            if not new_text:
                raise ValueError("Текст не может быть пустым")
            data = None
            geom = _rescale_geom(row["geom"], len([l for l in new_text.split("\n") if l.strip()]))
        if len(new_text) > 20000:
            raise ValueError("Слишком длинный текст")
        con.execute("UPDATE chunks SET text=?, data=?, geom=?, edited=1 WHERE id=?", (new_text, data, geom, chunk_id))
        title_idx = _index_text(f"{row['section'] or ''} {row['title']}")
        con.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
        con.execute("INSERT INTO chunks_fts(rowid, body, title) VALUES (?,?,?)",
                    (chunk_id, _index_text(new_text), title_idx))
        return row["doc_id"]


def document_text(doc_id):
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT title, text, kind FROM chunks WHERE doc_id=? ORDER BY seq", (doc_id,))]


def page_info(doc_id, page):
    with connect() as con:
        row = con.execute("SELECT source, skew FROM pages WHERE doc_id=? AND page=?", (doc_id, page)).fetchone()
        return dict(row) if row else None


def pages_meta(doc_id):
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT page, source FROM pages WHERE doc_id=? ORDER BY page", (doc_id,))]


def _norm_tok(t):
    return re.sub(r"[^0-9a-zа-я]", "", t.lower().replace("ё", "е"))


def chunk_anchors(doc_id):
    with connect() as con:
        pages = {r["page"]: json.loads(r["words"]) for r in
                 con.execute("SELECT page, words FROM pages WHERE doc_id=?", (doc_id,))}
        chunks = [dict(r) for r in con.execute(
            "SELECT id, page, page_to, kind, text FROM chunks WHERE doc_id=? ORDER BY seq", (doc_id,))]
    norm_pages = {p: [_norm_tok(w[0]) for w in ws] for p, ws in pages.items()}
    out, cursor_page, cursor = {}, None, 0
    for c in chunks:
        ws, toks = pages.get(c["page"]), norm_pages.get(c["page"])
        if not ws:
            continue
        first = [t for t in (_norm_tok(x) for x in re.split(r"[\s|]+", c["text"] or "")) if t][:3]
        if not first:
            continue
        start = cursor if cursor_page == c["page"] else 0
        found = None
        for k in range(len(first), 0, -1):
            for base in (start, 0):
                for i in range(base, len(toks) - k + 1):
                    if toks[i:i + k] == first[:k]:
                        found = i
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is not None:
            y0 = round(max(0.0, ws[found][2] - (0.011 if c["kind"] == "table" else 0.004)), 4)
            y1 = None
            if c["kind"] == "table" and (c["page_to"] or c["page"]) == c["page"]:
                # низ таблицы на одной странице - последние слова её текста
                tail = [t for t in (_norm_tok(x) for x in re.split(r"[\s|]+", c["text"] or "")) if t][-2:]
                for i in range(len(toks) - len(tail), found - 1, -1):
                    if toks[i:i + len(tail)] == tail:
                        y1 = round(ws[i + len(tail) - 1][4] + 0.014, 4)
                        break
            out[c["id"]] = (y0, y1)
            cursor_page, cursor = c["page"], found
    return out


# поиск
def segment_ys(doc_id):
    # где на странице стоят куски фрагментов: {id: [(y0, y1) | None]}
    with connect() as con:
        pages = {r["page"]: json.loads(r["words"]) for r in
                 con.execute("SELECT page, words FROM pages WHERE doc_id=?", (doc_id,))}
        chunks = [dict(r) for r in con.execute(
            "SELECT id, text, geom FROM chunks WHERE doc_id=? AND kind!='table' AND geom IS NOT NULL ORDER BY seq", (doc_id,))]
    toks_of = {p: [_norm_tok(w[0]) for w in ws] for p, ws in pages.items()}
    cursor = {}
    out = {}
    for c in chunks:
        lines = [l for l in (c["text"] or "").split("\n") if l.strip()]
        res = []
        for g in json.loads(c["geom"]):
            ws, toks = pages.get(g["page"]), toks_of.get(g["page"])
            seg = lines[g["r0"]:g["r1"]]
            seg_toks = [t for t in (_norm_tok(x) for x in re.split(r"\s+", " ".join(seg))) if t]
            if not ws or not seg_toks:
                res.append(None)
                continue
            first = seg_toks[:3]
            found = None
            for k in range(len(first), 0, -1):
                for base in (cursor.get(g["page"], 0), 0):
                    for i in range(base, len(toks) - k + 1):
                        if toks[i:i + k] == first[:k]:
                            found = i
                            break
                    if found is not None:
                        break
                if found is not None:
                    break
            if found is None:
                res.append(None)
                continue
            guess = min(len(toks) - 1, found + len(seg_toks) - 1)
            tail = seg_toks[-2:]
            end = guess
            for i in sorted(range(max(found, guess - 8), min(len(toks) - len(tail), guess + 8) + 1), key=lambda i: abs(i - guess)):
                if toks[i:i + len(tail)] == tail:
                    end = i + len(tail) - 1
                    break
            cursor[g["page"]] = end + 1
            res.append((round(max(0.0, ws[found][2] - 0.004), 4), round(min(1.0, ws[end][4] + 0.004), 4)))
        out[c["id"]] = res
    return out


def _query_terms(query):
    words = [w for w in WORD_RE.findall(query) if w.lower() not in STOP]
    return [(w, stem(w)) for w in words]


def _match_expr(terms, op):
    parts = []
    for _w, s in terms:
        parts.append(f'"{s}"*' if len(s) >= 3 else f'"{s}"')
    return f" {op} ".join(parts)


def _mark(text, q_stems):
    out, pos = [], 0
    for m in WORD_RE.finditer(text):
        st = stem(m.group())
        if any(matches(st, q) for q in q_stems):
            out.append(html.escape(text[pos:m.start()]))
            out.append("<mark>" + html.escape(m.group()) + "</mark>")
            pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _snippet(text, terms, width=230):
    q_stems = [s for _w, s in terms]
    spans = list(WORD_RE.finditer(text))
    hits = [m for m in spans if any(matches(stem(m.group()), q) for q in q_stems)]
    if hits:
        best = max(hits, key=lambda h: sum(1 for x in hits if h.start() <= x.start() < h.start() + width))
        start = max(0, best.start() - 70)
    else:
        start = 0
    end = min(len(text), start + width)
    if start > 0:
        sp = text.find(" ", start)
        start = sp + 1 if 0 <= sp < start + 25 else start
    if end < len(text):
        sp = text.rfind(" ", start, end)
        end = sp if sp > start + width // 2 else end
    body = _mark(text[start:end], q_stems).replace("\n", " ")
    return ("… " if start > 0 else "") + body.strip() + (" …" if end < len(text) else "")


def _table_snippet(rows, terms):
    q_stems = [s for _w, s in terms]
    if not rows:
        return ""
    hit_rows = [r for r in rows[1:] if any(matches(stem(w), q) for c in r for w in WORD_RE.findall(c) for q in q_stems)]
    shown = [rows[0]] + (hit_rows[:3] if hit_rows else rows[1:3])
    lines = [_mark(" | ".join(r), q_stems) for r in shown]
    more = len(hit_rows) - 3
    if more > 0:
        lines.append(f"… ещё строк: {more}")
    return "<br>".join(lines)


def _phrase_bonus(text, q_stems):
    if len(q_stems) < 2:
        return 0.0
    seq = stems(text)
    n = len(q_stems)
    for i in range(len(seq) - n + 1):
        if all(matches(seq[i + k], q_stems[k]) for k in range(n)):
            return 3.0
    return 0.0


def search(query, limit=20, per_doc=3, folder=None):
    query = (query or "").strip()
    if not query:
        return {"query": query, "total": 0, "results": []}
    terms = _query_terms(query)
    results, seen = [], set()
    frows = list_folders()
    fmap = {r["id"]: r for r in frows}
    allowed = set(descendants(folder, frows)) if folder else None

    with connect() as con:
        docs = {r["id"]: dict(r) for r in con.execute("SELECT * FROM docs WHERE status='indexed'")}
        if allowed is not None:
            docs = {k: v for k, v in docs.items() if v["folder"] in allowed}

        def add(row, kind, score, terms_for_snippet):
            if row["id"] in seen or row["doc_id"] not in docs:
                return
            seen.add(row["id"])
            d = docs[row["doc_id"]]
            if row["kind"] == "table" and row["data"]:
                snippet = _table_snippet(json.loads(row["data"]), terms_for_snippet)
            else:
                snippet = _snippet(row["text"], terms_for_snippet)
            results.append({
                "chunk_id": row["id"], "doc_id": d["id"], "doc_name": d["name"], "folder": d["folder"],
                "folder_path": folder_path(d["folder"], fmap),
                "section": row["section"], "parent": row["parent"], "title": row["title"],
                "page": row["page"], "page_to": row["page_to"], "source": row["source"], "chunk_kind": row["kind"],
                "kind": kind, "score": round(score, 3), "snippet": snippet,
            })

        # запрос - номер пункта («2.5.2.2»)
        if SECTION_RE.match(query):
            num = query.rstrip(".")
            rows = con.execute(
                "SELECT * FROM chunks WHERE section = ? OR section LIKE ? ORDER BY (section = ?) DESC, seq LIMIT 40",
                (num, num + ".%", num)).fetchall()
            for r in rows:
                add(r, "section", 100 - len(r["section"]), [])

        if terms and not SECTION_RE.match(query):
            q_stems = [s for _w, s in terms]

            # совпадение по названию файла
            for d in docs.values():
                name_stems = stems(d["name"].rsplit(".", 1)[0])
                if all(any(matches(n, q) for n in name_stems) for q in q_stems):
                    first = con.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY seq LIMIT 1", (d["id"],)).fetchone()
                    if first is not None:
                        add(first, "name", 7, [])
                    elif ("doc:" + d["id"]) not in seen:  # скан без текста: блоков нет, ищем по названию
                        seen.add("doc:" + d["id"])
                        results.append({
                            "chunk_id": None, "doc_id": d["id"], "doc_name": d["name"], "folder": d["folder"],
                            "folder_path": folder_path(d["folder"], fmap), "section": "", "parent": "", "title": "",
                            "page": 1, "page_to": 1, "source": "empty", "chunk_kind": "text",
                            "kind": "name", "score": 7, "snippet": "Документ без распознанного текста (скан)",
                        })

            # полнотекст: сначала все слова (AND), потом любое (OR)
            for op in ("AND", "OR"):
                if len(results) >= limit * 2 or (op == "OR" and len(terms) == 1):
                    break
                try:
                    rows = con.execute(
                        "SELECT c.*, bm25(chunks_fts, 1.0, 3.0) AS rank FROM chunks_fts "
                        "JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ? "
                        "ORDER BY rank LIMIT 120", (_match_expr(terms, op),)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for r in rows:
                    n = len(r["text"])
                    # короткие заголовки без текста не должны обгонять сам пункт
                    length = min(n, 300) / 300 * 2 - (1.5 if n < 60 else 0)
                    score = (-r["rank"] + _phrase_bonus(r["title"] + " " + r["text"], q_stems)
                             + length + (0 if op == "AND" else -2))
                    add(r, "text", score, terms)

    results.sort(key=lambda r: -r["score"])
    out, per = [], {}
    for r in results:
        if per.get(r["doc_id"], 0) >= per_doc:
            continue
        per[r["doc_id"]] = per.get(r["doc_id"], 0) + 1
        out.append(r)
        if len(out) >= limit:
            break

    # папки по названию
    folders = []
    if terms and not SECTION_RE.match(query):
        q_stems = [s for _w, s in terms]
        for f in frows:
            if f["system"] and f["id"] == INBOX and not any(matches(s, q) for s in stems(f["name"]) for q in q_stems):
                continue
            ns = stems(f["name"])
            if all(any(matches(n, q) for n in ns) for q in q_stems):
                folders.append({"id": f["id"], "name": f["name"], "path": folder_path(f["id"], fmap), "total": f["total"]})
    return {"query": query, "total": len(out), "results": out, "folders": folders[:5]}


# поиск внутри документа
def _page_tokens(rows):
    words, tokens = [], []
    for page, source, raw in rows:
        for w in json.loads(raw):
            idx = len(words)
            words.append((page, w))
            for part in WORD_RE.findall(w[0]):
                tokens.append((stem(part), idx, part))
    return words, tokens


def find_in_doc(doc_id, query, chunk_id=None):
    query = (query or "").strip()
    out = {"query": query, "total": 0, "hits": [], "start": 0, "mode": "none"}
    if not query:
        return out
    with connect() as con:
        rows = [(r["page"], r["source"], r["words"]) for r in
                con.execute("SELECT page, source, words FROM pages WHERE doc_id=? ORDER BY page", (doc_id,))]
        chunk = None
        if chunk_id:
            row = con.execute("SELECT * FROM chunks WHERE id=? AND doc_id=?", (chunk_id, doc_id)).fetchone()
            chunk = dict(row) if row else None
        all_chunks = [dict(r) for r in con.execute(
            "SELECT id, page, page_to, text, title FROM chunks WHERE doc_id=? ORDER BY seq", (doc_id,))]
    chunk_sets = {c["id"]: set(stems(c["text"] + " " + (c["title"] or ""))) for c in all_chunks}
    words, tokens = _page_tokens(rows)

    spans = []  # каждое совпадение - список индексов слов
    if SECTION_RE.match(query):
        num = query.rstrip(".")
        for i, (_p, w) in enumerate(words):
            if w[0].rstrip(".,;:") == num:
                spans.append([i])
        out["mode"] = "section"
    else:
        terms = [stem(w) for w in WORD_RE.findall(query) if w.lower() not in STOP] or stems(query)
        n = len(terms)
        content = [t for t in tokens if t[0] not in STOP]
        # фраза целиком, слова подряд
        for i in range(len(content) - n + 1):
            if all(matches(content[i + k][0], terms[k]) for k in range(n)):
                spans.append(sorted({content[i + k][1] for k in range(n)}))
        out["mode"] = "phrase"
        # все слова рядом (в пределах 10)
        if not spans and n > 1:
            i = 0
            while i < len(content):
                if matches(content[i][0], terms[0]) or any(matches(content[i][0], t) for t in terms):
                    window = content[i:i + 10]
                    found = {}
                    for t in window:
                        for q in terms:
                            if q not in found and matches(t[0], q):
                                found[q] = t[1]
                    if len(found) == n:
                        spans.append(sorted(set(found.values())))
                        i += 10
                        continue
                i += 1
            out["mode"] = "near"
        # любое из слов
        if not spans:
            for t in content:
                if any(matches(t[0], q) for q in terms):
                    spans.append([t[1]])
            spans = [list(s) for s in {tuple(s): s for s in spans}.values()]
            spans.sort()
            out["mode"] = "any" if n > 1 else "phrase"

    hits = []
    for sp in spans:
        by_page = {}
        for wi in sp:
            page, w = words[wi]
            by_page.setdefault(page, []).append(w)
        for page, ws in by_page.items():
            boxes = []  # слова одной строки склеиваем в один прямоугольник
            for w in sorted(ws, key=lambda w: (round((w[2] + w[4]) / 2, 3), w[1])):
                yc = (w[2] + w[4]) / 2
                if boxes and abs(boxes[-1]["yc"] - yc) < (w[4] - w[2]) * 0.6 and w[1] - boxes[-1]["b"][2] < 0.05:
                    b = boxes[-1]["b"]
                    b[0], b[1], b[2], b[3] = min(b[0], w[1]), min(b[1], w[2]), max(b[2], w[3]), max(b[3], w[4])
                else:
                    boxes.append({"yc": yc, "b": [w[1], w[2], w[3], w[4]]})
            ctx_from, ctx_to = max(0, sp[0] - 6), min(len(words), sp[-1] + 7)
            context = " ".join(words[k][1][0] for k in range(ctx_from, ctx_to))
            ctx = set(stems(context))
            cand = [c for c in all_chunks if c["page"] <= page <= (c["page_to"] or c["page"])]
            best_c = max(cand, key=lambda c: len(chunk_sets[c["id"]] & ctx), default=None)
            hits.append({"page": page, "boxes": [b["b"] for b in boxes], "word": sp[0], "context": context,
                         "chunk": best_c["id"] if best_c else None})
    hits.sort(key=lambda h: (h["page"], h["boxes"][0][1], h["boxes"][0][0]))
    out["hits"], out["total"] = hits, len(hits)

    # первым показываем совпадение из выбранного фрагмента
    if chunk and hits:
        cs = set(stems(chunk["text"] + " " + (chunk["title"] or "")))
        best, best_score = 0, -1
        for i, h in enumerate(hits):
            if not (chunk["page"] <= h["page"] <= (chunk["page_to"] or chunk["page"])):
                continue
            score = len(cs & set(stems(h["context"])))
            if score > best_score:
                best, best_score = i, score
        out["start"] = best
    return out


# подключённая папка
def st_folders():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM folders WHERE rel IS NOT NULL")]


def st_docs():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM docs WHERE rel IS NOT NULL")]


def st_add_folder(fid, parent_id, name, rel, system=False):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO folders(id, parent_id, name, system, hints, created_at, sort, rel) VALUES (?,?,?,?,?,?,?,?)",
                    (fid, parent_id, name, 1 if system else 0, "", time.strftime("%Y-%m-%d %H:%M:%S"), 0, rel))


def st_update_folder(fid, **fields):
    allowed = {"name", "parent_id", "rel", "system"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    with connect() as con:
        con.execute(f"UPDATE folders SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [fields[c] for c in cols] + [fid])


def st_update_doc(doc_id, **fields):
    allowed = {"folder", "name", "path", "rel", "size_bytes", "mtime", "want_sort"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    with connect() as con:
        con.execute(f"UPDATE docs SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [fields[c] for c in cols] + [doc_id])


def st_delete_folders(ids):
    if not ids:
        return
    with connect() as con:
        marks = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM folders WHERE id IN ({marks})", list(ids))


def st_retag_folder(old, new):
    with connect() as con:
        con.execute("UPDATE folders SET id=? WHERE id=?", (new, old))
        con.execute("UPDATE folders SET parent_id=? WHERE parent_id=?", (new, old))
        con.execute("UPDATE docs SET folder=? WHERE folder=?", (new, old))


def reset_all():
    with _lock, connect() as con:
        for t in ("chunks_fts", "chunks", "pages", "docs", "folders", "meta"):
            con.execute(f"DELETE FROM {t}")
