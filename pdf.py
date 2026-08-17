"""Geração do PDF do recibo de aluguel, no formato de recibo tradicional
(texto corrido, como um recibo assinado à mão ou digitalmente)."""
import io
from datetime import date

from num2words import num2words
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from models import TIPO_RECIBO_ALUGUEL, TIPO_RECIBO_CAUCAO, TIPO_RECIBO_IPTU, TIPO_RECIBO_OUTROS

MESES_EXTENSO = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def fmt_money(value):
    if value is None:
        return "R$ 0,00"
    value = float(value)
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def money_extenso(value):
    try:
        texto = num2words(float(value), lang="pt_BR", to="currency")
        return texto
    except Exception:
        return ""


def fmt_date(d):
    if not d:
        return ""
    if isinstance(d, str):
        return d
    return d.strftime("%d/%m/%Y")


def data_extenso(d):
    if not d:
        d = date.today()
    return f"{d.day:02d} de {MESES_EXTENSO[d.month - 1]} de {d.year}"


def build_tenants_text(clients):
    """Recebe uma lista de objetos Client e monta o texto
    'NOME e NOME2' (aceita 1 ou mais). Não inclui CPF — o recibo em texto
    mostra apenas os nomes."""
    parts = []
    for c in clients:
        parts.append((c.name or "").upper())
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " e " + parts[-1]


def generate_receipt_pdf(receipt) -> bytes:
    """Recebe um objeto Receipt (com dados/snapshot já preenchidos) e retorna
    os bytes do PDF, em formato de recibo tradicional (texto corrido)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=30 * mm, bottomMargin=30 * mm,
        leftMargin=25 * mm, rightMargin=25 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TituloRecibo", parent=styles["Heading1"], fontSize=14, alignment=TA_CENTER,
        spaceAfter=14, fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "Corpo", parent=styles["Normal"], fontSize=11.5, leading=19,
        alignment=TA_JUSTIFY, fontName="Helvetica",
    )
    date_line_style = ParagraphStyle(
        "DataLocal", parent=styles["Normal"], fontSize=11.5, leading=19,
        fontName="Helvetica",
    )
    signature_name_style = ParagraphStyle(
        "AssinaturaNome", parent=styles["Normal"], fontSize=11, alignment=TA_CENTER,
        fontName="Helvetica",
    )

    elements = [Paragraph("RECIBO", title_style)]

    landlord_name = (receipt.snapshot_landlord_name or "________________________").upper()
    tenants_text = receipt.snapshot_clients_text or "________________________"
    prop_addr = receipt.snapshot_property_address or ""

    valor_fmt = fmt_money(receipt.value)
    extenso = money_extenso(receipt.value)
    valor_texto = f"{valor_fmt} ({extenso})" if extenso else valor_fmt

    if receipt.tipo == TIPO_RECIBO_ALUGUEL and receipt.period_start and receipt.period_end:
        referencia = (
            f"referente à locação do imóvel localizado à {prop_addr}, "
            f"pelo período entre <b>{fmt_date(receipt.period_start)}</b> "
            f"e <b>{fmt_date(receipt.period_end)}</b>"
        )
    elif receipt.tipo == TIPO_RECIBO_CAUCAO:
        referencia = f"referente à caução do imóvel localizado à {prop_addr}"
    elif receipt.tipo == TIPO_RECIBO_IPTU:
        referencia = f"referente ao IPTU do imóvel localizado à {prop_addr}"
    else:
        descricao = receipt.notes or "despesas diversas"
        referencia = f"referente a {descricao}, no imóvel localizado à {prop_addr}"

    corpo = (
        f"Pelo presente instrumento, eu <b>{landlord_name}</b>, "
        + f"declaro que recebi na data de hoje de {tenants_text}, "
        + f"o valor de {valor_texto}, {referencia}."
    )

    elements.append(Paragraph(corpo, body_style))

    if receipt.notes and receipt.tipo != TIPO_RECIBO_OUTROS:
        elements.append(Spacer(1, 4 * mm))
        elements.append(Paragraph(f"Observações: {receipt.notes}", body_style))

    elements.append(Spacer(1, 10 * mm))

    cidade = receipt.snapshot_landlord_city or ""
    fecho = f"{cidade}, {data_extenso(receipt.issue_date)}." if cidade else f"{data_extenso(receipt.issue_date)}."
    elements.append(Paragraph(fecho, date_line_style))

    elements.append(Spacer(1, 24 * mm))
    elements.append(Paragraph("_" * 45, signature_name_style))
    elements.append(Paragraph(landlord_name, signature_name_style))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
