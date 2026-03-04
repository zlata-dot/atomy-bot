from io import BytesIO
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def _pick_cyrillic_font_path() -> str | None:
    """
    Пытаемся найти кириллический TTF на macOS.
    Чаще всего работает Arial.ttf из Supplemental.
    """
    candidates = [
        # macOS system fonts (обычно есть)
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",

        # если ты положишь шрифт в проект:
        str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf"),
        str(Path(__file__).parent / "fonts" / "Arial.ttf"),
    ]
    for p in candidates:
        if p and Path(p).exists():
            return p
    return None


def generate_offer_pdf(terms_text: str, title: str = "Условия Premium (оферта)") -> bytes:
    """
    Делает PDF из текста с поддержкой кириллицы.
    """
    buf = BytesIO()

    font_path = _pick_cyrillic_font_path()
    font_name = "Helvetica"

    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("CyrFont", font_path))
            font_name = "CyrFont"
        except Exception as e:
            print("Не удалось зарегистрировать кириллический шрифт:", e)
            font_name = "Helvetica"
    else:
        print("⚠️ Кириллический шрифт не найден. PDF может быть квадратами.")

    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    c.setFont(font_name, 14)
    c.drawString(40, height - 50, title)

    c.setFont(font_name, 10)
    y = height - 80

    for raw_line in terms_text.strip().splitlines():
        line = raw_line.rstrip()
        if not line:
            y -= 12
            continue

        # простой перенос строк (по длине)
        max_chars = 95
        while len(line) > max_chars:
            c.drawString(40, y, line[:max_chars])
            line = line[max_chars:]
            y -= 12
            if y < 60:
                c.showPage()
                c.setFont(font_name, 10)
                y = height - 60

        c.drawString(40, y, line)
        y -= 12
        if y < 60:
            c.showPage()
            c.setFont(font_name, 10)
            y = height - 60

    c.showPage()
    c.save()
    return buf.getvalue()