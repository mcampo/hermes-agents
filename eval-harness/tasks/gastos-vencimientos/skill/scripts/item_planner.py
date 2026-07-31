#!/usr/bin/env python3
"""Build canonical Sheet/Drive plans from deterministic extracted items."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from cell_range import MONTH_BLOCKS, cell_range
from row_builders import build_servicio_row, build_tarjeta_row


MONTH_NAMES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

CARD_TYPES = {"visa", "mastercard", "mercado_pago"}


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISO due_date: {value!r}") from exc


def _period(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
        if year < 2000 or month < 1 or month > 12:
            raise ValueError
        return year, month
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid statement_period: {value!r}") from exc


def canonical_manual_auto(item: dict[str, Any]) -> str:
    item_type = item["type"]
    if item_type in {"visa", "mastercard"}:
        return "M"
    if item_type == "expensas":
        return ""
    value = item.get("manual_auto") or ""
    if value not in ("", "M", "A"):
        raise ValueError(f"invalid extracted M/A value: {value!r}")
    return value


def build_row(item: dict[str, Any]) -> list:
    due = _date(item["due_date"])
    manual_auto = canonical_manual_auto(item)
    total_pesos = item.get("total_pesos")
    if item["type"] in CARD_TYPES:
        row = build_tarjeta_row(
            due.day,
            manual_auto,
            total_pesos,
            item.get("percepcion"),
            item.get("total_usd"),
        )
    else:
        row = build_servicio_row(
            due.day,
            manual_auto,
            total_pesos,
            item.get("total_usd"),
        )
    return row


def _source(sources: dict[str, str], role: str) -> str:
    value = sources.get(role)
    if not value:
        raise ValueError(f"missing source path for role {role!r}")
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"source path does not exist: {path}")
    return str(path)


def canonical_archives(item: dict[str, Any], sources: dict[str, str]) -> list[dict[str, str]]:
    due = _date(item["due_date"])
    period_year, period_month = _period(item["statement_period"])
    due_suffix = due.strftime("%d-%m-%y")
    period = f"{period_year:04d}-{period_month:02d}"
    folder_month = MONTH_NAMES[due.month]
    common = {"year": f"{due.year:04d}", "month": folder_month}
    item_type = item["type"]
    if item_type == "visa":
        values = [("pdf", f"Visa - Resumen {period} (vence {due_suffix}).pdf")]
    elif item_type == "mastercard":
        values = [("pdf", f"Mastercard - Resumen {period} (vence {due_suffix}).pdf")]
    elif item_type == "mercado_pago":
        values = [("pdf", f"Mercado Pago - Resumen {period} (vence {due_suffix}).pdf")]
    elif item_type == "expensas":
        # Both names use the enclosing email's statement period. The receipt
        # PDF may describe the prior paid period and is not authoritative here.
        values = [
            ("liquidacion", f"Expensas - Liquidacion {period} (vence {due_suffix}).pdf"),
            ("recibo", f"Expensas - Recibo {period}.pdf"),
        ]
    elif item_type == "pago_mis_cuentas_digest":
        values = [("eml", f"PagoMisCuentas - {item['service']} {period}.eml")]
    else:
        extension = Path(_source(sources, "source")).suffix or ".eml"
        values = [("source", f"{item['service']} - {period}{extension}")]
    return [
        {**common, "role": role, "local_path": _source(sources, role), "name": name}
        for role, name in values
    ]


def expected_numeric_row(item: dict[str, Any]) -> list[Any]:
    row = build_row(item)[0]
    total = Decimal(str(item["total_pesos"]))
    tax = Decimal(str(item.get("percepcion") or 0))
    ars = Decimal("0") if total < 0 else total - tax if item["type"] in CARD_TYPES and tax > 0 else total
    usd_value = item.get("total_usd")
    if usd_value is None:
        usd: str | Decimal = ""
    else:
        usd_decimal = Decimal(str(usd_value))
        usd = Decimal("0") if usd_decimal < 0 else usd_decimal
    return [row[0], row[1], format(ars, "f"), "" if usd == "" else format(usd, "f")]


def plan_item(
    extracted: dict[str, Any],
    sources: dict[str, str],
    *,
    message_id: str,
    subject: str,
) -> dict[str, Any]:
    if not message_id:
        raise ValueError("message_id is required")
    due = _date(extracted["due_date"])
    month_name = MONTH_NAMES[due.month]
    if month_name not in MONTH_BLOCKS:
        raise ValueError(f"due month {month_name} is outside Sheet coverage")
    service = str(extracted["service"])
    row = build_row(extracted)
    return {
        "manifest_version": 1,
        "message_id": message_id,
        "subject": subject,
        "type": extracted["type"],
        "service": service,
        "due_date": extracted["due_date"],
        "statement_period": extracted["statement_period"],
        "sheet_month": month_name,
        "sheet_range": cell_range(service, month_name),
        "row": row,
        "expected_numeric_row": expected_numeric_row(extracted),
        "archives": canonical_archives(extracted, sources),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted", required=True, help="Extracted item JSON path")
    parser.add_argument("--sources", required=True, help="JSON object mapping source roles to local paths")
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()
    with Path(args.extracted).open(encoding="utf-8") as handle:
        extracted = json.load(handle)
    sources = json.loads(args.sources)
    result = plan_item(extracted, sources, message_id=args.message_id, subject=args.subject)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
