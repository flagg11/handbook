# проверка дублей, сроков действия и редакций через настоящие запросы к приложению (на временной базе).
# запуск: python tools/test_docmeta.py
import io
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["HANDBOOK_DB"] = os.path.join(tmp, "t.sqlite3")

import app as hb  # noqa: E402
import classify  # noqa: E402
import searchindex as index  # noqa: E402

hb.UPLOAD_DIR = os.path.join(tmp, "uploads")
index.init_db()
index.seed_folders(classify.FOLDER_TREE)
hb.storage.configured = lambda: True
hb.storage.active = lambda: False
c = hb.app.test_client()
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def upload(data, name, **form):
    return c.post("/api/upload", data={"file": (io.BytesIO(data), name), "folder": "ot-height", **form},
                  content_type="multipart/form-data")


def wait_indexed(doc_id):
    for _ in range(120):
        d = index.get_document(doc_id)
        if d and d["status"] in ("indexed", "error"):
            return d
        time.sleep(0.5)


src = sorted(f for f in os.listdir(os.path.join(ROOT, "samples")) if f.endswith(".docx"))[0]
raw = open(os.path.join(ROOT, "samples", src), "rb").read()

# дубли
r1 = upload(raw, src)
check("первая загрузка проходит", r1.status_code == 201)
a = r1.get_json()["id"]
doc_a = wait_indexed(a)
check("файл разобран", doc_a and doc_a["status"] == "indexed", str(doc_a and doc_a["error"]))
r2 = upload(raw, "копия.docx")
j2 = r2.get_json()
check("такой же файл под другим именем отклонён как дубль", r2.status_code == 409 and j2["duplicate"]["id"] == a, str(j2))
check("в списке файлов дубль не появился", len(c.get("/api/uploads").get_json()) == 1)
r3 = upload(raw, "копия.docx", dup="keep")
check("с подтверждением дубль загружается", r3.status_code == 201)
b = r3.get_json()["id"]
wait_indexed(b)
lst = {d["id"]: d for d in c.get("/api/uploads").get_json()}
check("у копии указан оригинал", lst[b]["dup_of"] and lst[b]["dup_of"]["id"] == a)
check("у оригинала дубля нет", lst[a]["dup_of"] is None)
r4 = upload(raw + b"x", "другой.docx")
check("изменённый файл дублем не считается", r4.status_code in (201, 400), str(r4.status_code))

# сроки
today = time.strftime("%Y-%m-%d")
past = time.strftime("%Y-%m-%d", time.localtime(time.time() - 40 * 86400))
soon = time.strftime("%Y-%m-%d", time.localtime(time.time() + 10 * 86400))
far = time.strftime("%Y-%m-%d", time.localtime(time.time() + 400 * 86400))
r = c.patch(f"/api/docs/{a}", json={"valid_until": past, "review_until": soon, "edition": "ред. 3"})
t = r.get_json()
check("сроки сохраняются", r.status_code == 200 and t["valid_until"] == past and t["edition"] == "ред. 3", str(t))
check("истёкший срок помечен", t["term"]["valid_state"] == "expired" and t["term"]["valid_days"] == -40, str(t["term"]))
check("скорый пересмотр помечен", t["term"]["review_state"] == "soon", str(t["term"]))
check("неверная дата отклоняется", c.patch(f"/api/docs/{a}", json={"valid_until": "31.12.2026"}).status_code == 400)
check("несуществующая дата отклоняется", c.patch(f"/api/docs/{a}", json={"valid_until": "2026-02-30"}).status_code == 400)
t = c.patch(f"/api/docs/{a}", json={"valid_until": far, "review_until": ""}).get_json()
check("далёкий срок - без пометки, пустое поле очищает", t["term"]["valid_state"] == "ok" and t["review_until"] is None and t["term"]["review_state"] == "")
c.patch(f"/api/docs/{a}", json={"valid_until": past})
q = re.findall(r"[А-Яа-я]{6,}", " ".join(ch["text"] for ch in index.document_chunks(a)))[0]
res = c.get("/api/search", query_string={"q": q}).get_json()["results"]
hit = next(x for x in res if x["doc_id"] == a)
check("в выдаче поиска видна пометка о сроке", hit["term"]["valid_state"] == "expired" and hit["valid_until"] == past)

# редакции
before = {x["doc_id"] for x in c.get("/api/search", query_string={"q": q}).get_json()["results"]}
check("до замены находятся оба файла", {a, b} <= before, str(before))
r = c.post(f"/api/docs/{a}/supersede", json={"by": b})
check("отметка о замене ставится", r.status_code == 200 and r.get_json()["superseded_by"] == b)
after = {x["doc_id"] for x in c.get("/api/search", query_string={"q": q}).get_json()["results"]}
check("заменённая редакция пропала из поиска", a not in after and b in after, str(after))
withold = {x["doc_id"] for x in c.get("/api/search", query_string={"q": q, "old": "1"}).get_json()["results"]}
check("с галочкой «показывать заменённые» она снова видна", a in withold)
lst = {d["id"]: d for d in c.get("/api/uploads").get_json()}
check("в списке видно, кто кого заменил", lst[a]["superseded_by_name"] and lst[b]["replaces"] == a)
check("замкнутая цепочка запрещена", c.post(f"/api/docs/{b}/supersede", json={"by": a}).status_code == 400)
check("файл не может заменять сам себя", c.post(f"/api/docs/{a}/supersede", json={"by": a}).status_code == 400)
c.delete(f"/api/docs/{a}/supersede")
check("отметку можно снять", c.get("/api/uploads").get_json()[0]["superseded_by"] is None)
c.post(f"/api/docs/{a}/supersede", json={"by": b})

# история редакций: a -> b -> e
r5 = upload(raw, "ред3.docx", dup="keep")
e = r5.get_json()["id"]
c.post(f"/api/docs/{b}/supersede", json={"by": e})
for start in (a, b, e):
    ch = c.get(f"/api/docs/{start}/editions").get_json()
    ids = [x["id"] for x in ch["items"]]
    check(f"цепочка редакций видна из любого файла ({start[:6]})", ids == [a, b, e] and ch["current"] == start, str(ids))
chain = c.get(f"/api/docs/{a}/editions").get_json()["items"]
check("актуальной помечена только последняя", [bool(x["superseded_by"]) for x in chain] == [True, True, False])
lst = {d["id"]: d for d in c.get("/api/uploads").get_json()}
check("у каждого файла цепочки указано число редакций", all(lst[i]["editions"] == 3 for i in (a, b, e)))
check("у файла вне цепочки редакция одна", all(d["editions"] == 1 for d in lst.values() if d["id"] not in (a, b, e)))
check("для несуществующего файла - 404", c.get("/api/docs/нет/editions").status_code == 404)
c.delete(f"/api/upload/{e}")
c.delete(f"/api/upload/{b}")
check("если новую редакцию удалили, прежняя снова актуальна", index.get_document(a)["superseded_by"] in (None, ""))

print("\nНЕ ПРОШЛО: " + ", ".join(fails) if fails else "\nвсе проверки пройдены")
sys.exit(1 if fails else 0)
