"""Cálculo das datas de período de referência do aluguel.

O sistema seleciona o período automaticamente — o operador não escolhe
datas manualmente. As regras:

- mes_fechado: mês de calendário cheio (dia 1 ao último dia do mês).
- mes_vencido: período "vencido" (em atraso), que termina 1 dia antes do
  dia de vencimento do aluguel e começa no dia seguinte ao vencimento
  anterior. Ex.: vencimento dia 10 -> período de 10/07 a 09/08.
- mes_vincendo: período "a vencer" (adiantado), que começa no próprio dia
  de vencimento e termina 1 dia antes do vencimento seguinte. Ex.:
  vencimento dia 10 -> período de 10/08 a 09/09.

Depois do primeiro recibo de um contrato, os períodos seguintes são
sempre sequenciais: cada novo período começa no dia seguinte ao fim do
período anterior, independente da data em que o recibo é realmente
emitido.
"""
from datetime import date, timedelta
import calendar

from models import (
    PERIODICIDADE_MES_FECHADO, PERIODICIDADE_MES_VENCIDO, PERIODICIDADE_MES_VINCENDO,
)


def _clamp_day(year, month, day):
    """Garante um dia válido para o mês (ex.: dia 31 em fevereiro vira 28/29)."""
    last_day = calendar.monthrange(year, month)[1]
    return min(day, last_day)


def add_months(d, months):
    """Soma (ou subtrai) meses a uma data, preservando o dia quando possível
    (com ajuste automático para meses mais curtos)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = _clamp_day(year, month, d.day)
    return date(year, month, day)


def _due_date_in_month(ref_date, due_day):
    return date(ref_date.year, ref_date.month, _clamp_day(ref_date.year, ref_date.month, due_day))


def next_due_on_or_after(ref_date, due_day):
    """Primeira ocorrência do dia de vencimento igual ou posterior a ref_date."""
    candidate = _due_date_in_month(ref_date, due_day)
    if candidate < ref_date:
        candidate = add_months(candidate, 1)
    return candidate


def last_due_on_or_before(ref_date, due_day):
    """Última ocorrência do dia de vencimento igual ou anterior a ref_date."""
    candidate = _due_date_in_month(ref_date, due_day)
    if candidate > ref_date:
        candidate = add_months(candidate, -1)
    return candidate


def first_period(periodicity, anchor_date, due_day=None):
    """Calcula o primeiro período de referência de um contrato, a partir de
    uma data-âncora (normalmente a data de emissão do primeiro recibo)."""
    if periodicity == PERIODICIDADE_MES_FECHADO:
        start = date(anchor_date.year, anchor_date.month, 1)
        last_day = calendar.monthrange(anchor_date.year, anchor_date.month)[1]
        end = date(anchor_date.year, anchor_date.month, last_day)
        return start, end

    if not due_day:
        # sem dia de vencimento cadastrado, cai de volta para mês fechado
        return first_period(PERIODICIDADE_MES_FECHADO, anchor_date)

    if periodicity == PERIODICIDADE_MES_VENCIDO:
        due = last_due_on_or_before(anchor_date, due_day)
        end = due - timedelta(days=1)
        start = add_months(due, -1)
        return start, end

    if periodicity == PERIODICIDADE_MES_VINCENDO:
        due = next_due_on_or_after(anchor_date, due_day)
        start = due
        end = add_months(due, 1) - timedelta(days=1)
        return start, end

    return None, None


def next_period(previous_end):
    """Calcula o período seguinte de forma sequencial, a partir do fim do
    período anterior — sempre continua exatamente de onde parou."""
    start = previous_end + timedelta(days=1)
    end = add_months(start, 1) - timedelta(days=1)
    return start, end


MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
