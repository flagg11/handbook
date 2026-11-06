import json
import os
import hmac
import re
import shutil
import threading
import urllib.parse
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

import classify
import docparse
import docxconv
import exportdoc
import searchindex as index
import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
PAGES_DIR = os.path.join(BASE_DIR, "data", "pages")
FIGS_DIR = os.path.join(BASE_DIR, "data", "figs")
CONV_DIR = os.path.join(BASE_DIR, "data", "conv")  # конвертированные word -> pdf
ALLOWED_EXTENSIONS = {"pdf", "docx"}
_conv_lock = threading.Lock()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 мб на запрос
app.json.ensure_ascii = False

_executor = ThreadPoolExecutor(max_workers=1)
_boot_lock = threading.Lock()
_booted = False


# доступ
HOST = os.environ.get("HANDBOOK_HOST", "127.0.0.1")
PORT = int(os.environ.get("HANDBOOK_PORT", "5000"))
ACCESS_USER = os.environ.get("HANDBOOK_USER", "handbook")
ACCESS_PASSWORD = os.environ.get("HANDBOOK_PASSWORD", "")  # если задан - включается пароль (basic)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("HANDBOOK_ALLOWED_HOSTS", "").split(",") if h.strip()}


def _is_loopback_bind(host):
    return host in ("127.0.0.1", "localhost", "::1")


def _host_ok(host_header):
    host = (host_header or "").strip().lower()
    name = host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]
    return name in LOCAL_HOSTS or host in EXTRA_HOSTS or name in EXTRA_HOSTS


def _valid_upload(path, ext):
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
        if ext == ".pdf":
            return head.startswith(b"%PDF")
        if ext == ".docx":
            if not head.startswith(b"PK"):
                return False
            with zipfile.ZipFile(path) as z:
                return "word/document.xml" in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False
    return False


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def human_size(num_bytes):
    size = float(num_bytes or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024


def doc_to_json(d):
    return {
        "id": d["id"], "folder": d["folder"], "name": d["name"],
        "size": human_size(d["size_bytes"]), "date": d["date_label"], "author": d["author"],
        "status": d["status"], "pages": d["pages"], "ocr_pages": d["ocr_pages"], "tables": d["tables"],
        "chunks": d["chunks"], "warnings": [w for w in (d["warnings"] or "").split("\n") if w],
        "error": d["error"], "url": f"/files/{d['id']}",
        "kind": "docx" if d["name"].lower().endswith(".docx") else "pdf",
        "auto": bool(d["auto"]), "confidence": d["confidence"], "reason": d["reason"],
        "needs_review": bool(d["needs_review"]), "want_sort": bool(d["want_sort"]),
    }


def folder_to_json(f):
    return {"id": f["id"], "parent": f["parent_id"], "name": f["name"], "system": bool(f["system"]),
            "docs": f["docs"], "total": f["total"]}


def pdf_path(doc):
    # pdf, из которого читаем: сам файл или конвертация для word
    path = doc["path"]
    if not path.lower().endswith(".docx"):
        return path
    dst = os.path.join(CONV_DIR, doc["id"] + ".pdf")
    with _conv_lock:
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(path):
            os.makedirs(CONV_DIR, exist_ok=True)
            docxconv.docx_to_pdf(path, dst)
    return dst


def drop_doc_caches(doc_id):
    try:
        os.remove(os.path.join(CONV_DIR, doc_id + ".pdf"))
    except OSError:
        pass
    shutil.rmtree(os.path.join(PAGES_DIR, doc_id), ignore_errors=True)
    shutil.rmtree(os.path.join(FIGS_DIR, doc_id), ignore_errors=True)
    classify.forget(doc_id)


storage.on_drop = drop_doc_caches


def _remove_doc_files(doc):
    # в демо файл удаляем с диска, в папке им уже занимается storage (корзина)
    if not storage.active() and not doc["sample"] and os.path.exists(doc["path"]):
        os.remove(doc["path"])
    drop_doc_caches(doc["id"])


def _error(message, status=400):
    return jsonify({"error": message}), status


# обработка
def autosort(doc_id):
    decision = classify.classify_document(doc_id)
    mover = storage.move_doc if storage.active() else index.move_document
    try:
        mover(doc_id, decision["folder"], auto=True, confidence=decision["confidence"],
              reason=decision["reason"], needs_review=decision["review"])
    except (ValueError, LookupError):
        # папку на диске не поменять (права, имя занято) - файл остаётся где был, с пометкой
        index.move_document(doc_id, index.get_document(doc_id)["folder"], auto=True, confidence=0.0,
                            reason="Не удалось перенести файл на диске", needs_review=True)
        decision = dict(decision, folder=index.get_document(doc_id)["folder"], review=True)
    return decision


_queued = set()
_queue_lock = threading.Lock()


def submit_ingest(doc_id):
    with _queue_lock:
        if doc_id in _queued:
            return
        _queued.add(doc_id)

    def run():
        with _queue_lock:
            _queued.discard(doc_id)
        ingest(doc_id)
    _executor.submit(run)


def ingest(doc_id):
    doc = index.get_document(doc_id)
    if not doc:
        return
    try:
        result = docparse.parse_pdf(pdf_path(doc))
        classify.forget(doc_id)
        shutil.rmtree(os.path.join(PAGES_DIR, doc_id), ignore_errors=True)
        shutil.rmtree(os.path.join(FIGS_DIR, doc_id), ignore_errors=True)
        index.index_document(doc_id, result.pages, result.chunks)
        tables = sum(1 for c in result.chunks if c.kind == "table")
        index.finish_document(doc_id, len(result.pages), result.ocr_pages, tables,
                              len(result.chunks), result.chars, result.warnings)
        if doc["want_sort"]:
            autosort(doc_id)
    except Exception as exc:  # битый пдф и всё такое
        if index.get_document(doc_id):
            index.fail_document(doc_id, exc)


_active_mode = None


def activate():
    global _active_mode
    cfg = storage.load()
    if not cfg["configured"]:
        return
    docparse.OCR_ENABLED = bool(cfg["ocr"])
    if _active_mode == cfg["mode"]:
        return
    _active_mode = cfg["mode"]
    if cfg["mode"] == "demo":
        if index.meta_claim("folders_seeded"):
            index.seed_folders(classify.FOLDER_TREE)
        if index.meta_claim("samples_seeded"):
            manifest_path = os.path.join(SAMPLES_DIR, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, encoding="utf-8") as fh:
                    for item in json.load(fh):
                        path = os.path.join(SAMPLES_DIR, item["file"])
                        if not os.path.exists(path):
                            continue
                        folder = item["folder"] if index.get_folder(item["folder"]) else index.INBOX
                        doc_id = "sm-" + uuid.uuid4().hex[:10]
                        index.add_document(doc_id, folder, item["file"], path, os.path.getsize(path),
                                           item.get("author", "—"), item.get("date"), sample=True)
    for d in index.pending_documents():
        submit_ingest(d["id"])
    if cfg["mode"] == "storage":
        storage.start_scanner(submit_ingest)


def boot_once():
    global _booted
    with _boot_lock:
        if _booted:
            return
        index.init_db()
        activate()
        _booted = True


OPEN_PREFIXES = ("/static/", "/api/config", "/api/setup", "/api/fs/")


@app.before_request
def _guard():
    if not _host_ok(request.host):
        return _error("Недопустимое имя хоста", 400)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc.lower() != request.host.lower():
            return _error("Запрос с другого сайта отклонён", 403)
    if ACCESS_PASSWORD:
        auth = request.authorization
        ok = bool(auth and hmac.compare_digest((auth.username or "").encode(), ACCESS_USER.encode())
                  and hmac.compare_digest((auth.password or "").encode(), ACCESS_PASSWORD.encode()))
        if not ok:
            return Response("Нужен пароль", 401, {"WWW-Authenticate": 'Basic realm="Handbook", charset="UTF-8"'})


@app.after_request
def _headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.before_request
def _ensure_boot():
    boot_once()
    if not storage.configured() and request.path != "/" and not request.path.startswith(OPEN_PREFIXES):
        return _error("Сначала нужно настроить хранилище", 409)


# страница
@app.route("/")
def home():
    return render_template("index.html", app_name=storage.load()["app_name"])


# папки
@app.route("/api/folders", methods=["GET"])
def folders_list():
    return jsonify([folder_to_json(f) for f in index.list_folders()])


@app.route("/api/folders", methods=["POST"])
def folders_create():
    data = request.get_json(silent=True) or {}
    try:
        if storage.active():
            f = storage.create_folder(data.get("name"), data.get("parent") or None)
        else:
            f = index.create_folder(data.get("name"), data.get("parent") or None)
    except LookupError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc))
    f.update({"docs": 0, "total": 0})
    return jsonify(folder_to_json(f)), 201


@app.route("/api/folders/<fid>", methods=["PATCH"])
def folders_update(fid):
    data = request.get_json(silent=True) or {}
    try:
        update = storage.update_folder if storage.active() else index.update_folder
        f = update(fid, name=data.get("name"), parent_id=data["parent"] if "parent" in data else "__keep__")
    except LookupError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc))
    f.update({"docs": 0, "total": 0})
    return jsonify(folder_to_json(f))


@app.route("/api/folders/<fid>", methods=["DELETE"])
def folders_delete(fid):
    try:
        docs = storage.delete_folder(fid) if storage.active() else index.delete_folder(fid)
    except LookupError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc))
    for d in docs:
        _remove_doc_files(d)
    return jsonify({"ok": True, "deleted_docs": len(docs)})


# документы
@app.route("/api/uploads", methods=["GET"])
def list_uploads():
    return jsonify([doc_to_json(d) for d in index.list_documents()])


@app.route("/api/upload", methods=["POST"])
def upload_file():
    file = request.files.get("file")
    auto = request.form.get("auto") == "1"
    folder = (request.form.get("folder") or "").strip()

    if not file or file.filename == "":
        return _error("Файл не выбран")
    if not allowed_file(file.filename):
        if file.filename.lower().endswith(".doc"):
            return _error("Старый формат .doc не поддерживается: пересохраните файл как .docx")
        return _error("Разрешены только файлы PDF и Word (.docx)")
    if auto:
        folder = index.INBOX
    elif not folder or not index.get_folder(folder):
        return _error("Папка для загрузки не найдена")
    if storage.active():
        try:
            doc_id = storage.save_upload(file, folder, want_sort=auto, validate=_valid_upload)
        except (ValueError, LookupError) as exc:
            return _error(str(exc))
        submit_ingest(doc_id)
        return jsonify(doc_to_json(index.get_document(doc_id))), 201

    doc_id = "up-" + uuid.uuid4().hex[:12]
    original = os.path.basename(file.filename.replace("\\", "/"))
    display_name = storage.with_ext(original)
    ext = os.path.splitext(display_name)[1].lower()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")  # на диске по id, имя и папка в бд
    file.save(dest)
    if not _valid_upload(dest, ext):
        os.remove(dest)
        return _error("Файл повреждён или его содержимое не соответствует формату " + ext.lstrip(".").upper())

    index.add_document(doc_id, folder, display_name, dest, os.path.getsize(dest), "Вы", want_sort=auto)
    submit_ingest(doc_id)
    return jsonify(doc_to_json(index.get_document(doc_id))), 201


@app.route("/api/docs/<doc_id>", methods=["PATCH"])
def doc_update(doc_id):
    doc = index.get_document(doc_id)
    if doc is None:
        return _error("Файл не найден", 404)
    data = request.get_json(silent=True) or {}
    try:
        if data.get("name") is not None:
            (storage.rename_doc if storage.active() else index.rename_document)(doc_id, data["name"])
        if data.get("folder"):
            (storage.move_doc if storage.active() else index.move_document)(doc_id, data["folder"])  # ручной перенос снимает пометки автосортировки
    except (ValueError, LookupError) as exc:
        return _error(str(exc))
    return jsonify(doc_to_json(index.get_document(doc_id)))


@app.route("/api/upload/<doc_id>", methods=["DELETE"])
def delete_upload(doc_id):
    doc = index.get_document(doc_id)
    if doc is None:
        return _error("Файл не найден", 404)
    try:
        if storage.active():
            storage.delete_doc(doc_id)
        else:
            index.delete_document(doc_id)
    except (ValueError, LookupError) as exc:
        return _error(str(exc))
    _remove_doc_files(doc)
    return jsonify({"ok": True})


@app.route("/api/docs/<doc_id>/reparse", methods=["POST"])
def doc_reparse(doc_id):
    doc = index.get_document(doc_id)
    if doc is None or not os.path.exists(doc["path"]):
        return _error("Файл не найден", 404)
    if doc["status"] == "processing":
        return _error("Файл уже обрабатывается")
    shutil.rmtree(os.path.join(FIGS_DIR, doc_id), ignore_errors=True)
    index.restart_processing(doc_id)
    submit_ingest(doc_id)
    return jsonify(doc_to_json(index.get_document(doc_id)))


@app.route("/api/reparse", methods=["POST"])
def reparse_many():
    data = request.get_json(silent=True) or {}
    fid = data.get("folder") or None
    if fid and not index.get_folder(fid):
        return _error("Папка не найдена", 404)
    scope = set(index.descendants(fid)) if fid else None
    count = 0
    for d in index.list_documents():
        if (scope is not None and d["folder"] not in scope) or d["status"] == "processing":
            continue
        if not os.path.exists(d["path"]):
            continue
        shutil.rmtree(os.path.join(FIGS_DIR, d["id"]), ignore_errors=True)
        index.restart_processing(d["id"])
        submit_ingest(d["id"])
        count += 1
    return jsonify({"count": count})


@app.route("/api/docs/<doc_id>/autosort", methods=["POST"])
def doc_autosort(doc_id):
    doc = index.get_document(doc_id)
    if doc is None:
        return _error("Файл не найден", 404)
    if doc["status"] != "indexed":
        return _error("Файл ещё обрабатывается")
    decision = autosort(doc_id)
    return jsonify({"doc": doc_to_json(index.get_document(doc_id)), "decision": decision})


@app.route("/api/autosort/inbox", methods=["POST"])
def inbox_autosort():
    moved = left = 0
    for d in index.list_documents():
        if d["folder"] == index.INBOX and d["status"] == "indexed":
            decision = autosort(d["id"])
            if decision["folder"] == index.INBOX:
                left += 1
            else:
                moved += 1
    return jsonify({"moved": moved, "left": left})


@app.route("/api/docs/<doc_id>")
def doc_details(doc_id):
    doc = index.get_document(doc_id)
    if doc is None:
        abort(404)
    chunks = index.document_chunks(doc_id)
    anchors = index.chunk_anchors(doc_id)
    for c in chunks:
        a = anchors.get(c["id"])
        c["y"], c["y1"] = a if a else (None, None)
    seg_ys = index.segment_ys(doc_id)
    for c in chunks:
        for g, yy in zip(c.get("geom") or [], seg_ys.get(c["id"], [])):
            if yy and "box" not in g:
                g["y0"], g["y1"] = yy
    sizes, figures = [], []
    if os.path.exists(doc["path"]):
        sizes = docparse.page_sizes(pdf_path(doc))
        figures = _figures(doc)
    info = doc_to_json(doc)
    info["empty_pages"] = sum(1 for m in index.pages_meta(doc_id) if m["source"] == "empty")
    return jsonify({"doc": info, "chunks": chunks, "sizes": sizes, "figures": figures})


def _figures(doc):
    folder = os.path.join(FIGS_DIR, doc["id"])
    meta = os.path.join(folder, "figs_v3.json")
    if not os.path.exists(meta):
        sources = {m["page"]: m["source"] for m in index.pages_meta(doc["id"])}
        try:
            figs = docparse.extract_figures(pdf_path(doc), folder, sources)
        except Exception:
            figs = []
        os.makedirs(folder, exist_ok=True)
        with open(meta, "w", encoding="utf-8") as fh:
            json.dump(figs, fh, ensure_ascii=False)
    with open(meta, encoding="utf-8") as fh:
        figs = json.load(fh)
    for f in figs:
        f["url"] = f"/api/docs/{doc['id']}/fig/{f['file']}"
    return figs


@app.route("/api/docs/<doc_id>/fig/<name>")
def doc_figure(doc_id, name):
    if index.get_document(doc_id) is None or not re.fullmatch(r"\d+_\d+\.png", name):
        abort(404)
    path = os.path.join(FIGS_DIR, doc_id, name)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/png", max_age=3600)


@app.route("/api/docs/<doc_id>/export.docx")
def doc_export(doc_id):
    doc = index.get_document(doc_id)
    if doc is None:
        abort(404)
    if doc["status"] != "indexed":
        return _error("Файл ещё обрабатывается")
    sizes = []
    try:
        sizes = docparse.page_sizes(pdf_path(doc))
    except Exception:
        pass
    page = tuple(sizes[0]) if sizes and sizes[0][0] < sizes[0][1] and sizes[0][1] < 900 else (595.0, 842.0)
    data = exportdoc.build_docx(os.path.splitext(doc["name"])[0], index.document_chunks(doc_id), sizes, page)
    base = os.path.splitext(doc["name"])[0] + ".docx"
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(base)})


@app.route("/api/chunks/<int:chunk_id>", methods=["PATCH"])
def chunk_update(chunk_id):
    data = request.get_json(silent=True) or {}
    try:
        doc_id = index.update_chunk(chunk_id, text=data.get("text"), rows=data.get("rows"))
    except LookupError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc))
    classify.forget(doc_id)
    chunk = next(c for c in index.document_chunks(doc_id) if c["id"] == chunk_id)
    return jsonify(chunk)


@app.route("/api/docs/<doc_id>/find")
def doc_find(doc_id):
    if index.get_document(doc_id) is None:
        abort(404)
    chunk = request.args.get("chunk", type=int)
    return jsonify(index.find_in_doc(doc_id, request.args.get("q", ""), chunk_id=chunk))


@app.route("/api/docs/<doc_id>/page/<int:page_no>.png")
def doc_page_image(doc_id, page_no):
    doc = index.get_document(doc_id)
    if doc is None or not os.path.exists(doc["path"]):
        abort(404)
    info = index.page_info(doc_id, page_no)
    if info is None:
        abort(404)
    cache = os.path.join(PAGES_DIR, doc_id, f"{page_no}.png")
    if not os.path.exists(cache):
        png, _w, _h = docparse.render_page_png(pdf_path(doc), page_no, width=1100, skew=info["skew"],
                                                ocr_page=info["source"] == "ocr")
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as fh:
            fh.write(png)
    resp = send_file(cache, mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/api/search")
def search():
    q = request.args.get("q", "")
    folder = request.args.get("folder") or None
    return jsonify(index.search(q, limit=20, folder=folder))


@app.route("/api/status")
def status():
    docs = index.list_documents()
    cfg = storage.load()
    return jsonify({
        "ocr": docparse.ocr_status(),
        "documents": len(docs),
        "processing": sum(1 for d in docs if d["status"] in ("processing", "queued")),
        "rev": storage.rev,
        "scanning": storage.state["scanning"],
        "storage_error": storage.state["error"],
        "legacy_doc": len(storage.state["legacy"]),
        "legacy_examples": storage.state["legacy"][:5],
        "usage": storage.usage(),
        "root": cfg["root"] if storage.active() else "",
    })


# настройки и подключение
def config_to_json():
    cfg = storage.load()
    return {"configured": cfg["configured"], "mode": cfg["mode"], "app_name": cfg["app_name"], "root": cfg["root"],
            "auto_sort": cfg["auto_sort"], "inbox_name": cfg["inbox_name"], "scan_interval": cfg["scan_interval"],
            "ocr": cfg["ocr"], "trash": cfg["trash"], "ocr_available": docparse.ocr_status()}


@app.route("/api/config", methods=["GET"])
def config_get():
    return jsonify(config_to_json())


@app.route("/api/config", methods=["PATCH"])
def config_patch():
    if not storage.configured():
        return _error("Сначала нужно настроить хранилище", 409)
    try:
        changes = storage.clean_settings(request.get_json(silent=True) or {})
    except ValueError as exc:
        return _error(str(exc))
    storage.save(**changes)
    docparse.OCR_ENABLED = bool(storage.load()["ocr"])
    if storage.active():
        storage.wake.set()  # настройки применяем сразу, не ждём следующей проверки
    return jsonify(config_to_json())


def _local_client():
    # за прокси на этом же компьютере все приходят с 127.0.0.1 - прокси выдаёт заголовок, по нему отличаем
    if request.headers.get("X-Forwarded-For") or request.headers.get("Forwarded"):
        return False
    return request.remote_addr in ("127.0.0.1", "::1", None)


@app.route("/api/fs/list")
def fs_list():
    if not _local_client():
        return _error("Выбор папки доступен только на самом компьютере, где запущена программа", 403)
    if storage.configured():
        return _error("Хранилище уже подключено", 409)
    try:
        return jsonify(storage.browse(request.args.get("path", "")))
    except ValueError as exc:
        return _error(str(exc))


@app.route("/api/fs/probe")
def fs_probe():
    if not _local_client():
        return _error("Выбор папки доступен только на самом компьютере, где запущена программа", 403)
    if storage.configured():
        return _error("Хранилище уже подключено", 409)
    try:
        return jsonify(storage.probe(request.args.get("path", "")))
    except ValueError as exc:
        return _error(str(exc))


@app.route("/api/setup", methods=["POST"])
def setup():
    global _active_mode
    if not _local_client():
        return _error("Первая настройка выполняется на самом компьютере, где запущена программа", 403)
    if storage.configured():
        return _error("Хранилище уже настроено", 409)
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    if mode not in ("storage", "demo"):
        return _error("Выберите, что подключить")
    try:
        settings = storage.clean_settings(data)
    except ValueError as exc:
        return _error(str(exc))
    root = ""
    if mode == "storage":
        path = storage._norm(str(data.get("root") or ""))
        if not data.get("root") or not os.path.isdir(path):
            return _error("Укажите существующую папку с документами")
        if not os.access(path, os.R_OK):
            return _error("Нет доступа к этой папке")
        root = path
        index.reset_all()  # индекс от старого хранилища не нужен
        for d in (PAGES_DIR, FIGS_DIR):
            shutil.rmtree(d, ignore_errors=True)
        classify._counts.clear()
    settings.setdefault("app_name", storage.DEFAULTS["app_name"])
    if mode == "demo":
        settings.setdefault("auto_sort", True)
    _active_mode = None
    storage.save(configured=True, mode=mode, root=root, **settings)
    activate()
    if mode == "storage":
        storage.sync(submit_ingest)  # первое чтение сразу, распознавание потом в фоне
    return jsonify(config_to_json()), 201


@app.route("/api/setup/reset", methods=["POST"])
def setup_reset():
    global _active_mode
    if not _local_client():
        return _error("Отключить хранилище можно только на самом компьютере, где запущена программа", 403)
    storage.save(configured=False, mode="", root="")
    _active_mode = None
    return jsonify(config_to_json())


@app.route("/api/storage/rescan", methods=["POST"])
def storage_rescan():
    if not storage.active():
        return _error("Проверка нужна только для подключённой папки")
    changed = storage.sync(submit_ingest)
    return jsonify({"changed": changed, "rev": storage.rev})


@app.route("/files/<doc_id>")
def serve_file(doc_id):
    doc = index.get_document(doc_id)
    if doc is None or not os.path.exists(doc["path"]):
        abort(404)
    if doc["path"].lower().endswith(".docx"):
        return send_file(doc["path"], mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                         download_name=doc["name"], as_attachment=True)
    return send_file(doc["path"], mimetype="application/pdf", download_name=doc["name"], as_attachment=False)


if __name__ == "__main__":
    if not _is_loopback_bind(HOST) and not ACCESS_PASSWORD:
        raise SystemExit("Сервер открыт для сети (HANDBOOK_HOST=" + HOST + "), но пароль не задан. "
                         "Задайте HANDBOOK_PASSWORD или слушайте только этот компьютер (HANDBOOK_HOST=127.0.0.1).")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
