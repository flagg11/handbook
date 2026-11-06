# word -> pdf, чтобы дальше всё работало как с обычным pdf. word и libreoffice не нужны:
# python-docx -> простой html -> страницы через pymupdf (Story). картинки из word не переносятся
import gc
import html
import os
import re
import shutil
import time
import uuid

import pymupdf

PT = 12700  # emu в пункте

FONT_FILES = {  # шрифты windows, если есть - страницы выглядят как в word
    "regular": ("times.ttf", "Times New Roman"),
    "bold": ("timesbd.ttf", "Times New Roman"),
    "italic": ("timesi.ttf", "Times New Roman"),
    "bolditalic": ("timesbi.ttf", "Times New Roman"),
}


def _font_archive():
    dirs = [os.path.expandvars(r"%WINDIR%\Fonts"), "/usr/share/fonts/truetype/msttcorefonts", "/Library/Fonts",
            "/System/Library/Fonts/Supplemental"]
    found = {}
    for kind, (fname, _fam) in FONT_FILES.items():
        for d in dirs:
            path = os.path.join(d, fname)
            if os.path.exists(path):
                found[kind] = path
                break
            alt = os.path.join(d, fname.capitalize())
            if os.path.exists(alt):
                found[kind] = alt
                break
    if "regular" not in found:
        return "body, td, th, p, h1, h2, h3, h4 { font-family: serif; }", None
    arch = pymupdf.Archive()
    css = []
    for kind, path in found.items():
        with open(path, "rb") as fh:
            arch.add(fh.read(), f"tnr_{kind}.ttf")
        weight = "bold" if "bold" in kind else "normal"
        style = "italic" if "italic" in kind else "normal"
        css.append(f'@font-face {{ font-family: "TNR"; src: url(tnr_{kind}.ttf); font-weight: {weight}; font-style: {style}; }}')
    css.append("body, td, th, p, h1, h2, h3, h4 { font-family: TNR, serif; }")
    return "\n".join(css), arch


def _qn(tag):
    from docx.oxml.ns import qn
    return qn(tag)


def _run_html(run, base_pt):
    text = html.escape(run.text or "")
    if not text:
        return ""
    text = text.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    if run.font.size and run.font.size.pt and abs(run.font.size.pt - base_pt) > 0.4:
        text = f'<span style="font-size:{run.font.size.pt:.1f}pt">{text}</span>'
    if run.bold:
        text = f"<b>{text}</b>"
    if run.italic:
        text = f"<i>{text}</i>"
    if run.underline:
        text = f"<u>{text}</u>"
    return text


def _style_pt(par, default):
    st = par.style
    while st is not None:
        if st.font is not None and st.font.size:
            return st.font.size.pt
        st = st.base_style
    return default


def _para_html(par, default_pt, in_table=False):
    from docx.enum.text import WD_ALIGN_PARAGRAPH as A
    base = _style_pt(par, default_pt)
    inner = "".join(_run_html(r, base) for r in par.runs)
    if not inner.strip():
        return "" if in_table else "<p>&nbsp;</p>"
    pf = par.paragraph_format
    css = []
    align = par.alignment if par.alignment is not None else (par.style.paragraph_format.alignment if par.style is not None else None)
    css.append({A.CENTER: "text-align:center", A.RIGHT: "text-align:right", A.JUSTIFY: "text-align:justify"}.get(align, "text-align:left"))
    if pf.first_line_indent and pf.first_line_indent > 0:
        css.append(f"text-indent:{pf.first_line_indent / PT:.0f}pt")
    if pf.left_indent and pf.left_indent > 0:
        css.append(f"margin-left:{pf.left_indent / PT:.0f}pt")
    # между абзацами минимум 6 пт: у блоков слева свои отступы, иначе плотный текст не влезет по высоте и шрифт придётся сжимать
    after = (pf.space_after / PT) if pf.space_after is not None else 4
    css.append(f"margin-top:{(pf.space_before or 0) / PT:.0f}pt;margin-bottom:{0 if in_table else max(after, 6):.0f}pt")
    name = (par.style.name if par.style is not None else "") or ""
    if par._p.pPr is not None and par._p.pPr.numPr is not None:
        inner = ("&bull;&nbsp;" if "Number" not in name else "") + inner
    mh = re.match(r"(?:Heading|Заголовок)\s*(\d)", name)
    if mh:
        lvl = min(int(mh.group(1)), 4)
        return f'<h{lvl} style="{";".join(css)};font-size:{max(base, 14) + (4 - lvl) * 1.5:.1f}pt">{inner}</h{lvl}>'
    if name.lower() == "title":
        return f'<h1 style="{";".join(css)};text-align:center">{inner}</h1>'
    return f'<p style="{";".join(css)}">{inner}</p>'


def _table_html(tbl, default_pt):
    from docx.table import _Cell
    grid = []
    if tbl._tbl.tblGrid is not None:
        grid = [int(g.get(_qn("w:w")) or 0) for g in tbl._tbl.tblGrid.findall(_qn("w:gridCol"))]
    total = sum(grid) or 1
    rows = []                                   # строка -> [(колонка, span, kind, ширина %, html)]
    for tr in tbl._tbl.tr_lst:
        row, col = [], 0
        for tc in tr.tc_lst:
            gs = tc.tcPr.find(_qn("w:gridSpan")) if tc.tcPr is not None else None
            span = int(gs.get(_qn("w:val"))) if gs is not None else 1
            vm = tc.tcPr.find(_qn("w:vMerge")) if tc.tcPr is not None else None
            kind = ""
            if vm is not None:
                kind = "cont" if vm.get(_qn("w:val")) in (None, "continue") else "start"
            width = sum(grid[col:col + span]) / total * 100 if grid else 0
            txt = ""
            if kind != "cont":
                txt = "".join(_para_html(p, default_pt - 2, in_table=True) for p in _Cell(tc, tbl).paragraphs) or "&nbsp;"
            row.append((col, span, kind, width, txt))
            col += span
        rows.append(row)
    out = []
    for r_i, row in enumerate(rows):
        tds = []
        for col, span, kind, width, txt in row:
            if kind == "cont":
                continue  # закрыта rowspan сверху
            rowspan = 1
            if kind == "start":
                j = r_i + 1
                while j < len(rows) and any(c == col and k == "cont" for c, _s, k, _w, _t in rows[j]):
                    rowspan += 1
                    j += 1
            attrs = (f' colspan="{span}"' if span > 1 else "") + (f' rowspan="{rowspan}"' if rowspan > 1 else "")
            style = "border:0.75pt solid #000;padding:2pt 3pt;vertical-align:top;" + (f"width:{width:.1f}%;" if width else "")
            tds.append(f'<td{attrs} style="{style}">{txt}</td>')
        out.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table style="width:100%;border-collapse:collapse;margin-top:4pt;margin-bottom:6pt;'
            f'font-size:{default_pt - 2:.1f}pt">{"".join(out)}</table>')


MAX_UNPACKED = 300 * 1024 * 1024  # размер после распаковки
MAX_ENTRIES = 5000


def _check_zip(path):
    # docx это zip - проверяем до открытия, вдруг бомба
    import zipfile
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise ValueError("Документ Word слишком велик после распаковки")
        if "word/document.xml" not in z.namelist():
            raise ValueError("Это не документ Word")


def docx_to_html(path):
    import docx
    _check_zip(path)
    document = docx.Document(path)
    sec = document.sections[0]
    default_pt = 14.0
    nst = document.styles["Normal"]
    if nst.font is not None and nst.font.size:
        default_pt = nst.font.size.pt
    page_w = sec.page_width.pt if sec.page_width else 595.0
    page_h = sec.page_height.pt if sec.page_height else 842.0
    margins = [(m.pt if m is not None else 56.7) for m in (sec.left_margin, sec.top_margin, sec.right_margin, sec.bottom_margin)]
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    parts = []
    for el in document.element.body.iterchildren():
        if el.tag == _qn("w:p"):
            parts.append(_para_html(Paragraph(el, document), default_pt))
        elif el.tag == _qn("w:tbl"):
            parts.append(_table_html(Table(el, document), default_pt))
    return "".join(parts), default_pt, (page_w, page_h), margins


def docx_to_pdf(src, dst):
    body, base_pt, (pw, ph), (ml, mt, mr, mb) = docx_to_html(src)
    css, archive = _font_archive()
    css += f"\nbody {{ font-size: {base_pt:.1f}pt; line-height: 1.15; }} p, h1, h2, h3, h4 {{ margin-top:0; }}"
    story = pymupdf.Story(html=f"<body>{body or '<p>&nbsp;</p>'}</body>", user_css=css, archive=archive)
    tmp = f"{dst}.{uuid.uuid4().hex[:8]}.tmp"
    writer = pymupdf.DocumentWriter(tmp)
    mediabox = pymupdf.Rect(0, 0, pw, ph)
    where = pymupdf.Rect(ml, mt, pw - mr, ph - mb)
    more, pages = 1, 0
    while more and pages < 1000:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
    writer.close()
    del dev, writer, story  # на windows файл занят, пока жив объект писателя
    gc.collect()
    _move_into_place(tmp, dst)
    return dst


def _move_into_place(tmp, dst):
    # windows держит файл, пока его читает кто-то ещё (антивирус, индексатор) - пробуем несколько секунд
    last = None
    for attempt in range(25):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError as exc:        # WinError 32/5
            last = exc
            time.sleep(0.3)
    try:
        shutil.copyfile(tmp, dst)  # крайний случай - перезаписать содержимое
        os.remove(tmp)
        return
    except OSError:
        pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last
