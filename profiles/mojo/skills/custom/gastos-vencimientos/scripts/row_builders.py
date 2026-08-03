#!/usr/bin/env python3
"""
Row builders for gastos-vencimientos skill.

Exports:
    _fmt_ar(n)             — format Decimal/float as Argentine locale (1234567.89 → '1234567,89')
    build_tarjeta_row()    — build a 2D row for credit cards (with formula if AFIP tax > 0)
    build_servicio_row()   — build a 2D row for utilities (literal amount, no formula)
    _open_pdf_text()       — robust PDF text extraction (PyMuPDF 1.23–1.27+)

Usage:
    import sys
    sys.path.insert(0, '$HOME/.hermes/profiles/mojo/skills/custom/gastos-vencimientos/scripts')
    from row_builders import build_tarjeta_row, build_servicio_row, _open_pdf_text

These were previously inline code blocks in references/pdf-regex-cookbook.md.
Having them as a single importable module avoids copy-paste errors in cron runs.
"""

import math
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import fitz


# ---------------------------------------------------------------------------
# Money helpers — Decimal for exact financial arithmetic.
# ---------------------------------------------------------------------------

def _to_decimal(value) -> Decimal | None:
    """Convert a numeric input to Decimal, raising on NaN or Inf.

    Accepts float, int, str, Decimal, or None.  None stays None.
    Rounds to 2 decimal places with half-up rounding for input conversion.
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
    return f"{d:f}".replace(".", ",")


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
    if not isinstance(dia, int) or not 1 <= dia <= 31:
        raise ValueError(f"Due day must be int 1–31, got {dia!r}")
    manual_auto = "" if manual_auto is None else manual_auto
    if not isinstance(manual_auto, str) or manual_auto not in ("", "M", "A"):
        raise ValueError(f"M/A must be 'M', 'A', or '', got {manual_auto!r}")
    tp = _to_decimal(total_pesos)
    tu = _to_decimal(total_usd)  # None if missing

    if tp is None:
        raise ValueError("total_pesos is required and must be numeric")

    perc = _to_decimal(percepcion) or Decimal("0")
    if perc < 0:
        raise ValueError(f"AFIP tax cannot be negative: {perc}")
    if tp > 0 and perc > tp:
        raise ValueError(f"AFIP tax ({perc}) exceeds total pesos ({tp})")

    # ── ARS amount ──
    if tp < 0:
        monto = 0
    elif perc > 0:
        monto = f"={_fmt_ar(tp)}-{_fmt_ar(perc)}"
    else:
        monto = _fmt_ar(tp)

    # ── USD amount ──
    if tu is None:
        monto_usd = ""
    elif tu < 0:
        monto_usd = 0
    else:
        monto_usd = _fmt_ar(tu)

    return [[dia, manual_auto, monto, monto_usd]]


def build_servicio_row(
    dia: int,
    manual_auto: str,
    total_pesos,           # float | int | Decimal
    total_usd=None,        # float | int | Decimal | None
) -> list:
    """Build a 2D row for utilities: literal amount, no formula.

    - Negative total_pesos → 0 literal.
    - Missing USD → blank (empty string).
    - Negative USD → 0 literal.
    """
    return build_tarjeta_row(dia, manual_auto, total_pesos, None, total_usd)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _open_pdf_text(path: str, password: str = None) -> str:
    """Open a PDF (encrypted or not) and return its full text.

    Compatible with PyMuPDF 1.23–1.27+.
    """
    doc = fitz.open(path)
    try:
        if doc.is_encrypted:
            if password is None:
                raise ValueError(f"Encrypted PDF with no password: {path}")
            rc = doc.authenticate(password)
            if not rc:
                raise ValueError(f"Invalid password for {path}")
        # PyMuPDF ≤1.23: Document.get_text() exists
        if doc.page_count > 0 and not hasattr(doc[0], "get_textpage"):
            # PyMuPDF ≤1.23: Document.get_text() exists
            return doc.get_text()
        # PyMuPDF ≥1.27: iterate pages, extract TextPage
        parts = []
        for page in doc:
            parts.append(page.get_textpage().extractText())
        return "\n".join(parts)
    finally:
        doc.close()
