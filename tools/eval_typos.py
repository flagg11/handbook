# проверка исправления опечаток и неверной раскладки.
# Из запросов samples/search_queries.json (lexical) делаются испорченные варианты:
#   перестановка двух соседних букв, пропуск буквы, лишняя буква, соседняя клавиша, запрос в английской раскладке.
# Для каждого варианта смотрим, где нужный документ: без исправления (fix=False) и с ним (fix=True).
# Отдельно проверяется, что правильные запросы исправление не трогает.
# запуск: python tools/eval_typos.py [-v]
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_search as es  # noqa: E402  (строит временную базу из samples/)

index = es.index
RU = "йцукенгшщзхъфывапролджэячсмитьбю"
EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
KEYS = {**dict(zip(RU, EN)), **{r.upper(): e.upper() for r, e in zip(RU, EN) if e.isalpha()}, "ё": "`", "Ё": "~"}
ROWS = ["йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"]


def neighbour(ch):
    for row in ROWS:
        i = row.find(ch.lower())
        if i >= 0:
            return row[i + 1] if i + 1 < len(row) else row[i - 1]
    return ch


def target_word(q):
    ws = [w for w in index.WORD_RE.findall(q) if w.isalpha() and len(w) >= 5 and w.lower() not in index.STOP]
    return max(ws, key=len) if ws else None


def damage(word, kind):
    i = len(word) // 2
    if kind == "перестановка":
        return word[:i - 1] + word[i] + word[i - 1] + word[i + 1:]
    if kind == "пропуск":
        return word[:i] + word[i + 1:]
    if kind == "лишняя":
        return word[:i] + word[i] + word[i:]
    if kind == "соседняя клавиша":
        return word[:i] + neighbour(word[i]) + word[i + 1:]


def variants(items):
    out = []
    for it in items:
        if index.SECTION_RE.match(it["q"]):
            continue
        w = target_word(it["q"])
        if w:
            for kind in ("перестановка", "пропуск", "лишняя", "соседняя клавиша"):
                bad = damage(w, kind)
                if bad != w:
                    out.append({**it, "q": it["q"].replace(w, bad, 1), "kind": kind, "orig": it["q"]})
        if any(c in KEYS for c in it["q"]):
            out.append({**it, "q": "".join(KEYS.get(c, c) for c in it["q"]), "kind": "раскладка", "orig": it["q"]})
    return out


def score(items, fix):
    ranks, corrected = [], 0
    for it in items:
        res = index.search(it["q"], fix=fix)
        corrected += 1 if res.get("corrected") else 0
        ranks.append(es.rank_of(res, it["doc"], it.get("section")))
    return ranks, corrected


if __name__ == "__main__":
    verbose = "-v" in sys.argv
    queries = json.load(open(os.path.join(es.ROOT, "samples", "search_queries.json"), encoding="utf-8"))
    es.load()
    items = variants(queries["lexical"])
    print(f"\nиспорченных запросов: {len(items)}")
    r0, _ = score(items, False)
    r1, nfix = score(items, True)
    print(f"{'вид':18}{'всего':>6}{'без исправления: 1-м / в топ-3':>34}{'с исправлением: 1-м / в топ-3':>32}")
    for kind in ("перестановка", "пропуск", "лишняя", "соседняя клавиша", "раскладка"):
        idx = [i for i, it in enumerate(items) if it["kind"] == kind]
        f = lambda rs: (sum(1 for i in idx if rs[i] == 1), sum(1 for i in idx if 0 < rs[i] <= 3))
        a, b = f(r0), f(r1)
        print(f"{kind:18}{len(idx):>6}{a[0]:>20} /{a[1]:>3}{b[0]:>22} /{b[1]:>3}")
    a1, a3 = sum(1 for r in r0 if r == 1), sum(1 for r in r0 if 0 < r <= 3)
    b1, b3 = sum(1 for r in r1 if r == 1), sum(1 for r in r1 if 0 < r <= 3)
    print(f"{'итого':18}{len(items):>6}{a1:>20} /{a3:>3}{b1:>22} /{b3:>3}   (исправление сработало: {nfix})")
    if verbose or True:
        for it, a, b in zip(items, r0, r1):
            if b != 1:
                res = index.search(it["q"])
                c = (res.get("corrected") or {}).get("query")
                print(f"  не первым [{it['kind']}] {it['q']!r} (было {it['orig']!r}): место {b or '-'}, исправлено в {c!r}")

    # правильные запросы исправление трогать не должно
    clean = queries["lexical"] + queries["paraphrase"]
    touched = []
    for it in clean:
        res = index.search(it["q"])
        if res.get("corrected"):
            touched.append((it["q"], res["corrected"]["query"]))
    print(f"\nправильные запросы ({len(clean)}): исправление сработало {len(touched)}")
    for q, c in touched:
        print(f"  {q!r} -> {c!r}")
    import time
    t0 = time.perf_counter()
    for it in items:
        index.search(it["q"])
    print(f"среднее время ответа на испорченный запрос: {(time.perf_counter() - t0) / len(items) * 1000:.0f} мс")
