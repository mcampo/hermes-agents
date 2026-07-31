#!/usr/bin/env python3
"""Deterministically extract supported gastos-vencimientos source data.

The normal agent path calls this module or its CLI and consumes compact JSON.
It must not copy the regexes into ad-hoc shell snippets or print full PDFs.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from row_builders import _open_pdf_pages, _open_pdf_text


MONTH_NUMBERS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "setiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}

COMPANY_SERVICES = {
    "aysa": "Agua",
    "aguas bonaerenses": "Agua",
    "metrogas": "Gas",
    "gas natural fenosa": "Gas",
    "m.blum": "Expensas",
    "administracion m.blum": "Expensas",
    "octopus": "Expensas",
}


def _strip_accents(value: str) -> str:
    return value.casefold().translate(str.maketrans("áéíóúüñ", "aeiouun"))


def month_number(value: str) -> int:
    key = _strip_accents(value.strip().rstrip("."))
    if key not in MONTH_NUMBERS:
        raise ValueError(f"unsupported Spanish month: {value!r}")
    return MONTH_NUMBERS[key]


def full_year(value: str | int) -> int:
    year = int(value)
    return 2000 + year if 0 <= year < 100 else year


def ar_decimal(value: str) -> Decimal:
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    negative_suffix = text.endswith("-")
    if negative_suffix:
        text = text[:-1]
    text = text.replace("$", "").replace("US$", "").replace("U$S", "")
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text:
        raise ValueError(f"empty Argentine decimal: {value!r}")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid Argentine decimal: {value!r}") from exc
    if negative_suffix:
        result = -result
    return result.quantize(Decimal("0.01"))


def decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _iso_date(day: str | int, month: str | int, year: str | int) -> str:
    month_value = month_number(month) if isinstance(month, str) and not month.isdigit() else int(month)
    return date(full_year(year), month_value, int(day)).isoformat()


def _period(year: str | int, month: str | int) -> str:
    month_value = month_number(month) if isinstance(month, str) and not month.isdigit() else int(month)
    return f"{full_year(year):04d}-{month_value:02d}"


def _require_match(pattern: str, text: str, label: str, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if not match:
        raise ValueError(f"could not extract {label}")
    return match


def _date_after_label(
    text: str,
    label: str,
    *,
    max_lines: int = 8,
) -> tuple[str, str, str]:
    """Return one Spanish date from a bounded line window after a label."""
    label_match = re.search(rf"(?im)^\s*{re.escape(label)}\b", text)
    if not label_match:
        raise ValueError(f"could not find {label} label")
    lines = text[label_match.end():].splitlines()[:max_lines]
    window = "\n".join(lines)
    candidates = re.findall(
        r"\b(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{2,4})\b",
        window,
        re.IGNORECASE,
    )
    if len(candidates) != 1:
        raise ValueError(
            f"{label} window contains {len(candidates)} date candidates; expected exactly one"
        )
    return candidates[0]


def extract_visa_text(text: str) -> dict[str, Any]:
    due_day, due_month, due_year = _date_after_label(text, "VENCIMIENTO")
    totals = _require_match(
        r"SALDO\s+ACTUAL\s+\$\s+(-?[\d.,]+)\s+U\$S\s+(-?[\d.,]+)",
        text,
        "Visa SALDO ACTUAL",
        re.IGNORECASE,
    )
    tax_pattern = r"DB\.RG\s+5617\s+30%\s*\([^)]*\)\s+([\d.,]+)"
    tax_values = re.findall(tax_pattern, text, re.IGNORECASE)
    has_tax_marker = bool(re.search(r"DB\s*\.\s*RG\s+5617", text, re.IGNORECASE))
    if has_tax_marker and len(tax_values) != 1:
        raise ValueError("Visa DB.RG 5617 is present but its amount is ambiguous")
    tax = ar_decimal(tax_values[0]) if tax_values else Decimal("0.00")
    close = re.search(
        r"CIERRE\s+ACTUAL\s*:\s*\d{1,2}\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{2,4})",
        text,
        re.IGNORECASE,
    )
    statement_period = (
        _period(close.group(2), close.group(1))
        if close
        else _period(due_year, due_month)
    )
    return {
        "type": "visa",
        "service": "Visa",
        "due_date": _iso_date(due_day, due_month, due_year),
        "statement_period": statement_period,
        "manual_auto": "M",
        "total_pesos": decimal_text(ar_decimal(totals.group(1))),
        "percepcion": decimal_text(tax),
        "total_usd": decimal_text(ar_decimal(totals.group(2))),
    }


def extract_mastercard_text(page_one: str, full_text: str | None = None) -> dict[str, Any]:
    all_text = full_text if full_text is not None else page_one
    dates = re.findall(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{2})\b", page_one)
    if len(dates) < 4:
        raise ValueError(f"Mastercard page 1 has {len(dates)} dates; expected at least 4")
    day, month, year = dates[3]
    totals = _require_match(
        r"TOTAL\s+A\s+PAGAR\s+(-?[\d.,]+)\s+(-?[\d.,]+)",
        all_text,
        "Mastercard TOTAL A PAGAR",
        re.IGNORECASE,
    )
    tax = re.search(
        r"PERCEP(?:\.AFIP)?\s+RG\s+(?:4815|5617)\s+30%\s+([\d.,]+)",
        all_text,
        re.IGNORECASE,
    )
    return {
        "type": "mastercard",
        "service": "Mastercard",
        "due_date": _iso_date(day, month, year),
        "statement_period": _period(year, month),
        "manual_auto": "M",
        "total_pesos": decimal_text(ar_decimal(totals.group(1))),
        "percepcion": decimal_text(ar_decimal(tax.group(1))) if tax else "0.00",
        "total_usd": decimal_text(ar_decimal(totals.group(2))),
    }


def extract_mercado_pago_text(text: str, year: int) -> dict[str, Any]:
    due = _require_match(
        r"Fecha\s+de\s+vencimiento\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)",
        text,
        "Mercado Pago due date",
        re.IGNORECASE,
    )
    total = _require_match(
        r"Total\s+a\s+pagar\s+\$\s+(-?[\d.]+)\s+(\d{2})",
        text,
        "Mercado Pago ARS total",
        re.IGNORECASE,
    )
    usd = _require_match(
        r"Total\s+a\s+pagar[\s\S]*?US\$\s+(-?[\d.]+)\s+(\d{2})",
        text,
        "Mercado Pago USD total",
        re.IGNORECASE,
    )
    total_ars = ar_decimal(f"{total.group(1)},{total.group(2)}")
    total_usd = ar_decimal(f"{usd.group(1)},{usd.group(2)}")
    automatic = bool(
        re.search(r"ten[eé]s\s+activo\s+el\s+d[eé]bito\s+autom[aá]tico", text, re.IGNORECASE)
    )
    return {
        "type": "mercado_pago",
        "service": "Tarjeta MP",
        "due_date": _iso_date(due.group(1), due.group(2), year),
        "statement_period": _period(year, due.group(2)),
        "manual_auto": "A" if automatic else "",
        "total_pesos": decimal_text(total_ars),
        "percepcion": "0.00",
        "total_usd": decimal_text(total_usd),
    }


def _subject_period(subject: str) -> str:
    match = _require_match(
        r"Expensas\s+Per[ií]odo\s+([A-Za-zÁÉÍÓÚáéíóú]+)-(20\d{2})",
        subject,
        "Expensas statement period from subject",
        re.IGNORECASE,
    )
    return _period(match.group(2), match.group(1))


def extract_expensas_text(text: str, subject: str) -> dict[str, Any]:
    try:
        statement_period = _subject_period(subject)
    except ValueError:
        fallback = _require_match(
            r"(?:LIQUIDACI[ÓO]N\s+DE\s+MES|Expensas)\s+([A-Za-zÁÉÍÓÚáéíóú]+)[ -](20\d{2})",
            text,
            "Expensas statement period",
            re.IGNORECASE,
        )
        statement_period = _period(fallback.group(2), fallback.group(1))
    due = _require_match(
        r"1[°º]?\s*VTO\s*:\s*(\d{1,2})/(\d{1,2})/(20\d{2})",
        text,
        "Expensas first due date",
        re.IGNORECASE,
    )
    amount = _require_match(
        r"TOTAL\s+AL\s+1er\s+VTO\.?\s*:\s*(?:\d{1,2}/\d{1,2}/20\d{2}\s*)?\$\s*([\d.,]+)",
        text,
        "Expensas first-due amount",
        re.IGNORECASE,
    )
    return {
        "type": "expensas",
        "service": "Expensas",
        "due_date": _iso_date(due.group(1), due.group(2), due.group(3)),
        "statement_period": statement_period,
        "manual_auto": "",
        "total_pesos": decimal_text(ar_decimal(amount.group(1))),
        "total_usd": None,
    }


def clean_html(value: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", value, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _map_company(company: str) -> str:
    normalized = _strip_accents(company).strip()
    normalized = re.sub(r"\s*\(pa\)\s*$", "", normalized).strip()
    exact = COMPANY_SERVICES.get(normalized)
    if exact:
        return exact
    matches = {service for name, service in COMPANY_SERVICES.items() if name in normalized}
    if len(matches) == 1:
        return matches.pop()
    raise ValueError(f"unmapped or ambiguous PagoMisCuentas company: {company!r}")


def extract_pago_mis_cuentas_html(body: str) -> list[dict[str, Any]]:
    text = clean_html(body)
    blocks = ["Empresa:" + block for block in text.split("Empresa:")[1:]]
    if not blocks:
        raise ValueError("PagoMisCuentas email contains no Empresa blocks")
    items: list[dict[str, Any]] = []
    for block in blocks:
        company = _require_match(r"Empresa:\s*(.+?)\s*$", block, "company", re.MULTILINE).group(1).strip()
        due = _require_match(
            r"Vencimiento:\s*(\d{1,2})/(\d{1,2})/(20\d{2})",
            block,
            f"due date for {company}",
            re.IGNORECASE,
        )
        amount = _require_match(
            r"Importe:\s*\$\s*([\d.,]+)", block, f"amount for {company}", re.IGNORECASE
        )
        automatic = "(pa)" in company.casefold() or bool(
            re.search(r"pago\s+autom[aá]tico", block, re.IGNORECASE)
        )
        due_date = _iso_date(due.group(1), due.group(2), due.group(3))
        items.append({
            "type": "pago_mis_cuentas_digest",
            "service": _map_company(company),
            "company": company,
            "due_date": due_date,
            "statement_period": due_date[:7],
            "manual_auto": "A" if automatic else "",
            "total_pesos": decimal_text(ar_decimal(amount.group(1))),
            "total_usd": None,
        })
    return items


def body_from_eml(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    body = message.get_body(preferencelist=("html", "plain"))
    if body is None:
        raise ValueError(f"no text body found in EML: {path}")
    return body.get_content()


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="type", required=True)
    for name in ("visa", "mastercard"):
        command = sub.add_parser(name)
        command.add_argument("--pdf", required=True)
    mercado = sub.add_parser("mercado-pago")
    mercado.add_argument("--pdf", required=True)
    mercado.add_argument("--year", required=True, type=int)
    expensas = sub.add_parser("expensas")
    expensas.add_argument("--pdf", required=True)
    expensas.add_argument("--subject", required=True)
    pmc = sub.add_parser("pago-mis-cuentas")
    pmc.add_argument("--eml", required=True)
    args = parser.parse_args()

    if args.type == "visa":
        result = extract_visa_text(_open_pdf_text(args.pdf))
    elif args.type == "mastercard":
        pages = _open_pdf_pages(args.pdf)
        result = extract_mastercard_text(pages[0], "\n".join(pages))
    elif args.type == "mercado-pago":
        result = extract_mercado_pago_text(_open_pdf_text(args.pdf, password="31507"), args.year)
    elif args.type == "expensas":
        result = extract_expensas_text(_open_pdf_text(args.pdf), args.subject)
    else:
        result = extract_pago_mis_cuentas_html(body_from_eml(args.eml))
    print(_json(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(_json({"status": "error", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(1)
