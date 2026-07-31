#!/usr/bin/env python3
"""Render the user-facing final report from commit ledgers only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def _load(path: str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"ledger must be a JSON object: {path}")
    return value


def _artifact_link(artifact: dict[str, Any]) -> str:
    name = str(artifact.get("name") or "archivo")
    url = str(artifact.get("url") or "")
    if not url.startswith("https://drive.google.com/"):
        raise ValueError(f"artifact {name!r} has no verified Drive URL")
    return f"[{name}]({url})"


def render_report(ledgers: Iterable[dict[str, Any]]) -> str:
    values = list(ledgers)
    if not values:
        return "[SILENT]"

    administrative = [
        ledger
        for ledger in values
        if ledger.get("status") == "success" and ledger.get("administrative_close")
    ]
    successful = [
        ledger
        for ledger in values
        if ledger.get("status") == "success" and not ledger.get("administrative_close")
    ]
    failed = [ledger for ledger in values if ledger.get("status") != "success"]
    item_count = sum(len(ledger.get("items") or []) for ledger in successful)
    lines: list[str] = []
    if failed:
        lines.append(
            f"⚠️ Procesados {len(successful)} correos; "
            f"{len(failed)} quedó sin procesar y permanece unread."
        )
    elif successful:
        lines.append(
            f"✅ Procesados {len(successful)} correos ({item_count} vencimientos) correctamente."
        )
    else:
        lines.append("ℹ️ Sin vencimientos nuevos.")

    for ledger in successful:
        subject = str(ledger.get("subject") or ledger.get("message_id") or "correo")
        items = ledger.get("items") or []
        item_summary = ", ".join(
            f"{item.get('service', 'servicio')} vence {item.get('due_date', '?')}"
            for item in items
        )
        lines.append(f"- {subject}: {item_summary or 'procesado' }.")
        for artifact in ledger.get("artifacts") or []:
            try:
                lines.append(f"  - {_artifact_link(artifact)}")
            except ValueError as exc:
                lines.append(f"  - Problema de reporte: {exc}")

    for ledger in administrative:
        subject = str(ledger.get("subject") or ledger.get("message_id") or "correo")
        lines.append(f"- Cierre administrativo: {subject}.")

    for ledger in failed:
        subject = str(ledger.get("subject") or ledger.get("message_id") or "correo")
        error = str(ledger.get("error") or "transacción incompleta")
        lines.append(f"- Sin procesar: {subject} — {error}")
        for artifact in ledger.get("artifacts") or []:
            try:
                link = _artifact_link(artifact)
            except ValueError as exc:
                lines.append(f"  - Problema de reporte: {exc}")
            else:
                lines.append(f"  - Archivo creado antes del fallo: {link}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="*")
    args = parser.parse_args()
    ledgers = [_load(path) for path in args.ledger]
    print(render_report(ledgers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
