#!/usr/bin/env python3
"""
Row builders for gastos-vencimientos skill.

Exports:
    _fmt_ar(n)             — format Decimal/float as Argentine locale (1234567.89 → '1234567,89')
    build_tarjeta_row()    — build a 2D row for credit cards (with formula if AFIP tax > 0)
    build_servicio_row()   — build a 2D row for utilities (literal amount, no formula)
    _open_pdf_text()       — robust PDF text extraction (PyMuPDF 1.23–1.27+)
    _open_pdf_pages()      — robust per-page PDF text extraction

Usage:
    import sys
    sys.path.insert(0, '/home/mcampo/.hermes/profiles/eval/skills/gastos-vencimientos/scripts')
    from row_builders import build_tarjeta_row, build_servicio_row, _open_pdf_text

These were previously inline code blocks in references/pdf-regex-cookbook.md.
Having them as a single importable module avoids copy-paste errors in cron runs.
"""

import math
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

try:
    import fitz
except ModuleNotFoundError:  # Pure planning and tests do not need PDF support.
    fitz = None


# ---------------------------------------------------------------------------
# Money helpers — Decimal for exact financial arithmetic.
# ---------------------------------------------------------------------------

def _to_decimal(value) -> Decimal | None:
    """Convert a numeric input to Decimal, raising on NaN or Inf.

    Accepts float, int, str, Decimal, or None.  None stays None.
    Rounds to 2 decimal places with banker's rounding for input conversion.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, str)):
        d = Decimal(value)
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"Rejecting non-finite float: {value!r}")
        # Convert via string to avoid float binary-approximation artifacts
        # (e.g. 2.675 → Decimal('2.6749999999999998') → wrong rounding).
        d = Decimal(str(value))
    else:
        raise TypeError(f"Expected numeric type, got {type(value).__name__}: {value!r}")
    try:
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"Cannot quantize to 2 decimal places: {value!r}")


def _fmt_ar(n) -> str:
    """Format a Decimal/float/int as Argentine locale: 1234567.89 → '1234567,89'"""
    d = _to_decimal(n)
    if d is None:
        return ""
    # Decimal quantize ensures exactly 2 decimal places.
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Use string formatting and replace the dot with comma.
    s = f"{d:f}"
    # f-string for Decimal gives e.g. "1234567.89"
    return s.replace(".", ",")


def _is_negative(d: Decimal | None) -> bool:
    """True when d is not None AND strictly < 0."""
    return d is not None and d < 0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_dia(dia) -> int:
    """Return an integer 1–31, raising ValueError otherwise."""
    if not isinstance(dia, int) or dia < 1 or dia > 31:
        raise ValueError(f"Due day must be int 1–31, got {dia!r}")
    return dia


def _validate_ma(manual_auto) -> str:
    """Accept 'M', 'A', or empty string. Raise ValueError otherwise."""
    if manual_auto is None:
        manual_auto = ""
    if not isinstance(manual_auto, str) or manual_auto not in ("", "M", "A"):
        raise ValueError(f"M/A must be 'M', 'A', or '', got {manual_auto!r}")
    return manual_auto


def _validate_tax_perc(percepcion, total_pesos: Decimal):
    """Check that tax is not negative and does not exceed total (unless total ≤ 0)."""
    perc = _to_decimal(percepcion)
    if perc is None or perc == 0:
        return Decimal("0")
    if perc < 0:
        raise ValueError(f"AFIP tax cannot be negative: {perc}")
    if total_pesos > 0 and perc > total_pesos:
        raise ValueError(
            f"AFIP tax ({perc}) exceeds total pesos ({total_pesos})"
        )
    return perc


# ---------------------------------------------------------------------------
# Public row builders
# ---------------------------------------------------------------------------

def build_tarjeta_row(
    dia: int,
    manual_auto: str,
    total_pesos,       # float | int | Decimal
    percepcion,        # float | int | Decimal | None
    total_usd,         # float | int | Decimal | None
) -> list:
    """Build a 2D row for credit cards.

    - Negative total_pesos → 0 literal (credit balance).
    - AFIP tax > 0 → formula: =TOTAL,XX-TAX,XX (comma decimal for AR locale).
    - No tax (0 or None) → literal value.
    - Negative USD → 0 literal.
    """
    dia = _validate_dia(dia)
    manual_auto = _validate_ma(manual_auto)
    tp = _to_decimal(total_pesos)
    tu = _to_decimal(total_usd)  # None if missing

    if tp is None:
        raise ValueError("total_pesos is required and must be numeric")

    perc = _validate_tax_perc(percepcion, tp)

    # ── ARS amount ──
    if _is_negative(tp):
        monto = 0
    elif perc > 0:
        monto = f"={_fmt_ar(tp)}-{_fmt_ar(perc)}"
    else:
        monto = _fmt_ar(tp)

    # ── USD amount ──
    if tu is None:
        monto_usd = ""
    elif _is_negative(tu):
        monto_usd = 0
    else:
        monto_usd = _fmt_ar(tu)

    return [[dia, manual_auto, monto, monto_usd]]


def build_servicio_row(dia: int, manual_auto: str, total_pesos, total_usd=None) -> list:
    return build_tarjeta_row(dia, manual_auto, total_pesos, None, total_usd)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _open_pdf_pages(path: str, password: str = None) -> list[str]:
    """Open a PDF and return one text string per page."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is required to extract PDF text")
    doc = fitz.open(path)
    try:
        if doc.is_encrypted:
            if password is None:
                raise ValueError(f"Encrypted PDF with no password: {path}")
            rc = doc.authenticate(password)
            if not rc:
                raise ValueError(f"Invalid password for {path}")
        parts = []
        for page in doc:
            if hasattr(page, "get_textpage"):
                parts.append(page.get_textpage().extractText())
            elif hasattr(page, "get_text"):
                parts.append(page.get_text())
            else:
                raise RuntimeError("unsupported PyMuPDF page text API")
        return parts
    finally:
        doc.close()


def _open_pdf_text(path: str, password: str = None) -> str:
    return "\n".join(_open_pdf_pages(path, password))
