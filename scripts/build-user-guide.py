"""Build the operator PDF from the versioned Portuguese manual."""
from pathlib import Path
import re
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]


def build_guide(output: Path) -> None:
    source = (ROOT / "docs/MANUAL_USUARIO.md").read_text(encoding="utf-8")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("GuideTitle", parent=styles["Title"], textColor=colors.HexColor("#17233F"), spaceAfter=18))
    styles.add(ParagraphStyle("GuideSection", parent=styles["Heading2"], textColor=colors.HexColor("#2563EB"), spaceBefore=14, spaceAfter=7, keepWithNext=True))
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 15
    styles["BodyText"].spaceAfter = 8
    story = []
    for block in source.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        style = "GuideSection" if block.startswith("## ") else "GuideTitle" if block.startswith("# ") else "BodyText"
        text = escape(re.sub(r"^#+ ", "", block)).replace("\n", " ")
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        story.append(Paragraph(text, styles[style]))
    story.append(Spacer(1, 5 * mm))
    output.parent.mkdir(parents=True, exist_ok=True)

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(20 * mm, 13 * mm, "ThermoPower Monitor · Manual do Usuário")
        canvas.drawRightString(A4[0] - 20 * mm, 13 * mm, str(document.page))

    SimpleDocTemplate(str(output), pagesize=A4, title="Manual do Usuário - ThermoPower Monitor",
                      author="ThermoPower", leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=23 * mm).build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build_guide(ROOT / "build/user-guide.pdf")
