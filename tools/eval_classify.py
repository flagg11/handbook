# проверка автосортировки на samples/ и demo_upload/ (имена файлов классификатор не видит).
# документ при оценке выкидывается из «обучения» своей папки, чтобы не узнавал сам себя.
# запуск: python tools/eval_classify.py [-v]
import json
import os
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["HANDBOOK_DB"] = os.path.join(tmp, "eval.sqlite3")

import app as hb  # noqa: E402
import classify  # noqa: E402
import searchindex as index  # noqa: E402


def run(verbose=False, use_similarity=True):
    classify.W_SIM = 0.20 if use_similarity else 0.0
    expected = json.load(open(os.path.join(ROOT, "samples", "expected_folders.json"), encoding="utf-8"))
    index.init_db()
    index.seed_folders(classify.FOLDER_TREE)
    seed = {m["file"]: m for m in json.load(open(os.path.join(ROOT, "samples", "manifest.json"), encoding="utf-8"))}
    ids = {}
    for fname, folder in expected.items():
        in_samples = fname in seed
        path = os.path.join(ROOT, "samples" if in_samples else "demo_upload", fname)
        doc_id = "t-" + uuid.uuid4().hex[:8]
        index.add_document(doc_id, folder if in_samples else index.INBOX, fname, path, os.path.getsize(path),
                           "-", sample=True)
        hb.ingest(doc_id)
        ids[fname] = doc_id

    fmap = {f["id"]: f for f in index.list_folders()}
    rows, exact, section_ok, safe_inbox, wrong = [], 0, 0, 0, 0
    for fname, want in expected.items():
        decision = classify.classify_document(ids[fname])
        got = decision["folder"]
        want_id = want or index.INBOX
        if got == want_id:
            verdict, exact = "верно", exact + 1
        elif got == fmap[want_id]["parent_id"] if want_id in fmap and fmap[want_id]["parent_id"] else False:
            verdict, section_ok = "в общий раздел", section_ok + 1
        elif got == index.INBOX:
            verdict, safe_inbox = "во Входящие", safe_inbox + 1
        else:
            verdict, wrong = "ОШИБКА", wrong + 1
        rows.append((fname, want_id, got, decision["confidence"], verdict, decision["reason"]))
    n = len(expected)
    print(f"{'файл':56} {'ожидалось':14} {'получено':14} {'увер.':>5}  итог")
    for fname, want, got, conf, verdict, reason in rows:
        print(f"{fname[:56]:56} {want:14} {got:14} {conf:5.2f}  {verdict}")
        if verbose or verdict not in ("верно",):
            print(f"      {reason}")
    print(f"\nВсего {n}: точно в нужную папку {exact}, в общий раздел {section_ok}, "
          f"осторожно во Входящие {safe_inbox}, в неверную папку {wrong}")
    return exact, section_ok, safe_inbox, wrong, n


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    print("=== с учётом сходства с файлами папок ===")
    run(verbose, True)
