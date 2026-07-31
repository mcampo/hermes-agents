#!/usr/bin/env python3
"""Process supported unread expense messages through one deterministic batch path."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen

from commit_item import commit_transaction
from download_gmail_attachments import download_attachments
from extract_items import body_from_eml
from prepare_item import prepare
from render_report import render_report
from row_builders import _open_pdf_text
from save_gmail_eml import save_eml_from_service


UNREAD_QUERY = (
    'label:eval is:unread ("resumen de cuenta" OR "resumen de tarjeta" '
    'OR resumen OR mastercard OR visa OR pago OR vencimiento OR factura OR '
    'expensas OR servicios OR servicio OR boleta OR deuda)'
)
VISA_URL = re.compile(
    r"https://www\.eresumen\.com\.ar/msc/descargar/m/[A-Za-z0-9-]+:0",
    re.IGNORECASE,
)
LEDGER_DIR_ENV = "GASTOS_VENCIMIENTOS_LEDGER_DIR"
EXPENSAS_LIQUIDACION = re.compile(r"TOTAL\s+AL\s+1(?:ER|°)\s+VTO", re.IGNORECASE)


def _decoded_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _headers(message: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for header in message.get("payload", {}).get("headers", []):
        name = str(header.get("name") or "").casefold()
        if name and name not in values:
            values[name] = _decoded_header(str(header.get("value") or ""))
    return values


def message_metadata(message: dict[str, Any]) -> dict[str, str]:
    headers = _headers(message)
    message_id = str(message.get("id") or "")
    if not message_id:
        raise ValueError("Gmail message has no id")
    return {
        "message_id": message_id,
        "subject": headers.get("subject", ""),
        "sender": email.utils.parseaddr(headers.get("from", ""))[1].casefold(),
        "date": headers.get("date", ""),
    }


def identify_type(subject: str, sender: str, body: str = "") -> str | None:
    """Classify only the supported current-message types."""
    normalized_subject = subject.casefold()
    normalized_sender = sender.casefold()
    normalized_body = body.casefold()
    if (
        "confirmación de pago automático" in normalized_subject
        or "confirmacion de pago automatico" in normalized_subject
        or "débito automático" in normalized_body
        or "debito automatico" in normalized_body
        or "se ha realizado con éxito" in normalized_body
        or "se ha realizado con exito" in normalized_body
    ):
        return "administrative_close"
    if (
        "resumen de cuenta visa" in normalized_subject
        and ("galicia" in normalized_sender or "eresumen" in normalized_sender)
    ):
        return "visa"
    if "resumen de tarjeta mastercard" in normalized_subject and "galicia" in normalized_sender:
        return "mastercard"
    if (
        "debitaremos el total de tu tarjeta" in normalized_subject
        and normalized_sender == "no-responder@mercadopago.com"
    ):
        return "mercado_pago"
    if "expensas período" in normalized_subject and normalized_sender == "no-reply@octopus.com.ar":
        return "expensas"
    if "servicios por vencer" in normalized_subject and normalized_sender == "avisos@pagomiscuentas.com":
        return "pago_mis_cuentas_digest"
    return None


def list_message_ids(gmail, query: str) -> list[str]:
    """Return every matching message ID, following Gmail pagination."""
    result: list[str] = []
    page_token: str | None = None
    while True:
        response = gmail.users().messages().list(
            userId="me",
            q=query,
            maxResults=100,
            pageToken=page_token,
        ).execute()
        result.extend(
            str(message["id"])
            for message in response.get("messages", [])
            if message.get("id")
        )
        page_token = response.get("nextPageToken")
        if not page_token:
            return result


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return safe or "message"

def default_ledger_dir() -> Path:
    return Path(os.environ.get(LEDGER_DIR_ENV) or tempfile.mkdtemp(prefix="gastos-vencimientos-ledgers-"))


def _message_year(metadata: dict[str, str], fallback_year: int | None) -> int:
    if fallback_year is not None:
        return fallback_year
    try:
        parsed = email.utils.parsedate_to_datetime(metadata["date"])
        if parsed is not None:
            return parsed.year
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    return datetime.now().year


def _pdf_attachments(attachments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        attachment
        for attachment in attachments
        if str(attachment.get("mimeType") or "").casefold() == "application/pdf"
        or Path(str(attachment.get("path") or "")).suffix.casefold() == ".pdf"
    ]


def _exactly_one_pdf(attachments: Iterable[dict[str, Any]], label: str) -> str:
    pdfs = _pdf_attachments(attachments)
    if len(pdfs) != 1:
        raise ValueError(f"{label} requires exactly one PDF attachment; found {len(pdfs)}")
    return str(pdfs[0]["path"])


def _expensas_paths(attachments: Iterable[dict[str, Any]]) -> dict[str, str]:
    pdfs = _pdf_attachments(attachments)
    if len(pdfs) != 2:
        raise ValueError(f"Expensas requires exactly two PDF attachments; found {len(pdfs)}")
    liquidaciones = [
        attachment
        for attachment in pdfs
        if EXPENSAS_LIQUIDACION.search(_open_pdf_text(str(attachment["path"])))
    ]
    if len(liquidaciones) != 1:
        raise ValueError(
            "Expensas requires exactly one liquidación PDF with TOTAL AL 1er VTO marker"
        )
    liquidacion = liquidaciones[0]
    receipt = next(attachment for attachment in pdfs if attachment is not liquidacion)
    return {"liquidacion": str(liquidacion["path"]), "recibo": str(receipt["path"])}


def _visa_url(eml_path: Path) -> str:
    match = VISA_URL.search(html.unescape(body_from_eml(eml_path)))
    if not match:
        raise ValueError("Visa EML has no current eresumen PDF URL ending in :0")
    return match.group(0)


def download_visa_pdf(url: str, destination: Path) -> None:
    """Download one Visa statement and reject token-expiry HTML responses."""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is allowlisted above.
        body = response.read()
        headers = getattr(response, "headers", None)
        content_type = (
            headers.get_content_type() if hasattr(headers, "get_content_type") else ""
        )
    if content_type.casefold() == "text/html" or not body.startswith(b"%PDF"):
        raise ValueError("Visa download did not return a PDF; link may be expired")
    destination.write_bytes(body)


def acquire_sources(
    message: dict[str, Any],
    *,
    gmail,
    source_dir: Path,
    fallback_year: int | None = None,
) -> dict[str, Any]:
    """Acquire and role-label only the current message's required sources."""
    metadata = message_metadata(message)
    source_dir.mkdir(parents=True, exist_ok=True)
    item_type = identify_type(metadata["subject"], metadata["sender"])
    eml_path = source_dir / "message.eml"

    if item_type is None:
        save_eml_from_service(gmail, metadata["message_id"], str(eml_path))
        item_type = identify_type(
            metadata["subject"], metadata["sender"], body_from_eml(eml_path)
        )
    if item_type is None:
        raise ValueError("unsupported message type for deterministic batch runner")
    if item_type == "administrative_close":
        return {
            **metadata,
            "type": item_type,
            "paths": {},
            "year": _message_year(metadata, fallback_year),
        }

    if item_type == "visa":
        save_eml_from_service(gmail, metadata["message_id"], str(eml_path))
        pdf_path = source_dir / "visa.pdf"
        download_visa_pdf(_visa_url(eml_path), pdf_path)
        paths = {"pdf": str(pdf_path)}
    elif item_type in {"mastercard", "mercado_pago"}:
        attachments = download_attachments(
            gmail,
            metadata["message_id"],
            str(source_dir),
            message=message,
        )
        paths = {"pdf": _exactly_one_pdf(attachments, item_type)}
    elif item_type == "expensas":
        attachments = download_attachments(
            gmail,
            metadata["message_id"],
            str(source_dir),
            message=message,
        )
        paths = _expensas_paths(attachments)
    elif item_type == "pago_mis_cuentas_digest":
        save_eml_from_service(gmail, metadata["message_id"], str(eml_path))
        paths = {"eml": str(eml_path)}
    else:
        raise AssertionError(f"missing source handler for {item_type}")
    return {
        **metadata,
        "type": item_type,
        "paths": paths,
        "year": _message_year(metadata, fallback_year),
    }


def _failed_ledger(metadata: dict[str, str], error: Exception | str) -> dict[str, Any]:
    detail = str(error) if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return {
        "ledger_version": 1,
        "message_id": metadata["message_id"],
        "subject": metadata["subject"],
        "status": "failed",
        "error": detail,
        "steps": [],
        "artifacts": [],
        "items": [],
    }


def _pending_ledger(metadata: dict[str, str]) -> dict[str, Any]:
    return {
        "ledger_version": 1,
        "message_id": metadata["message_id"],
        "subject": metadata["subject"],
        "status": "pending",
        "steps": [],
        "artifacts": [],
        "items": [],
    }


def persist_ledger(path: Path, ledger: dict[str, Any]) -> None:
    """Atomically replace one per-message ledger file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(ledger, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _ledger_path(ledger_dir: Path, index: int, message_id: str) -> Path:
    return ledger_dir / f"{index:03d}-{_safe_component(message_id)}.json"


def _mark_unread(gmail, message_id: str) -> None:
    gmail.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": ["UNREAD"]},
    ).execute()


def _administrative_close(gmail, metadata: dict[str, str]) -> dict[str, Any]:
    gmail.users().messages().modify(
        userId="me",
        id=metadata["message_id"],
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()
    return {
        "ledger_version": 1,
        "message_id": metadata["message_id"],
        "subject": metadata["subject"],
        "status": "success",
        "administrative_close": True,
        "steps": [{"name": "gmail_mark_read", "status": "ok"}],
        "artifacts": [],
        "items": [],
    }


def _persist_final_ledger(
    ledger_path: Path,
    ledger: dict[str, Any],
    *,
    gmail,
) -> dict[str, Any]:
    try:
        persist_ledger(ledger_path, ledger)
        return ledger
    except Exception as exc:
        failed = dict(ledger)
        failed["status"] = "failed"
        failed["error"] = f"ledger persistence failure: {type(exc).__name__}: {exc}"
        if ledger.get("status") == "success":
            try:
                _mark_unread(gmail, str(ledger["message_id"]))
                failed.setdefault("steps", []).append(
                    {"name": "gmail_restore_unread", "status": "ok"}
                )
            except Exception as unread_error:
                failed["error"] += (
                    f"; failed to restore unread: {type(unread_error).__name__}: {unread_error}"
                )
        try:
            persist_ledger(ledger_path, failed)
        except Exception:
            pass
        return failed


def process_message(
    message: dict[str, Any],
    *,
    gmail,
    drive,
    sheets,
    source_root: Path,
    ledger_dir: Path,
    index: int,
    fallback_year: int | None = None,
) -> dict[str, Any]:
    """Process exactly one message; never automatically retry its commit."""
    metadata = message_metadata(message)
    ledger_path = _ledger_path(ledger_dir, index, metadata["message_id"])
    try:
        persist_ledger(ledger_path, _pending_ledger(metadata))
    except Exception as exc:
        return _failed_ledger(metadata, f"ledger persistence failure before commit: {exc}")

    try:
        acquired = acquire_sources(
            message,
            gmail=gmail,
            source_dir=source_root / f"{index:03d}-{_safe_component(metadata['message_id'])}",
            fallback_year=fallback_year,
        )
        if acquired["type"] == "administrative_close":
            ledger = _administrative_close(gmail, acquired)
        else:
            manifest = prepare(
                acquired["type"],
                message_id=acquired["message_id"],
                subject=acquired["subject"],
                paths=acquired["paths"],
                year=acquired["year"],
            )
            ledger = commit_transaction(manifest, gmail=gmail, drive=drive, sheets=sheets)
    except Exception as exc:
        ledger = _failed_ledger(metadata, exc)
    return _persist_final_ledger(ledger_path, ledger, gmail=gmail)


def process_batch(
    *,
    gmail,
    drive,
    sheets,
    ledger_dir: Path,
    message_ids: list[str] | None = None,
    query: str = UNREAD_QUERY,
    fallback_year: int | None = None,
) -> list[dict[str, Any]]:
    """Process explicit IDs or every message returned by the fixed unread query."""
    resolved_ids = list(message_ids) if message_ids is not None else list_message_ids(gmail, query)
    if not resolved_ids:
        return []
    with tempfile.TemporaryDirectory(prefix="gastos-vencimientos-sources-") as directory:
        source_root = Path(directory)
        results: list[dict[str, Any]] = []
        for index, message_id in enumerate(resolved_ids, start=1):
            message = gmail.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
            results.append(
                process_message(
                    message,
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    source_root=source_root,
                    ledger_dir=ledger_dir,
                    index=index,
                    fallback_year=fallback_year,
                )
            )
        return results


def build_services() -> dict[str, Any]:
    google_scripts = os.path.expanduser(
        "~/.hermes/profiles/eval/skills/productivity/google-workspace/scripts"
    )
    sys.path.insert(0, google_scripts)
    from google_api import build_service  # type: ignore

    return {
        "gmail": build_service("gmail", "v1"),
        "drive": build_service("drive", "v3"),
        "sheets": build_service("sheets", "v4"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-id", action="append", dest="message_ids")
    parser.add_argument("--query", default=UNREAD_QUERY)
    parser.add_argument(
        "--ledger-dir",
        type=Path,
        help="retained per-run ledger directory (defaults to the harness destination or a new standalone path)",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="override the source message year for Mercado Pago",
    )
    args = parser.parse_args()
    if args.message_ids and args.query != UNREAD_QUERY:
        parser.error("--message-id and a custom --query are mutually exclusive")
    services = build_services()
    ledgers = process_batch(
        gmail=services["gmail"],
        drive=services["drive"],
        sheets=services["sheets"],
        ledger_dir=args.ledger_dir or default_ledger_dir(),
        message_ids=args.message_ids,
        query=args.query,
        fallback_year=args.year,
    )
    print(render_report(ledgers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
