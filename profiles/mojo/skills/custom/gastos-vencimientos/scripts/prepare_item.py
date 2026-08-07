#!/usr/bin/env python3
"""Prepare one Gmail message as a compact, read-only transaction manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from extract_items import (
    body_from_eml,
    extract_expensas_text,
    extract_mastercard_text,
    extract_mercado_pago_text,
    extract_pago_mis_cuentas_html,
    extract_visa_text,
)
from item_planner import plan_item
from row_builders import _open_pdf_pages, _open_pdf_text


def prepare(
    item_type: str,
    *,
    message_id: str,
    subject: str,
    paths: dict[str, str],
    year: int | None = None,
) -> dict[str, Any]:
    if item_type == "visa":
        extracted = [extract_visa_text(_open_pdf_text(paths["pdf"]))]
        source_maps = [{"pdf": paths["pdf"]}]
    elif item_type == "mastercard":
        pages = _open_pdf_pages(paths["pdf"])
        extracted = [extract_mastercard_text(pages[0], "\n".join(pages))]
        source_maps = [{"pdf": paths["pdf"]}]
    elif item_type == "mercado_pago":
        if year is None:
            raise ValueError("Mercado Pago preparation requires --year")
        extracted = [extract_mercado_pago_text(_open_pdf_text(paths["pdf"], password=os.environ["MERCADO_PAGO_PDF_PASSWORD"]), year)]
        source_maps = [{"pdf": paths["pdf"]}]
    elif item_type == "expensas":
        extracted = [extract_expensas_text(_open_pdf_text(paths["liquidacion"]), subject)]
        sources: dict[str, str] = {"liquidacion": paths["liquidacion"]}
        if "recibo" in paths:
            sources["recibo"] = paths["recibo"]
        source_maps = [sources]
    elif item_type == "pago_mis_cuentas_digest":
        extracted = extract_pago_mis_cuentas_html(body_from_eml(paths["eml"]))
        source_maps = [{"eml": paths["eml"]} for _ in extracted]
    else:
        raise ValueError(f"unsupported deterministic item type: {item_type}")
    items = [
        plan_item(value, sources, message_id=message_id, subject=subject)
        for value, sources in zip(extracted, source_maps, strict=True)
    ]
    return {
        "transaction_version": 1,
        "message_id": message_id,
        "subject": subject,
        "items": items,
    }


def _paths(args: argparse.Namespace) -> dict[str, str]:
    if args.type in {"visa", "mastercard", "mercado_pago"}:
        return {"pdf": args.pdf}
    if args.type == "expensas":
        return {"liquidacion": args.liquidacion, "recibo": args.recibo}
    return {"eml": args.eml}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--type",
        required=True,
        choices=("visa", "mastercard", "mercado_pago", "expensas", "pago_mis_cuentas_digest"),
    )
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--pdf")
    parser.add_argument("--liquidacion")
    parser.add_argument("--recibo")
    parser.add_argument("--eml")
    parser.add_argument("--year", type=int)
    args = parser.parse_args()
    paths = _paths(args)
    for role, value in paths.items():
        if not value:
            parser.error(f"--{role} is required for {args.type}")
        if not Path(value).is_file():
            parser.error(f"source file does not exist: {value}")
    result = prepare(
        args.type,
        message_id=args.message_id,
        subject=args.subject,
        paths=paths,
        year=args.year,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
