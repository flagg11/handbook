# handbook как оболочка над обычной папкой с pdf и word.
# правда - то, что лежит на диске; индекс в data/ отдельно и сами файлы не трогает.
# удаление по умолчанию - в скрытую корзину .handbook_trash
import json
import os
import shutil
import threading
import time
import uuid

import searchindex as index

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("HANDBOOK_CONFIG", os.path.join(BASE_DIR, "data", "config.json"))
TRASH = ".handbook_trash"
ROOTFILES = "rootfiles"  # виртуальная папка для файлов прямо в корне
SKIP_DIRS = {"$recycle.bin", "system volume information", "node_modules"}
EXTS = (".pdf", ".docx")  # word читаем через конвертацию в pdf
MAX_FILES = 50000
SETTLE_SECONDS = 2.0  # файл только что менялся, возможно ещё копируется - ждём следующей проверки

DEFAULTS = {
    "configured": False, "mode": "", "app_name": "Хранилище документов", "root": "",
    "auto_sort": False, "inbox_name": "Входящие", "scan_interval": 30, "ocr": True, "trash": True,
}

_cfg_lock = threading.Lock()
_sync_lock = threading.Lock()
_cfg = None
rev = 0  # растёт при любом изменении файлов, по нему фронт обновляется
state = {"scanning": False, "last_scan": None, "error": ""}


# настройки
def load():
    global _cfg
    with _cfg_lock:
        if _cfg is None:
            _cfg = dict(DEFAULTS)
            try:
                with open(CONFIG_PATH, encoding="utf-8") as fh:
                    _cfg.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
            except (OSError, ValueError):
                pass
        return dict(_cfg)


def save(**changes):
    global _cfg
    cfg = load()
    cfg.update(changes)
    with _cfg_lock:
        _cfg = cfg
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    return dict(cfg)


def configured():
    return bool(load()["configured"])


def is_doc(name):
    n = name.lower()
    return n.endswith(EXTS) and not n.startswith("~$")


def with_ext(name, like=None):
    if name.lower().endswith(EXTS):
        return name
    ext = os.path.splitext(like or "")[1].lower()
    return name + (ext if ext in EXTS else ".pdf")


def active():
    cfg = load()
    return bool(cfg["configured"] and cfg["mode"] == "storage")


def clean_settings(data):
    out = {}
    if "app_name" in data:
        name = " ".join(str(data["app_name"] or "").split())
        if not name:
            raise ValueError("Введите название")
        if len(name) > 40:
            raise ValueError("Название слишком длинное (до 40 символов)")
        out["app_name"] = name
    for key in ("auto_sort", "ocr", "trash"):
        if key in data:
            out[key] = bool(data[key])
    if "scan_interval" in data:
        try:
            v = int(data["scan_interval"])
        except (TypeError, ValueError):
            raise ValueError("Интервал проверки должен быть числом секунд")
        if v != 0 and not 5 <= v <= 86400:
            raise ValueError("Интервал проверки: от 5 секунд до суток или 0 (выключено)")
        out["scan_interval"] = v
    return out


# пути
def root():
    return load()["root"]


def _inside(path):
    r = os.path.realpath(root())
    p = os.path.realpath(path)
    return p == r or p.startswith(r + os.sep)


def abs_of(rel):
    path = os.path.normpath(os.path.join(root(), *[x for x in rel.split("/") if x]))
    if not _inside(path):
        raise ValueError("Путь выходит за пределы хранилища")
    return path


def _join(parent_rel, name):
    return f"{parent_rel}/{name}" if parent_rel else name


def _clean_name(name, what="папки"):
    name = " ".join((name or "").split())
    if not name or name in (".", ".."):
        raise ValueError(f"Введите название {what}")
    if len(name) > 120:
        raise ValueError("Название слишком длинное (до 120 символов)")
    if any(ch in name for ch in '\\/:*?"<>|') or name.startswith("."):
        raise ValueError('В названии нельзя использовать символы \\ / : * ? " < > | и точку в начале')
    return name


def unique_name(dir_abs, name):
    if not os.path.exists(os.path.join(dir_abs, name)):
        return name
    stem, ext = os.path.splitext(name)
    for n in range(2, 1000):
        cand = f"{stem} ({n}){ext}"
        if not os.path.exists(os.path.join(dir_abs, cand)):
            return cand
    return f"{stem} ({uuid.uuid4().hex[:6]}){ext}"


# выбор папки (до настройки)
def _drives():
    if os.name != "nt":
        return []
    out = []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            if mask & (1 << i):
                root_ = f"{c}:\\"
                kind = ctypes.windll.kernel32.GetDriveTypeW(root_)
                out.append((root_, kind == 4))  # сетевой диск
    except Exception:
        out = [(f"{c}:\\", False) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
    return out


def _is_unc(path):
    return path.startswith("\\\\") or path.startswith("//")


def _norm(path):
    path = (path or "").strip().strip('"')
    if os.name == "nt" and _is_unc(path):
        return os.path.normpath("\\\\" + path.replace("/", "\\").lstrip("\\"))
    return os.path.abspath(os.path.expanduser(path))


def browse(path):
    path = (path or "").strip()
    if not path:
        home = os.path.expanduser("~")
        drives = _drives()
        dirs_ = [{"name": r + ("  (сетевой диск)" if net else ""), "path": r, "net": net} for r, net in drives] or [{"name": "/", "path": "/"}]
        if os.name != "nt":
            for mnt in ("/mnt", "/media", "/Volumes"):
                if os.path.isdir(mnt):
                    dirs_.append({"name": mnt + "  (подключённые диски и сетевые ресурсы)", "path": mnt})
        return {"path": "", "parent": None, "net_hint": os.name == "nt", "dirs": dirs_ +
                ([{"name": "Домашняя папка", "path": home}] if os.path.isdir(home) else []), "pdfs": 0}
    path = _norm(path)
    if not os.path.isdir(path):
        raise ValueError("Папка не найдена или недоступна" + (" (проверьте сетевой путь и права доступа)" if _is_unc(path) else ""))
    dirs, pdfs = [], 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.name.startswith(".") or e.name.lower() in SKIP_DIRS:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        dirs.append({"name": e.name, "path": e.path})
                    elif e.is_file() and is_doc(e.name):
                        pdfs += 1
                except OSError:
                    continue
    except PermissionError:
        raise ValueError("Нет доступа к этой папке")
    dirs.sort(key=lambda d: d["name"].lower())
    parent = os.path.dirname(path)
    if parent == path or (os.name == "nt" and _is_unc(path) and path.rstrip("\\").count("\\") <= 3):
        parent = ""
    return {"path": path, "parent": parent, "dirs": dirs, "pdfs": pdfs}


def probe(path):
    path = _norm(path)
    if not os.path.isdir(path):
        raise ValueError("Папка не найдена или недоступна" + (" (проверьте сетевой путь и права доступа)" if _is_unc(path) else ""))
    dirs = files = size = 0
    t0 = time.time()
    capped = False
    for base, names, fnames in os.walk(path):
        names[:] = [n for n in names if not n.startswith(".") and n.lower() not in SKIP_DIRS]
        dirs += len(names)
        for f in fnames:
            if is_doc(f):
                files += 1
                try:
                    size += os.path.getsize(os.path.join(base, f))
                except OSError:
                    pass
        if files > MAX_FILES or time.time() - t0 > 4:
            capped = True
            break
    writable = os.access(path, os.W_OK)
    return {"path": path, "dirs": dirs, "pdfs": files, "size": size, "capped": capped, "writable": writable}


# сканирование диска
def _walk(base):
    # недоступное (обрыв сети, нет прав) не считаем удалённым, иначе при сбое сети индекс опустеет
    dirs, files, failed = {}, {}, set()
    stack = [("", base)]
    while stack:
        rel, path = stack.pop()
        try:
            entries = list(os.scandir(path))
        except OSError:
            failed.add(rel)
            continue
        for e in entries:
            try:
                name = e.name
                if name.startswith(".") or name.lower() in SKIP_DIRS:
                    continue
                crel = _join(rel, name)
                if e.is_dir(follow_symlinks=False):
                    dirs[crel] = e.path
                    stack.append((crel, e.path))
                elif e.is_file(follow_symlinks=False) and is_doc(name):  # ссылки на файлы снаружи не читаем
                    st = e.stat()
                    files[crel] = (e.path, st.st_size, st.st_mtime)
            except OSError:
                failed.add(rel)
                continue
        if len(files) > MAX_FILES:
            break
    return dirs, files, failed


def ensure_inbox():
    cfg = load()
    name = cfg["inbox_name"]
    folders = index.st_folders()
    if any(f["id"] == index.INBOX for f in folders):
        return
    existing = next((f for f in folders if f["rel"].lower() == name.lower()), None)
    if existing:
        index.st_retag_folder(existing["id"], index.INBOX)
        index.st_update_folder(index.INBOX, system=1)
        return
    path = os.path.join(root(), name)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return
    index.st_add_folder(index.INBOX, None, name, name, system=True)


def sync(submit):
    global rev
    cfg = load()
    if not (cfg["configured"] and cfg["mode"] == "storage"):
        return False
    with _sync_lock:
        state["scanning"] = True
        try:
            base = cfg["root"]
            if not os.path.isdir(base):
                state["error"] = "Папка хранилища недоступна: " + base
                return False
            state["error"] = ""
            if cfg["auto_sort"]:
                ensure_inbox()
            dirs, files, failed = _walk(base)
            if "" in failed:
                state["error"] = "Не удаётся прочитать папку хранилища: " + base
                return False
            if failed:
                state["error"] = "Часть папок сейчас недоступна, их содержимое не изменено: " + ", ".join(sorted(failed)[:3])
            unknown = lambda r: any(r == f or r.startswith(f + "/") for f in failed)
            changed = False
            fol = {f["rel"]: f for f in index.st_folders()}

            # сначала родители
            for rel in sorted(dirs, key=lambda r: r.count("/")):
                if rel in fol:
                    continue
                parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
                parent = fol[parent_rel]["id"] if parent_rel else None
                fid = "d-" + uuid.uuid4().hex[:10]
                index.st_add_folder(fid, parent, rel.rsplit("/", 1)[-1], rel)
                fol[rel] = {"id": fid, "rel": rel, "parent_id": parent, "name": rel.rsplit("/", 1)[-1]}
                changed = True
            if cfg["auto_sort"]:
                ib = next((f for f in fol.values() if f["rel"].lower() == cfg["inbox_name"].lower() and "/" not in f["rel"]), None)
                if ib and ib["id"] != index.INBOX and not any(f["id"] == index.INBOX for f in fol.values()):
                    index.st_retag_folder(ib["id"], index.INBOX)
                    index.st_update_folder(index.INBOX, system=1)
                    fol[ib["rel"]]["id"] = index.INBOX
            has_root_files = any("/" not in r for r in files)
            if has_root_files and ROOTFILES not in {f["id"] for f in fol.values()}:
                index.st_add_folder(ROOTFILES, None, "Файлы в корне", "", system=True)
                fol[""] = {"id": ROOTFILES, "rel": "", "parent_id": None, "name": "Файлы в корне"}
                changed = True
            folder_of = lambda rel: fol[rel.rsplit("/", 1)[0] if "/" in rel else ""]["id"]

            # файлы
            docs = {d["rel"]: d for d in index.st_docs()}
            now = time.time()
            gone = [d for rel, d in docs.items() if rel not in files and not unknown(rel)]
            fresh = []
            for rel, (path, size, mtime) in files.items():
                d = docs.get(rel)
                if d is None:
                    if now - mtime < SETTLE_SECONDS:
                        continue
                    fresh.append(rel)
                elif (d["size_bytes"] != size or abs((d["mtime"] or 0) - mtime) > 1) and now - mtime >= SETTLE_SECONDS:
                    if d["status"] != "processing":
                        index.st_update_doc(d["id"], size_bytes=size, mtime=mtime)
                        index.restart_processing(d["id"])
                        _drop_caches(d["id"])
                        submit(d["id"])
                        changed = True
                    else:
                        index.st_update_doc(d["id"], size_bytes=size, mtime=mtime)
                else:
                    if d["folder"] != folder_of(rel) or d["path"] != path:
                        index.st_update_doc(d["id"], folder=folder_of(rel), path=path)
                        changed = True
            # если файл перенесли снаружи - узнаём по размеру и времени, чтобы не терять индекс
            for rel in list(fresh):
                path, size, mtime = files[rel]
                match = next((g for g in gone if g["size_bytes"] == size and abs((g["mtime"] or 0) - mtime) <= 1), None)
                if match:
                    gone.remove(match)
                    fresh.remove(rel)
                    index.st_update_doc(match["id"], folder=folder_of(rel), name=os.path.basename(rel), path=path, rel=rel)
                    changed = True
            for g in gone:
                index.delete_document(g["id"])
                _drop_caches(g["id"])
                changed = True
            for rel in fresh:
                path, size, mtime = files[rel]
                fid = folder_of(rel)
                doc_id = "s-" + uuid.uuid4().hex[:12]
                index.add_document(doc_id, fid, os.path.basename(rel), path, size, "Хранилище",
                                   want_sort=bool(cfg["auto_sort"] and fid == index.INBOX), rel=rel, mtime=mtime)
                submit(doc_id)
                changed = True

            # пропавшие папки - в конце, чтобы не потерять перенесённые файлы
            wanted = set(dirs) | ({""} if has_root_files else set())
            drop = [f["id"] for f in fol.values() if f["rel"] not in wanted and f["id"] != index.INBOX
                    and not (f["rel"] and unknown(f["rel"]))]
            if drop:
                index.st_delete_folders(drop)
                changed = True
            if changed:
                rev += 1
            state["last_scan"] = time.time()
            return changed
        finally:
            state["scanning"] = False


on_drop = None  # app.py сюда кладёт функцию, которая чистит кэш картинок


def _drop_caches(doc_id):
    if on_drop:
        on_drop(doc_id)


_scanner = None


def start_scanner(submit):
    global _scanner
    if _scanner and _scanner.is_alive():
        wake.set()
        return
    wake.set()

    def loop():
        last = 0.0
        while True:
            cfg = load()
            interval = int(cfg.get("scan_interval") or 0)
            due = wake.is_set() or (interval and time.time() - last >= interval)
            if due and cfg["configured"] and cfg["mode"] == "storage":
                wake.clear()
                try:
                    sync(submit)
                except Exception as exc:  # один кривой файл не должен ронять всю проверку
                    state["error"] = f"Ошибка проверки: {exc}"
                last = time.time()
            wake.wait(1.0)

    wake_thread = threading.Thread(target=loop, name="storage-scanner", daemon=True)
    _scanner = wake_thread
    wake_thread.start()


wake = threading.Event()


# операции с файлами
def _folder_row(fid):
    f = index.get_folder(fid)
    if not f or f.get("rel") is None:
        raise LookupError("Папка не найдена")
    return f


def _rewrite_subtree(old_rel, new_rel):
    prefix = old_rel + "/"
    for f in index.st_folders():
        if f["rel"] == old_rel:
            index.st_update_folder(f["id"], rel=new_rel)
        elif f["rel"].startswith(prefix):
            index.st_update_folder(f["id"], rel=new_rel + "/" + f["rel"][len(prefix):])
    for d in index.st_docs():
        if d["rel"].startswith(prefix):
            nr = new_rel + "/" + d["rel"][len(prefix):]
            index.st_update_doc(d["id"], rel=nr, path=abs_of(nr))


def create_folder(name, parent_id):
    name = _clean_name(name)
    parent_rel = ""
    if parent_id:
        parent = _folder_row(parent_id)
        parent_rel = parent["rel"]
        if parent_id == ROOTFILES:
            raise ValueError("В эту папку нельзя вложить папку")
    rel = _join(parent_rel, name)
    path = abs_of(rel)
    if os.path.exists(path):
        raise ValueError("В этой папке уже есть папка или файл с таким названием")
    try:
        os.mkdir(path)
    except OSError as exc:
        raise ValueError(f"Не удалось создать папку: {exc.strerror or exc}")
    fid = "d-" + uuid.uuid4().hex[:10]
    index.st_add_folder(fid, parent_id or None, name, rel)
    return index.get_folder(fid)


def update_folder(fid, name=None, parent_id="__keep__"):
    f = _folder_row(fid)
    if f["system"]:
        raise ValueError("Системную папку нельзя изменить")
    new_name = _clean_name(name) if name is not None else f["name"]
    new_parent = f["parent_id"] if parent_id == "__keep__" else (parent_id or None)
    parent_rel = ""
    if new_parent:
        if new_parent == ROOTFILES:
            raise ValueError("В эту папку нельзя вложить папку")
        parent_rel = _folder_row(new_parent)["rel"]
        if parent_rel == f["rel"] or parent_rel.startswith(f["rel"] + "/"):
            raise ValueError("Нельзя переместить папку саму в себя")
    new_rel = _join(parent_rel, new_name)
    if new_rel != f["rel"]:
        dst = abs_of(new_rel)
        if os.path.exists(dst):
            raise ValueError("В этой папке уже есть папка или файл с таким названием")
        try:
            os.rename(abs_of(f["rel"]), dst)
        except OSError as exc:
            raise ValueError(f"Не удалось переименовать: {exc.strerror or exc}")
        _rewrite_subtree(f["rel"], new_rel)
    index.st_update_folder(fid, name=new_name, parent_id=new_parent)
    return index.get_folder(fid)


def _to_trash(path):
    cfg = load()
    if not cfg["trash"]:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return
    tdir = os.path.join(root(), TRASH)
    os.makedirs(tdir, exist_ok=True)
    dst = os.path.join(tdir, time.strftime("%Y%m%d-%H%M%S_") + os.path.basename(path))
    dst = os.path.join(tdir, unique_name(tdir, os.path.basename(dst)))
    shutil.move(path, dst)


def delete_folder(fid):
    f = _folder_row(fid)
    if f["system"]:
        raise ValueError("Системную папку нельзя удалить")
    ids = index.descendants(fid)
    marks = set(ids)
    docs = [d for d in index.list_documents() if d["folder"] in marks]
    try:
        _to_trash(abs_of(f["rel"]))
    except OSError as exc:
        raise ValueError(f"Не удалось удалить: {exc.strerror or exc}")
    for d in docs:
        index.delete_document(d["id"])
    index.st_delete_folders(ids)
    return docs


def save_upload(file, folder_id, want_sort=False, validate=None):
    if folder_id == index.INBOX:
        ensure_inbox()
    f = _folder_row(folder_id)
    dir_abs = abs_of(f["rel"])
    original = os.path.basename((file.filename or "").replace("\\", "/"))
    name = _clean_name(with_ext(original), "файла")
    name = unique_name(dir_abs, name)
    dest = os.path.join(dir_abs, name)
    file.save(dest)
    if validate and not validate(dest, os.path.splitext(name)[1].lower()):
        os.remove(dest)
        raise ValueError("Файл повреждён или его содержимое не соответствует формату")
    st = os.stat(dest)
    doc_id = "s-" + uuid.uuid4().hex[:12]
    index.add_document(doc_id, folder_id, name, dest, st.st_size, "Вы", want_sort=want_sort,
                       rel=_join(f["rel"], name), mtime=st.st_mtime)
    return doc_id


def rename_doc(doc_id, name):
    d = index.get_document(doc_id)
    name = " ".join((name or "").split())
    name = _clean_name(with_ext(name, d["name"]), "файла")
    parent_rel = d["rel"].rsplit("/", 1)[0] if "/" in d["rel"] else ""
    new_rel = _join(parent_rel, name)
    if new_rel == d["rel"]:
        return
    dst = abs_of(new_rel)
    if os.path.exists(dst):
        raise ValueError("В этой папке уже есть файл с таким названием")
    try:
        os.rename(d["path"], dst)
    except OSError as exc:
        raise ValueError(f"Не удалось переименовать: {exc.strerror or exc}")
    index.st_update_doc(doc_id, name=name, rel=new_rel, path=dst)


def move_doc(doc_id, folder_id, **meta):
    d = index.get_document(doc_id)
    if d is None:
        raise LookupError("Файл не найден")
    if folder_id == index.INBOX:
        ensure_inbox()
    f = _folder_row(folder_id)
    if d["folder"] != folder_id:
        dir_abs = abs_of(f["rel"])
        name = unique_name(dir_abs, d["name"])
        dst = os.path.join(dir_abs, name)
        try:
            shutil.move(d["path"], dst)
        except OSError as exc:
            raise ValueError(f"Не удалось перенести: {exc.strerror or exc}")
        index.st_update_doc(doc_id, name=name, rel=_join(f["rel"], name), path=dst)
    index.move_document(doc_id, folder_id, **meta)


def delete_doc(doc_id):
    d = index.get_document(doc_id)
    if d is None:
        raise LookupError("Файл не найден")
    if os.path.exists(d["path"]):
        try:
            _to_trash(d["path"])
        except OSError as exc:
            raise ValueError(f"Не удалось удалить: {exc.strerror or exc}")
    index.delete_document(doc_id)
    return d


def usage():
    docs = index.list_documents()
    used = sum(d["size_bytes"] or 0 for d in docs)
    try:
        du = shutil.disk_usage(root() if active() and os.path.isdir(root()) else BASE_DIR)
        total, free = du.total, du.free
    except OSError:
        total = free = 0
    return {"used": used, "total": total, "free": free}
