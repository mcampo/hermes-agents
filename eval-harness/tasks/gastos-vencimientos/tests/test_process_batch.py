from __future__ import annotations

import json
import os
import sys
import tempfile
sys.dont_write_bytecode = True
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TASK_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = TASK_DIR / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(TASK_DIR))
import verify_skill

import process_batch
from render_report import render_report


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


def message(
    message_id: str,
    subject: str = "Resumen de Cuenta VISA",
    sender: str = "e-resumen@bancogalicia.com.ar",
) -> dict:
    return {
        "id": message_id,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Sat, 11 Jul 2026 18:44:22 -0300"},
            ]
        },
    }


class Response:
    def __init__(self, body: bytes, content_type: str):
        self.body = body
        self.headers = self
        self.content_type = content_type

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self):
        return self.body

    def get_content_type(self):
        return self.content_type


class ProcessBatchTests(unittest.TestCase):
    def test_supported_dispatch_and_confirmation_are_explicit(self):
        self.assertEqual(
            process_batch.identify_type(
                "Resumen de Cuenta VISA", "e-resumen@bancogalicia.com.ar"
            ),
            "visa",
        )
        self.assertEqual(
            process_batch.identify_type(
                "Resumen de Tarjeta MasterCard", "notificaciones@galicia.com.ar"
            ),
            "mastercard",
        )
        self.assertEqual(
            process_batch.identify_type(
                "Debitaremos el total de tu tarjeta el 17 de julio",
                "no-responder@mercadopago.com",
            ),
            "mercado_pago",
        )
        self.assertEqual(
            process_batch.identify_type(
                "J ALVAREZ 783 - Expensas Período JUNIO-2026 (No responder)",
                "no-reply@octopus.com.ar",
            ),
            "expensas",
        )
        self.assertEqual(
            process_batch.identify_type(
                "Servicios por Vencer", "avisos@pagomiscuentas.com"
            ),
            "pago_mis_cuentas_digest",
        )
        self.assertEqual(
            process_batch.identify_type(
                "Otro asunto",
                "avisos@pagomiscuentas.com",
                "El débito automático se ha realizado con éxito",
            ),
            "administrative_close",
        )

    def test_message_discovery_paginates(self):
        gmail = MagicMock()
        messages = gmail.users.return_value.messages.return_value
        messages.list.side_effect = [
            Request({"messages": [{"id": "one"}], "nextPageToken": "p2"}),
            Request({"messages": [{"id": "two"}]}),
        ]
        self.assertEqual(process_batch.list_message_ids(gmail, "label:eval"), ["one", "two"])
        self.assertEqual(messages.list.call_count, 2)
        self.assertEqual(messages.list.call_args_list[1].kwargs["pageToken"], "p2")

    def test_visa_download_rejects_html_and_accepts_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "visa.pdf"
            with patch.object(
                process_batch,
                "urlopen",
                return_value=Response(b"%PDF-1.7\ncurrent", "application/pdf"),
            ):
                process_batch.download_visa_pdf("https://example.test/statement:0", destination)
            self.assertEqual(destination.read_bytes(), b"%PDF-1.7\ncurrent")
            with patch.object(
                process_batch,
                "urlopen",
                return_value=Response(b"<html>expired</html>", "text/html"),
            ), self.assertRaisesRegex(ValueError, "did not return a PDF"):
                process_batch.download_visa_pdf("https://example.test/statement:0", destination)

    def test_expensas_role_selection_requires_one_current_liquidacion(self):
        attachments = [
            {"path": "/tmp/liquidacion.pdf", "mimeType": "application/pdf"},
            {"path": "/tmp/recibo.pdf", "mimeType": "application/pdf"},
        ]
        with patch.object(
            process_batch,
            "_open_pdf_text",
            side_effect=["TOTAL AL 1er VTO.: $306.017,11", "Recibo de pago"],
        ):
            self.assertEqual(
                process_batch._expensas_paths(attachments),
                {"liquidacion": "/tmp/liquidacion.pdf", "recibo": "/tmp/recibo.pdf"},
            )
        with patch.object(process_batch, "_open_pdf_text", return_value="Recibo"):
            with self.assertRaisesRegex(ValueError, "exactly one liquidación"):
                process_batch._expensas_paths(attachments)

    def test_failed_acquisition_persists_failure_and_never_commits(self):
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(
                process_batch, "acquire_sources", side_effect=ValueError("expired Visa URL")
            ), patch.object(process_batch, "commit_transaction") as commit:
                ledger = process_batch.process_message(
                    message("visa-id"),
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    source_root=root / "sources",
                    ledger_dir=root / "ledgers",
                    index=1,
                )
            self.assertEqual(ledger["status"], "failed")
            self.assertIn("expired Visa URL", ledger["error"])
            commit.assert_not_called()
            saved = json.loads((root / "ledgers" / "001-visa-id.json").read_text())
            self.assertEqual(saved["status"], "failed")

    def test_precommit_ledger_failure_stops_commit(self):
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(process_batch, "persist_ledger", side_effect=OSError("disk full")), \
                 patch.object(process_batch, "commit_transaction") as commit:
                ledger = process_batch.process_message(
                    message("visa-id"),
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    source_root=Path(directory) / "sources",
                    ledger_dir=Path(directory) / "ledgers",
                    index=1,
                )
        self.assertEqual(ledger["status"], "failed")
        self.assertIn("before commit", ledger["error"])
        commit.assert_not_called()

    def test_commit_runs_once_and_final_ledger_is_saved(self):
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        acquired = {
            "message_id": "visa-id",
            "subject": "Resumen de Cuenta VISA",
            "sender": "e-resumen@bancogalicia.com.ar",
            "date": "Sat, 11 Jul 2026 18:44:22 -0300",
            "type": "visa",
            "paths": {"pdf": "/tmp/current-visa.pdf"},
            "year": 2026,
        }
        manifest = {"message_id": "visa-id", "subject": acquired["subject"], "items": [{}]}
        committed = {
            "ledger_version": 1,
            "message_id": "visa-id",
            "subject": acquired["subject"],
            "status": "success",
            "steps": [],
            "artifacts": [],
            "items": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(process_batch, "acquire_sources", return_value=acquired), \
                 patch.object(process_batch, "prepare", return_value=manifest) as prepare, \
                 patch.object(process_batch, "commit_transaction", return_value=committed) as commit:
                ledger = process_batch.process_message(
                    message("visa-id"),
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    source_root=root / "sources",
                    ledger_dir=root / "ledgers",
                    index=1,
                )
            self.assertEqual(ledger["status"], "success")
            self.assertEqual(commit.call_count, 1)
            self.assertEqual(prepare.call_args.kwargs["year"], 2026)
            saved = json.loads((root / "ledgers" / "001-visa-id.json").read_text())
            self.assertEqual(saved["status"], "success")

    def test_administrative_close_marks_only_message_and_renders_separately(self):
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        acquired = {
            "message_id": "close-id",
            "subject": "Confirmación de Pago Automático",
            "sender": "avisos@pagomiscuentas.com",
            "date": "Sat, 11 Jul 2026 18:44:22 -0300",
            "type": "administrative_close",
            "paths": {},
            "year": 2026,
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(process_batch, "acquire_sources", return_value=acquired), \
                 patch.object(process_batch, "commit_transaction") as commit:
                ledger = process_batch.process_message(
                    message("close-id", acquired["subject"], acquired["sender"]),
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    source_root=Path(directory) / "sources",
                    ledger_dir=Path(directory) / "ledgers",
                    index=1,
                )
        self.assertEqual(ledger["status"], "success")
        self.assertTrue(ledger["administrative_close"])
        commit.assert_not_called()
        self.assertEqual(
            gmail.users.return_value.messages.return_value.modify.call_args.kwargs["body"],
            {"removeLabelIds": ["UNREAD"]},
        )
        self.assertIn("Cierre administrativo", render_report([ledger]))

    def test_batch_uses_discovered_ids_once_each(self):
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        messages = gmail.users.return_value.messages.return_value
        messages.get.side_effect = [
            Request(message("one")),
            Request(message("two", "Servicios por Vencer", "avisos@pagomiscuentas.com")),
        ]
        results = [
            {"status": "failed", "message_id": "one", "subject": "one"},
            {"status": "failed", "message_id": "two", "subject": "two"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(process_batch, "process_message", side_effect=results) as process:
                actual = process_batch.process_batch(
                    gmail=gmail,
                    drive=drive,
                    sheets=sheets,
                    ledger_dir=Path(directory) / "ledgers",
                    message_ids=["one", "two"],
                )
        self.assertEqual(actual, results)
        self.assertEqual(process.call_count, 2)
        self.assertEqual(messages.get.call_count, 2)


    def test_default_ledger_dir_uses_harness_destination_or_unique_standalone_path(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = Path(directory) / "provided-by-harness"
            with patch.dict(os.environ, {process_batch.LEDGER_DIR_ENV: str(configured)}):
                self.assertEqual(process_batch.default_ledger_dir(), configured)
            with patch.dict(os.environ, {}, clear=True), patch.object(
                process_batch.tempfile, "tempdir", directory
            ):
                first = process_batch.default_ledger_dir()
                second = process_batch.default_ledger_dir()
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory))
            self.assertTrue(first.name.startswith("gastos-vencimientos-ledgers-"))

    def test_static_skill_guard_requires_an_absolute_batch_interpreter(self):
        skill_text = (TASK_DIR / "skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(verify_skill.MANDATORY_BATCH_COMMAND, skill_text)
        self.assertNotIn(verify_skill.SHELL_DEPENDENT_BATCH_COMMAND, skill_text)


if __name__ == "__main__":
    unittest.main()
