# распознанный текст -> word. правки из просмотрщика попадают в файл
import io
import re

BULLET = re.compile(r"^([-–—•]\s|\d{1,2}[.)]\s|[а-яa-z]\)\s|(рисунок|рис\.|таблица)\s*[А-ЯA-Z]?\.?\d)", re.I)


def paragraphs(text):
    # строки pdf рваные по ширине листа - склеиваем в абзацы (правило такое же, как в js)
    raw = [l.strip() for l in str(text or "").split("\n") if l.strip()]
    if len(raw) < 2:
        return raw
    max_len = max(len(l) for l in raw)
    out = []                       # [текст, длина последней строки]
    for line in raw:
        prev = out[-1] if out else None
        bullet = bool(BULLET.match(line))
        ends = prev and re.search(r"[.!?:;]$", prev[0])
        short_prev = prev and prev[1] < max_len * 0.72
        upper = bool(re.match(r"^[A-ZА-ЯЁ0-9]", line))
        if not prev or bullet or (short_prev and (ends or upper)):
            out.append([line, len(line)])
        elif re.search(r"[а-яё]-$", prev[0], re.I) and re.match(r"^[а-яё]", line):
            prev[0] = prev[0][:-1] + line
            prev[1] = len(line)
        else:
            prev[0] += " " + line
            prev[1] = len(line)
    return [o[0] for o in out]


def _heading_level(c):
    sec = c.get("section")
    if not sec:
        return 0
    if sec.startswith("Прил"):
        return 1
    return len(sec.split("."))


def _pt(chunk, sizes, default):
    # кегль из геометрии разбора, если нет - по умолчанию
    for g in chunk.get("geom") or []:
        fs = g.get("fs")
        page = g.get("page") or chunk.get("page") or 1
        if fs and 0 < page <= len(sizes):
            pt = fs * sizes[page - 1][0]
            if 7 <= pt <= 24:
                return round(pt * 2) / 2
    return default


def build_docx(title, chunks, sizes=None, page=(595.0, 842.0)):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    sizes = sizes or []
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Pt(page[0]), Pt(page[1])
    sec.left_margin, sec.right_margin = Cm(3), Cm(1.5)
    sec.top_margin = sec.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(14)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.15

    def set_font(run, pt, bold=False):
        run.font.name = "Times New Roman"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        run.font.size = Pt(pt)
        run.bold = bold

    def add_table(rows, pt, header=True):
        width = max(len(r) for r in rows)
        tbl = doc.add_table(rows=len(rows), cols=width)
        tbl.style = "Table Grid"
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, row in enumerate(rows):
            for j in range(width):
                cell = tbl.cell(i, j)
                cell.text = ""
                par = cell.paragraphs[0]
                par.paragraph_format.line_spacing = 1.0
                run = par.add_run(str(row[j]) if j < len(row) else "")
                set_font(run, pt, bold=(header and i == 0))
        if header:                                   # шапка таблицы повторяется на каждой странице
            trpr = tbl.rows[0]._tr.get_or_add_trPr()
            el = OxmlElement("w:tblHeader")
            el.set(qn("w:val"), "true")
            trpr.append(el)
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    for c in chunks:
        if c.get("kind") == "table" and c.get("data"):
            pt = _pt(c, sizes, 12)
            if c.get("title"):
                par = doc.add_paragraph()
                par.paragraph_format.keep_with_next = True
                set_font(par.add_run(c["title"]), pt + 1)
            add_table(c["data"], pt)
            continue
        pt = _pt(c, sizes, 14)
        lines = paragraphs(c.get("text"))
        lvl = _heading_level(c)
        for i, line in enumerate(lines):
            par = doc.add_paragraph()
            par.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            head = lvl > 0 and len(lines) >= 1 and i == 0 and len(line) <= 110 and not re.search(r"[.;,:]$", line.strip())
            text = (c["section"] + " " + line) if (i == 0 and c.get("section") and not line.startswith(c["section"])) else line
            if head:
                par.paragraph_format.keep_with_next = True
                par.paragraph_format.space_before = Pt(8)
                par.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            else:
                par.paragraph_format.first_line_indent = Cm(1.25)
            set_font(par.add_run(text), pt, bold=head)
    if not doc.paragraphs and not doc.tables:
        doc.add_paragraph("В документе не найдено распознанного текста.")
    doc.core_properties.title = title
    doc.core_properties.author = ""
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
