# автосортировка по папкам, только по тексту (имя файла не смотрим).
# оценка папки: заголовок + ключевые слова + похожесть на то, что в ней уже лежит.
# не уверены - остаётся во «Входящих» с пометкой; если колеблются соседние папки - кладём в раздел выше
import math
import re
from collections import Counter

import searchindex as si

HEAD_CHARS = 500
ACCEPT = 0.40  # минимум для лучшей папки
MARGIN = 0.06  # минимальный отрыв от второй
W_HEAD, W_KW, W_SIM = 0.40, 0.40, 0.20
HEAD_MISS_PENALTY = 0.6
TITLE_ZONE = 160  # сколько символов с начала считаем названием

TK = [r"технологическ\w+\s+карт", r"карт\w+\s+технологическ", r"\bтк[-\s]?\d"]

# (id, родитель, название, подсказки, системная)
FOLDER_TREE = [
    ("tk", None, "Технологические карты", None, False),
    ("tk-vent", "tk", "Вентиляция и кондиционирование", {
        "head": TK, "sat": 3,
        "kw": ["вентиляция", "вентилятор", "кондиционер", "фильтр", "фильтроэлемент", "воздуховод", "приточный",
               "вытяжной", "калорифер", "чиллер", "воздухообмен", "дифманометр", "вентиляционный"]}, False),
    ("tk-el", "tk", "Электроустановки и СЦБ", {
        "head": TK, "sat": 3,
        "kw": ["стрелочный", "электропривод", "светофор", "сцб", "реле", "релейный", "автоблокировка", "кабель",
               "дроссель", "рельсовая", "электрооборудование", "контакт", "блокировка"]}, False),
    ("tk-track", "tk", "Путевое хозяйство", {
        "head": TK, "sat": 3,
        "kw": ["рельс", "шпала", "балласт", "щебень", "выправка", "подбивка", "колея", "путь", "стык", "накладка",
               "рельсовый", "костыль", "путевой"]}, False),

    ("ot", None, "Охрана труда", None, False),
    ("ot-instr", "ot", "Инструкции по охране труда", {
        "head": [r"инструкци\w+\s+(?:№\s*\d+\s+)?по\s+охране\s+труда",
                 r"инструкци\w+\s+(?:№\s*\d+\s+)?по\s+(?:\bот\b|электробезопасности|технике безопасности)"],
        "sat": 3,
        "kw": ["охрана", "труд", "инструктаж", "спецодежда", "защиты", "пострадавший", "несчастный", "допуск",
               "безопасность", "травма", "наряд"]}, False),
    ("ot-height", "ot", "Работы на высоте", {
        "head": [r"работ\w*\s+на\s+высоте", r"при\s+работе\s+на\s+высоте"], "sat": 3,
        "kw": ["высота", "страховочный", "привязь", "каска", "лестница", "леса", "подмости", "падение", "строп",
               "карабин", "люлька", "ограждение"]}, False),
    ("ot-fire", "ot", "Пожарная безопасность", {
        "head": [r"пожарн\w+\s+безопасност", r"противопожарн", r"мерах\s+пожарной"], "sat": 3,
        "kw": ["пожар", "огнетушитель", "эвакуация", "возгорание", "пожарный", "горючий", "курение", "дым",
               "противопожарный", "гидрант"]}, False),

    ("norm", None, "Нормативные документы", None, False),
    ("norm-regs", "norm", "Регламенты и положения", {
        "head": [r"^\s*регламент", r"^\s*положени\w+\s+(?:о|об)\b", r"правила\s+внутреннего"] , "sat": 3,
        "kw": ["регламент", "положение", "периодичность", "ответственность", "обслуживание", "график", "порядок",
               "контроль", "руководитель", "подразделение"]}, False),
    ("norm-std", "norm", "Стандарты и ГОСТы", {
        "head": [r"национальн\w+\s+стандарт", r"\bгост\b", r"стандарт\s+организации", r"межгосударственн\w+\s+стандарт",
                 r"строительные\s+нормы"], "sat": 3,
        "kw": ["стандарт", "гост", "технические", "условия", "испытание", "классификация", "термины", "определения",
               "нормативные", "ссылки", "область", "применения", "требования"]}, False),

    ("acts", None, "Акты и протоколы", None, False),
    ("acts-insp", "acts", "Акты осмотров и приёмки", {
        "head": [r"^\s*акт\b", r"\bакт\s+(?:осмотра|приёмки|приемки|выполненных|обследования|сдачи)"], "sat": 3,
        "kw": ["осмотр", "комиссия", "приёмка", "замечание", "выявлено", "недостаток", "составлен", "подпись",
               "обследование", "сдача", "заключение", "рекомендовано"]}, False),
    ("acts-test", "acts", "Протоколы испытаний", {
        "head": [r"^\s*протокол", r"протокол\s+(?:№|n|испытани|измерени|проверк|замер)"], "sat": 3,
        "kw": ["испытание", "измерение", "сопротивление", "изоляция", "мегаомметр", "результат", "норма", "годен",
               "прибор", "температура", "давление", "замер", "проверка"]}, False),

    ("fin", None, "Договоры и закупки", None, False),
    ("fin-contracts", "fin", "Договоры", {
        "head": [r"^\s*договор", r"договор\s+(?:подряда|поставки|оказания|аренды|№)"], "sat": 3,
        "kw": ["заказчик", "подрядчик", "исполнитель", "стороны", "предмет", "стоимость", "оплата", "срок",
               "договор", "реквизиты", "неустойка", "расторжение"]}, False),
    ("fin-invoices", "fin", "Счета и накладные", {
        "head": [r"^\s*сч[её]т", r"товарная\s+накладная", r"накладная\s+№", r"сч[её]т-фактура"], "sat": 3,
        "kw": ["наименование", "ндс", "итого", "оплате", "количество", "цена", "сумма", "грузополучатель",
               "поставщик", "плательщик", "товар", "накладная"]}, False),

    ("hr", None, "Кадровые документы", None, False),
    ("hr-orders", "hr", "Приказы", {
        "head": [r"^\s*приказ\b", r"приказываю"], "sat": 3,
        "kw": ["приказываю", "назначить", "основание", "ознакомить", "возложить", "директор", "утвердить",
               "контроль", "исполнение", "приказ"]}, False),
    ("hr-jobs", "hr", "Должностные инструкции", {
        "head": [r"должностн\w+\s+инструкци"], "sat": 3,
        "kw": ["должностной", "обязанности", "права", "подчиняется", "квалификационные", "должность", "назначается",
               "освобождается", "работник", "должность"]}, False),

    (si.INBOX, None, "Входящие", None, True),
]

_counts = {}  # doc_id -> счётчик основ слов


def forget(doc_id):
    _counts.pop(doc_id, None)


def _doc_counts(doc_id):
    if doc_id not in _counts:
        parts = si.document_text(doc_id)
        _counts[doc_id] = Counter(s for p in parts for s in si.stems(p["title"] + " " + p["text"]) if s not in si.STOP)
    return _counts[doc_id]


def _vector(counts, idf):
    vec = {s: (1 + math.log(c)) * idf.get(s, 1.0) for s, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {s: v / norm for s, v in vec.items()}


def _effective_hints(folder, rows):
    h = folder.get("hints")
    if h:
        return h
    words = [w for w in si.WORD_RE.findall(folder["name"]) if len(w) >= 3 and w.lower() not in si.STOP]
    return {"head": [], "kw": words, "sat": 1.5}


def _is_target(folder, rows):
    if folder["id"] == si.INBOX:
        return False
    has_children = any(r["parent_id"] == folder["id"] for r in rows)
    return (not has_children) or bool(folder.get("hints"))


def _ancestors(fid, fmap):
    chain = []
    while fid:
        chain.append(fid)
        fid = fmap[fid]["parent_id"] if fid in fmap else None
    return chain


def classify_parts(head, body_counts, exclude=None, doc_id=None):
    rows = si.list_folders()
    fmap = {r["id"]: r for r in rows}
    targets = [r for r in rows if _is_target(r, rows)]
    head_l = head.lower()
    head_stems = set(si.stems(head))

    docs = [d for d in si.list_documents() if d["status"] == "indexed" and d["id"] != exclude]
    n_docs = len(docs) + 1
    df = Counter()
    for d in docs:
        df.update(_doc_counts(d["id"]).keys())
    df.update(body_counts.keys())
    idf = {s: math.log((n_docs + 1) / (c + 0.5)) + 1 for s, c in df.items()}
    doc_vec = _vector(body_counts, idf)

    members = {}
    for d in docs:
        if d["id"] == doc_id:
            continue
        members.setdefault(d["folder"], []).append(d["id"])

    out = []
    for f in targets:
        hints = _effective_hints(f, rows)
        # заголовок
        # в самом начале (название) вес полный, дальше слабый - акт может ссылаться на «ТК-027»
        head_hit, head_score = None, 0.0
        for pat in hints.get("head", []):
            m = re.search(pat, head_l, re.I | re.M)
            if m:
                s_ = 1.0 if m.start() < TITLE_ZONE else 0.35
                if s_ > head_score:
                    head_hit, head_score = m.group(0).strip(), s_
        # ключевые слова
        count, found = 0.0, []
        for kw in hints.get("kw", []):
            q = si.stem(kw)
            tf = sum(c for s, c in body_counts.items() if si.matches(s, q))
            if tf:
                contrib = min(1.0, 0.5 + 0.25 * (tf - 1)) + (0.5 if any(si.matches(s, q) for s in head_stems) else 0)
                count += contrib
                found.append(kw)
        kw_score = 1 - math.exp(-count / hints.get("sat", 3))
        # похожесть на то, что уже лежит в папке
        sim, sim_n = 0.0, 0
        ids = members.get(f["id"], [])
        if ids:
            centroid = Counter()
            for mid in ids:
                for s, v in _vector(_doc_counts(mid), idf).items():
                    centroid[s] += v
            norm = math.sqrt(sum(v * v for v in centroid.values())) or 1.0
            sim = sum(doc_vec.get(s, 0.0) * v / norm for s, v in centroid.items())
            sim_n = len(ids)
        sim_score = min(1.0, sim / 0.5)
        total = W_HEAD * head_score + W_KW * kw_score + W_SIM * sim_score
        out.append({"folder": f["id"], "name": f["name"], "score": round(total, 3), "head": head_hit, "head_score": head_score,
                    "words": found[:6], "similar": round(sim, 2), "similar_docs": sim_n})
    # если заголовок явно говорит о типе (акт, договор, ТК), а у папки есть свои
    # заголовочные признаки и они не совпали - штраф. иначе «Акт осмотра вентиляции»
    # уедет в ТК по вентиляции
    if any(c["head_score"] >= 1.0 for c in out):
        for c in out:
            if c["head_score"] < 1.0 and _effective_hints(fmap[c["folder"]], rows).get("head"):
                c["score"] = round(c["score"] * HEAD_MISS_PENALTY, 3)
    out.sort(key=lambda c: -c["score"])
    return out, fmap


def decide(cands, fmap):
    if not cands:
        return {"folder": si.INBOX, "confidence": 0.0, "review": True, "reason": "Нет подходящих папок", "candidates": []}
    best = cands[0]
    second = cands[1] if len(cands) > 1 else None
    margin = best["score"] - (second["score"] if second else 0.0)

    def why(c):
        bits = []
        if c["head"]:
            bits.append(f"заголовок «{c['head']}»")
        if c["words"]:
            bits.append("слова: " + ", ".join(c["words"][:5]))
        if c["similar_docs"] and c["similar"] >= 0.15:
            bits.append(f"похож на файлы папки ({c['similar']:.2f})")
        return "; ".join(bits) or "совпадений нет"

    top = [{"folder": c["folder"], "name": c["name"], "score": c["score"]} for c in cands[:3]]
    if best["score"] < ACCEPT:
        return {"folder": si.INBOX, "confidence": best["score"], "review": True, "candidates": top,
                "reason": f"Не удалось определить папку: лучший вариант «{best['name']}» ({int(best['score'] * 100)}%)"}
    if margin < MARGIN and second:
        pa, pb = _ancestors(best["folder"], fmap), _ancestors(second["folder"], fmap)
        common = next((x for x in pa if x in pb), None)
        if common and common != best["folder"]:
            return {"folder": common, "confidence": best["score"], "review": True, "candidates": top,
                    "reason": f"Подходят «{best['name']}» и «{second['name']}» - помещён в общий раздел"}
        return {"folder": si.INBOX, "confidence": best["score"], "review": True, "candidates": top,
                "reason": f"Два равных варианта: «{best['name']}» и «{second['name']}»"}
    return {"folder": best["folder"], "confidence": best["score"], "review": best["score"] < 0.55,
            "reason": why(best), "candidates": top}


def classify_document(doc_id, exclude_self_from_learning=True):
    parts = si.document_text(doc_id)
    full = "\n".join(p["text"] for p in parts)
    head = full[:HEAD_CHARS]
    counts = _doc_counts(doc_id)
    cands, fmap = classify_parts(head, counts, exclude=doc_id if exclude_self_from_learning else None, doc_id=doc_id)
    return decide(cands, fmap)
