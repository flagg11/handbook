# сверка docparse с эталоном, из которого делались pdf (make_samples.py)
# запуск: python tools/eval_ocr.py
import difflib
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import docparse  # noqa: E402
import make_samples  # noqa: E402
import extra_docs  # noqa: E402

extra_docs.register(make_samples.add, make_samples.T)


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def words_of(text):
    return re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", text.lower().replace("ё", "е"))


def main():
    tot_cells = ok_cells = 0
    sim_sum = 0.0
    shape_ok = shape_n = 0
    rec_hit = rec_all = 0
    print(f"{'файл':58} {'тип':5} {'табл.':>5} {'ячейки':>9} {'слова':>7} {'сек':>5}")
    for filename, spec, folder, author, date, where in make_samples.DOCS:
        path = os.path.join(make_samples.OUT if where == "samples" else make_samples.DEMO, filename)
        t0 = time.time()
        res = docparse.parse_pdf(path)
        dt = time.time() - t0
        truth_tables = [b[1] for b in spec["blocks"] if b[0] == "table"]
        got_tables = [c.data for c in res.chunks if c.kind == "table"]
        # слова: все слова эталона должны быть найдены в распознанном тексте
        truth_words = []
        for b in spec["blocks"]:
            if b[0] in ("title", "sub", "h1", "h2", "p"):
                truth_words += words_of(b[1])
            elif b[0] == "table":
                for row in b[1]:
                    for c in row:
                        truth_words += words_of(c)
        got = set(words_of(" ".join(p.text for p in res.pages)))
        hit = sum(1 for w in truth_words if w in got)
        rec_hit += hit
        rec_all += len(truth_words)

        cells = okc = 0
        for t_idx, truth in enumerate(truth_tables):
            shape_n += 1
            gt = got_tables[t_idx] if t_idx < len(got_tables) else []
            if len(gt) == len(truth) and all(len(a) == len(b) for a, b in zip(gt, truth)):
                shape_ok += 1
            for r, row in enumerate(truth):
                for c, cell in enumerate(row):
                    cells += 1
                    g = gt[r][c] if r < len(gt) and c < len(gt[r]) else ""
                    same = norm(g) == norm(cell)
                    okc += same
                    sim_sum += 1.0 if same else difflib.SequenceMatcher(None, norm(g), norm(cell)).ratio()
                    if not same and "-v" in sys.argv:
                        print(f"      ячейка [{r},{c}]: эталон «{cell}» -> «{g}»")
        tot_cells += cells
        ok_cells += okc
        kind = "скан" if res.ocr_pages else "текст"
        cell_txt = f"{okc}/{cells}" if cells else "-"
        print(f"{filename[:58]:58} {kind:5} {len(got_tables)}/{len(truth_tables):<3} {cell_txt:>9} "
              f"{hit}/{len(truth_words):<4} {dt:5.1f}")
    print()
    print(f"Таблицы: структура (строки x столбцы) верна в {shape_ok} из {shape_n}")
    print(f"Ячейки: точное совпадение {ok_cells} из {tot_cells} ({100 * ok_cells / max(tot_cells, 1):.1f}%), "
          f"среднее сходство {100 * sim_sum / max(tot_cells, 1):.1f}%")
    print(f"Слова эталона, найденные в тексте: {rec_hit} из {rec_all} ({100 * rec_hit / max(rec_all, 1):.1f}%)")


if __name__ == "__main__":
    main()
