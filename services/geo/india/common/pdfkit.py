"""Shared reportlab building blocks for the English India documents (NDA, pool agreement, grid application).

Only WinAnsi characters are used (standard PDF fonts), so the rupee sign is written as "INR".
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

_BASE = dict(fontName="Helvetica", fontSize=9.6, leading=13)
ST_BODY = ParagraphStyle("body", alignment=TA_JUSTIFY, spaceAfter=3.5, **_BASE)
ST_ITEM = ParagraphStyle("item", parent=ST_BODY, leftIndent=16, spaceAfter=2.5)
ST_H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=9, spaceAfter=4, keepWithNext=1)
ST_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=19, alignment=TA_CENTER, spaceAfter=4)
ST_SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, alignment=TA_CENTER,
                        textColor=colors.HexColor("#444444"), spaceAfter=10)
ST_PARTY = ParagraphStyle("party", parent=ST_BODY, alignment=0, leftIndent=14, spaceAfter=6)
ST_SMALL = ParagraphStyle("small", fontName="Helvetica", fontSize=8.4, leading=11)


class NumberedCanvas(rl_canvas.Canvas):
    """Adds 'Page x of y' and the document id to every page footer."""

    footer_text = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawString(2.2 * cm, 1.3 * cm, self.footer_text)
            self.drawRightString(A4[0] - 2.2 * cm, 1.3 * cm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def paras(items: list[tuple[str, list[str]]]) -> list:
    """(heading, paragraphs) -> flowables. A paragraph starting with two spaces is an indented sub-item."""
    out: list = []
    for heading, texts in items:
        out.append(Paragraph(escape(heading), ST_H))
        for t in texts:
            out.append(Paragraph(escape(t.strip()), ST_ITEM if t.startswith("  ") else ST_BODY))
    return out


def table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    t = Table([[Paragraph(escape(str(c)).replace("\n", "<br/>"), ST_SMALL) for c in r] for r in rows],
              colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaaaaa")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(story: list, *, title: str, author: str, subject: str, template: str, footer: str) -> bytes:
    """Render `story` as a deterministic A4 PDF (invariant=1 -> same inputs, same bytes)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.0 * cm, bottomMargin=2.2 * cm,
        title=title, author=author, subject=subject, creator=f"{author} - {template}", keywords=template,
        lang="en-IN", invariant=1,
    )

    class Canvas(NumberedCanvas):
        footer_text = footer

    doc.build(story, canvasmaker=lambda *a, **k: Canvas(*a, **k))
    return buf.getvalue()


def inr(n: float) -> str:
    """Indian digit grouping: 12,34,56,789."""
    neg = n < 0
    s = f"{abs(round(n)):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if neg else "") + f"INR {s}"


def num(n: float, nd: int = 0) -> str:
    return f"{n:,.{nd}f}"
