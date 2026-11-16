# проверка поиска на samples/: запросы из samples/search_queries.json, ответ - нужный документ в выдаче.
# lexical - запросы словами из документа (в том числе в другой форме), paraphrase - своими словами (синонимы).
# запуск: python tools/eval_search.py [-v]
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
os.environ["HANDBOOK_DB"] = os.path.join(tmp, "eval.sqlite3")

import app as hb  # noqa: E402
import classify  # noqa: E402
import searchindex as index  # noqa: E402


def load():
    index.init_db()
    index.seed_folders(classify.FOLDER_TREE)
    manifest = json.load(open(os.path.join(ROOT, "samples", "manifest.json"), encoding="utf-8"))
    t0 = time.time()
    for m in manifest:
        path = os.path.join(ROOT, "samples", m["file"])
        doc_id = "s-" + uuid.uuid4().hex[:8]
        index.add_document(doc_id, m["folder"], m["file"], path, os.path.getsize(path), "-", sample=True)
        hb.ingest(doc_id)
    print(f"разбор {len(manifest)} документов: {time.time() - t0:.0f} с")


def rank_of(res, wants, section=None):
    """номер документа в выдаче (с 1), 0 - не найден"""
    seen = []
    for r in res["results"]:
        if r["doc_id"] not in seen:
            seen.append(r["doc_id"])
        if any(w in r["doc_name"] for w in wants) and (section is None or r["section"] == section):
            return seen.index(r["doc_id"]) + 1
    return 0


def run_set(items, verbose):
    ranks, times = [], []
    for it in items:
        t0 = time.perf_counter()
        res = index.search(it["q"])
        times.append((time.perf_counter() - t0) * 1000)
        rk = rank_of(res, it["doc"], it.get("section"))
        ranks.append(rk)
        if verbose or rk != 1:
            print(f"  {'ok ' if rk == 1 else ('top3' if 0 < rk <= 3 else 'НЕТ ')} [{it['kind']:12}] {it['q']!r}: место {rk or '-'}")
    n = len(items)
    top1 = sum(1 for r in ranks if r == 1)
    top3 = sum(1 for r in ranks if 0 < r <= 3)
    top10 = sum(1 for r in ranks if 0 < r <= 10)
    return n, top1, top3, top10, times, ranks


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    queries = json.load(open(os.path.join(ROOT, "samples", "search_queries.json"), encoding="utf-8"))
    load()
    for name in ("lexical", "paraphrase"):
        print(f"\n=== {name} ===")
        n, top1, top3, top10, times, ranks = run_set(queries[name], verbose)
        print(f"запросов {n}: нужный документ первым {top1}, в первых трёх {top3}, в первых десяти {top10}; "
              f"ответ в среднем {statistics.mean(times):.0f} мс, максимум {max(times):.0f} мс")
