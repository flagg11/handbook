# как поиск ведёт себя при росте числа документов: учебные файлы размножаются под разными именами.
# для каждого размера: время разбора, размер базы, время ответа и доля запросов, где нужный документ первый.
# запуск: python tools/eval_scale.py [копий_максимум]   (по умолчанию 1, 5, 10 копий набора)
import json
import os
import statistics
import sys
import tempfile
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "scale.sqlite3")
os.environ["HANDBOOK_DB"] = DB

import app as hb  # noqa: E402
import classify  # noqa: E402
import searchindex as index  # noqa: E402


def add_copy(k, manifest):
    for m in manifest:
        path = os.path.join(ROOT, "samples", m["file"])
        doc_id = "s-" + uuid.uuid4().hex[:8]
        index.add_document(doc_id, m["folder"], f"к{k} {m['file']}", path, os.path.getsize(path), "-", sample=True)
        hb.ingest(doc_id)


def measure(queries):
    times, top1 = [], 0
    for it in queries:
        t0 = time.perf_counter()
        res = index.search(it["q"])
        times.append((time.perf_counter() - t0) * 1000)
        r = res["results"][0] if res["results"] else None
        if r and any(w in r["doc_name"] for w in it["doc"]) and (it.get("section") is None or r["section"] == it["section"]):
            top1 += 1
    return statistics.mean(times), max(times), top1


if __name__ == "__main__":
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    sizes = sorted({1, 5, top}) if top >= 5 else [1, top]
    manifest = json.load(open(os.path.join(ROOT, "samples", "manifest.json"), encoding="utf-8"))
    queries = json.load(open(os.path.join(ROOT, "samples", "search_queries.json"), encoding="utf-8"))["lexical"]
    index.init_db()
    index.seed_folders(classify.FOLDER_TREE)
    done = 0
    for size in sizes:
        t0 = time.time()
        for k in range(done + 1, size + 1):
            add_copy(k, manifest)
        done = size
        load_s = time.time() - t0
        mean_ms, max_ms, top1 = measure(queries)
        db_mb = sum(os.path.getsize(os.path.join(tmp, f)) for f in os.listdir(tmp)) / 1e6
        print(f"документов {size * len(manifest):4}: разбор добавленных {load_s:5.0f} с, база {db_mb:5.1f} МБ, "
              f"ответ в среднем {mean_ms:5.1f} мс (макс {max_ms:5.1f}), первым {top1}/{len(queries)}", flush=True)
