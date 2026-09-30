import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.ledger.dao import GlCodeTotal
from app.ledger.fingerprint import sha256_hex

HEADER = ("gl_code", "account_names", "currency", "debit", "credit", "net", "posting_count")


@dataclass(frozen=True)
class RenderedExport:
    content: str
    sha256: str
    line_count: int
    total_debits_minor: int
    total_credits_minor: int


def format_minor(amount_minor: int, minor_units: int) -> str:
    quantum = Decimal(1).scaleb(-minor_units)
    return str(Decimal(amount_minor).scaleb(-minor_units).quantize(quantum))


def render(lines: Sequence[GlCodeTotal], *, currency: str, minor_units: int) -> RenderedExport:
    """CSV with one row per GL code plus a TOTAL control row; net = debit - credit."""
    total_debits = sum(line.debit_minor for line in lines)
    total_credits = sum(line.credit_minor for line in lines)
    if total_debits != total_credits:
        raise ValueError(f"GL export does not balance: debits {total_debits} != credits {total_credits}")

    def money(amount: int) -> str:
        return format_minor(amount, minor_units)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    for line in lines:
        writer.writerow([
            line.gl_code, "; ".join(line.account_names), currency,
            money(line.debit_minor), money(line.credit_minor), money(line.debit_minor - line.credit_minor),
            line.posting_count,
        ])
    writer.writerow(["TOTAL", "", currency, money(total_debits), money(total_credits), money(0), ""])
    content = buffer.getvalue()
    return RenderedExport(content, sha256_hex(content), len(lines), total_debits, total_credits)