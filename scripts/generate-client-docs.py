from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(20 * mm, 12 * mm, "ThermoPower Monitor — pacote de homologação")
    canvas.drawRightString(190 * mm, 12 * mm, f"Página {document.page}")
    canvas.restoreState()


def build_document(path: Path, title: str, subtitle: str, sections: list[tuple[str, list[str]]]):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cover", parent=styles["Title"], fontSize=26, leading=31, textColor=colors.HexColor("#173B73"), alignment=TA_CENTER, spaceAfter=18))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontSize=17, leading=21, textColor=colors.HexColor("#173B73"), spaceBefore=14, spaceAfter=8))
    styles.add(ParagraphStyle(name="BodyTP", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=7))
    document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title=title)
    story = [Spacer(1, 42 * mm), Paragraph(title, styles["Cover"]), Paragraph(subtitle, styles["Heading2"]), Spacer(1, 16 * mm), Paragraph("Versão beta para validação funcional e coleta segura de diagnóstico.", styles["BodyTP"]), Paragraph("A aquisição com instrumentos físicos ainda não está homologada.", styles["BodyTP"]), PageBreak()]
    for heading, paragraphs in sections:
        story.append(Paragraph(heading, styles["Section"]))
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph, styles["BodyTP"]))
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manual_sections = [
        ("1. Objetivo", ["Este manual orienta a validação do ThermoPower Monitor no Windows com laboratório virtual e a coleta de informações técnicas dos equipamentos físicos."]),
        ("2. Requisitos", ["Use Windows 10 ou 11 x64 e uma conta comum. Python, Node.js, npm, banco de dados e ferramentas de desenvolvimento não são necessários."]),
        ("3. Instalação", ["Execute o instalador recebido. Mantenha o Laboratório Virtual selecionado para criar dois atalhos separados.", "Se o SmartScreen indicar editor desconhecido, confira o SHA-256 com o valor enviado pelo suporte e use a opção de execução autorizada pela política da empresa. Não desative antivírus."]),
        ("4. Login", ["Abra ThermoPower Monitor e use a credencial de homologação fornecida. O aplicativo funciona localmente e abre no navegador padrão."]),
        ("5. Laboratório virtual", ["Abra o atalho ThermoPower Virtual Lab. Confira a faixa roxa LABORATÓRIO VIRTUAL. Conecte AT4532 virtual em COM90 e GPM-8213 virtual em COM91, associe, conecte e execute uma sessão. Tudo nessa janela é simulado e não comprova driver, VID/PID ou protocolo físico."]),
        ("6. Diagnóstico físico", ["Feche o laboratório e abra ThermoPower Monitor. Em Equipamentos > Diagnóstico, capture: sem aparelhos; somente AT4532; somente GPM-8213; os dois; com os programas dos fabricantes abertos; e depois de trocar as portas USB.", "A captura é somente leitura: não envia comandos ao instrumento, não altera o Windows e não instala driver."]),
        ("7. Exportação", ["Selecione Visualizar dados, confira a prévia, marque o consentimento e escolha Exportar pacote para suporte. Envie somente o ZIP gerado ao contato configurado: <b>[CONTATO_DE_SUPORTE]</b>."]),
        ("8. Logs e solução de problemas", ["Logs ficam em %LOCALAPPDATA%\\ThermoPower Monitor\\logs. Se uma porta estiver ocupada, feche temporariamente o programa do fabricante e atualize. Se não aparecer, confira cabo e Gerenciador de Dispositivos. Não instale drivers sem orientação do fabricante."]),
        ("9. Limitação essencial", ["Detecção pelo Windows, porta aberta, seleção manual ou laboratório virtual não significam identidade confirmada, protocolo validado, aquisição validada ou equipamento homologado. Esses estados dependem de testes com os instrumentos físicos."]),
    ]
    build_document(output / "Manual-de-Homologacao.pdf", "Manual de Homologação", f"ThermoPower Monitor {args.version}", manual_sections)
    test_sections = [
        ("Roteiro", ["1. Registrar data, computador e responsável pelo teste.", "2. Validar login, dashboard, sessão simulada e PDF/JPEG.", "3. Executar plug/unplug dos dois dispositivos no Virtual Lab.", "4. Realizar as seis capturas físicas na ordem indicada.", "5. Revisar e exportar o ZIP de diagnóstico.", "6. Anotar resultado esperado, resultado observado e mensagem de erro para cada etapa."]),
        ("Devolução", ["Enviar o ZIP de diagnóstico, o roteiro preenchido e fotos opcionais apenas do equipamento/cabos. Não enviar senhas, banco, documentos pessoais ou medições confidenciais."]),
    ]
    build_document(output / "Roteiro-de-Testes.pdf", "Roteiro de Testes", f"ThermoPower Monitor {args.version}", test_sections)


if __name__ == "__main__":
    main()
