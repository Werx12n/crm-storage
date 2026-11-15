"""Генерація штрихкодів (FR-1.2, FR-1.4): EAN-13 (GTIN), Code128 (адреси комірок, номери завдань),
GS1-128 з AI 00 (SSCC палет/вантажних місць), QR. Бібліотеки python-barcode, segno, reportlab."""
import io
import os

import barcode
import segno
from barcode.writer import ImageWriter, SVGWriter

from app.errors import Invalid
from app.services import gs1

KINDS = ("ean13", "code128", "sscc", "gs1", "qr")
FONT_CANDIDATES = [
    os.environ.get("PDF_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def find_font() -> str | None:
    return next((f for f in FONT_CANDIDATES if f and os.path.exists(f)), None)


def validate(kind: str, value: str) -> str:
    """Перевірка значення і контрольної цифри GS1; повертає нормалізоване значення."""
    value = (value or "").strip()
    if kind not in KINDS:
        raise Invalid(f"Тип штрихкоду має бути одним з: {', '.join(KINDS)}", code="bad_kind")
    if not value:
        raise Invalid("Порожнє значення", code="empty")
    if kind == "ean13":
        if len(value) == 14 and value.startswith("0"):
            value = value[1:]
        if len(value) != 13 or not gs1.is_valid_gtin(value):
            raise Invalid(f"{value}: невірний GTIN-13 (контрольна цифра GS1)", code="bad_check_digit")
    elif kind == "sscc":
        if value.startswith("00") and len(value) == 20:
            value = value[2:]
        if not gs1.is_valid_sscc(value):
            raise Invalid(f"{value}: невірний SSCC (18 цифр з контрольною цифрою GS1)", code="bad_check_digit")
    elif kind == "gs1":
        parsed = gs1.parse(value)
        if not (parsed["gtin"] or parsed["sscc"]):
            raise Invalid("Рядок GS1 не містить дійсного GTIN (01) або SSCC (00)", code="bad_check_digit")
    elif kind == "code128":
        if not all(32 <= ord(ch) < 127 for ch in value):
            raise Invalid("Code128 підтримує лише символи ASCII", code="bad_chars")
    return value


def _gs1_digits(value: str) -> str:
    """'(01)0482…(10)L1' → '010482…10L1' для python-barcode gs1_128 (FNC1 додається бібліотекою)."""
    return value.replace("(", "").replace(")", "")


def render(kind: str, value: str, fmt: str = "svg") -> tuple[bytes, str]:
    value = validate(kind, value)
    if fmt not in ("svg", "png"):
        raise Invalid("Формат має бути svg або png", code="bad_format")
    buf = io.BytesIO()
    if kind == "qr":
        segno.make(value, error="m").save(buf, kind=fmt, scale=6, border=2)
    else:
        writer = SVGWriter() if fmt == "svg" else ImageWriter()
        opts = {"module_height": 15.0, "font_size": 10 if fmt == "svg" else 12, "text_distance": 5.0,
                "quiet_zone": 4.0}
        if kind == "ean13":
            bc = barcode.get("ean13", value[:12], writer=writer)
        elif kind == "sscc":
            bc = barcode.get("gs1_128", "00" + value, writer=writer)
        elif kind == "gs1":
            bc = barcode.get("gs1_128", _gs1_digits(value), writer=writer)
        else:
            bc = barcode.get("code128", value, writer=writer)
        bc.write(buf, options=opts)
    return buf.getvalue(), ("image/svg+xml" if fmt == "svg" else "image/png")


def labels_pdf(labels: list[dict]) -> bytes:
    """Аркуш етикеток A4 (3 × 7) через reportlab. label = {kind, value, title, subtitle}."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import code128, eanbc, qr
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = "Helvetica"
    path = find_font()
    if path:
        if "WMSFont" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("WMSFont", path))
        font = "WMSFont"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Етикетки WMS")
    cols, rows = 3, 7
    lw, lh = 70 * mm, 297 * mm / rows
    for i, lb in enumerate(labels):
        if i and i % (cols * rows) == 0:
            c.showPage()
        pos = i % (cols * rows)
        x0, y0 = (pos % cols) * lw, 297 * mm - (pos // cols + 1) * lh
        c.setFont(font, 8)
        c.drawString(x0 + 4 * mm, y0 + lh - 5 * mm, (lb.get("title") or "")[:42])
        if lb.get("subtitle"):
            c.setFont(font, 7)
            c.drawString(x0 + 4 * mm, y0 + lh - 9 * mm, lb["subtitle"][:48])
        kind, value = lb["kind"], validate(lb["kind"], lb["value"])
        if kind == "qr":
            w = qr.QrCodeWidget(value)
            b = w.getBounds()
            size = 26 * mm
            d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
            d.add(w)
            renderPDF.draw(d, c, x0 + 4 * mm, y0 + 3 * mm)
            c.setFont(font, 8)
            c.drawString(x0 + 32 * mm, y0 + 12 * mm, value[:20])
            continue
        if kind == "ean13":
            w = eanbc.Ean13BarcodeWidget(value[:12])
            w.barHeight = 14 * mm
            b = w.getBounds()
            d = Drawing(b[2] - b[0], b[3] - b[1])
            d.add(w)
            renderPDF.draw(d, c, x0 + 6 * mm, y0 + 4 * mm)
            continue
        data = ("\xf1" + "00" + value) if kind == "sscc" else (
            "\xf1" + _gs1_digits(value) if kind == "gs1" else value)
        bc = code128.Code128(data, barHeight=13 * mm, barWidth=0.27 * mm if kind in ("sscc", "gs1") else 0.33 * mm)
        bc.drawOn(c, x0 + 2 * mm, y0 + 8 * mm)
        c.setFont(font, 8)
        human = f"(00) {value}" if kind == "sscc" else value
        c.drawCentredString(x0 + lw / 2, y0 + 4 * mm, human)
    if not labels:
        c.setFont(font, 12)
        c.drawString(20 * mm, 280 * mm, "Немає етикеток для друку")
    c.showPage()
    c.save()
    return buf.getvalue()
