from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TASK_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = TASK_DIR / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import commit_item
from extract_items import (
    extract_expensas_text,
    extract_mastercard_text,
    extract_visa_text,
)
from item_planner import plan_item
from render_report import render_report


class ExtractionTests(unittest.TestCase):
    def test_visa_uses_current_db_rg_and_builds_required_formula_inputs(self):
        text = """
        CIERRE ACTUAL: 16 Jul 26
        VENCIMIENTO 24 Jul 26
        DEV.IMP. RG 5617 30% (histórico) 99.999,99
        SALDO ACTUAL $ 3.453.744,11 U$S 73,82
        DB.RG 5617 30% ( 108847,57 ) 32.654,27
        """
        item = extract_visa_text(text)
        self.assertEqual(item["due_date"], "2026-07-24")
        self.assertEqual(item["manual_auto"], "M")
        self.assertEqual(item["total_pesos"], "3453744.11")
        self.assertEqual(item["percepcion"], "32654.27")
        self.assertEqual(item["total_usd"], "73.82")

        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "visa.pdf"
            pdf.touch()
            plan = plan_item(
                item,
                {"pdf": str(pdf)},
                message_id="visa-id",
                subject="Resumen de Cuenta VISA",
            )
        self.assertEqual(plan["row"], [[24, "M", "=3453744,11-32654,27", "73,82"]])

    def test_visa_due_date_supports_real_tabular_page_one_layout(self):
        text = """
        PAGINA:
        CIERRE ACTUAL: 16 Jul 26
        VENCIMIENTO
        SALDO $
        SALDO U$S
        PAGO MIN.$ PAGO MIN.U$S
        24 Jul 26 3.453.744,11
        73,82
        SALDO ACTUAL $ 3.453.744,11 U$S 73,82
        DB.RG 5617 30% ( 108847,57 ) 32.654,27
        """
        item = extract_visa_text(text)
        self.assertEqual(item["due_date"], "2026-07-24")
        self.assertEqual(item["percepcion"], "32654.27")

    def test_visa_due_date_window_fails_on_multiple_candidates(self):
        text = """
        VENCIMIENTO
        SALDO $
        24 Jul 26 3.453.744,11
        25 Jul 26 3.453.744,11
        SALDO ACTUAL $ 3.453.744,11 U$S 73,82
        """
        with self.assertRaisesRegex(ValueError, "2 date candidates"):
            extract_visa_text(text)

    def test_visa_ambiguous_db_rg_fails_instead_of_assuming_zero(self):
        text = """
        VENCIMIENTO 24 Jul 26
        SALDO ACTUAL $ 3.453.744,11 U$S 73,82
        DB . RG 5617 importe ilegible
        """
        with self.assertRaisesRegex(ValueError, "amount is ambiguous"):
            extract_visa_text(text)

    def test_visa_multiple_current_db_rg_values_fail_as_ambiguous(self):
        text = """
        VENCIMIENTO 24 Jul 26
        SALDO ACTUAL $ 3.453.744,11 U$S 73,82
        DB.RG 5617 30% ( 108847,57 ) 32.654,27
        DB.RG 5617 30% ( 100,00 ) 30,00
        """
        with self.assertRaisesRegex(ValueError, "amount is ambiguous"):
            extract_visa_text(text)

    def test_mastercard_fourth_page_one_date_and_negative_ars(self):
        page_one = """
        01-Jun-26 02-Jun-26 03-Jul-26 17-Jul-26 18-Jul-26 19-Jul-26
        TOTAL A PAGAR -823.130,13 249,82
        """
        item = extract_mastercard_text(page_one)
        self.assertEqual(item["due_date"], "2026-07-17")
        self.assertEqual(item["manual_auto"], "M")
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "mastercard.pdf"
            pdf.touch()
            plan = plan_item(
                item,
                {"pdf": str(pdf)},
                message_id="master-id",
                subject="Resumen de Tarjeta MasterCard",
            )
        self.assertEqual(plan["row"], [[17, "M", 0, "249,82"]])

    def test_expensas_names_use_statement_period_but_folder_uses_due_month(self):
        item = extract_expensas_text(
            "1° VTO: 10/07/2026\nTOTAL AL 1er VTO.: $306.017,11",
            "Expensas Período JUNIO-2026",
        )
        with tempfile.TemporaryDirectory() as directory:
            liquidation = Path(directory) / "liquidacion.pdf"
            receipt = Path(directory) / "recibo.pdf"
            liquidation.touch()
            receipt.touch()
            plan = plan_item(
                item,
                {"liquidacion": str(liquidation), "recibo": str(receipt)},
                message_id="expensas-id",
                subject="Expensas Período JUNIO-2026",
            )
        self.assertEqual(plan["sheet_month"], "Julio")
        self.assertEqual(plan["sheet_range"], "'Aux - Previsión'!F10:I10")
        self.assertEqual(plan["row"], [[10, "", "306017,11", ""]])
        self.assertEqual(
            [(value["year"], value["month"], value["name"]) for value in plan["archives"]],
            [
                ("2026", "Julio", "Expensas - Liquidacion 2026-06 (vence 10-07-26).pdf"),
                ("2026", "Julio", "Expensas - Recibo 2026-06.pdf"),
            ],
        )


class ReportTests(unittest.TestCase):
    def test_report_is_ledger_driven_and_links_every_file(self):
        report = render_report([
            {
                "status": "success",
                "subject": "Expensas Período JUNIO-2026",
                "items": [{"service": "Expensas", "due_date": "2026-07-10"}],
                "artifacts": [
                    {
                        "name": "liquidacion.pdf",
                        "url": "https://drive.google.com/file/d/liquidation/view",
                    },
                    {
                        "name": "recibo.pdf",
                        "url": "https://drive.google.com/file/d/receipt/view",
                    },
                ],
            }
        ])
        self.assertIn("✅ Procesados 1 correos", report)
        self.assertIn("[liquidacion.pdf](https://drive.google.com/file/d/liquidation/view)", report)
        self.assertIn("[recibo.pdf](https://drive.google.com/file/d/receipt/view)", report)

    def test_failed_ledger_cannot_render_all_success(self):
        report = render_report([
            {
                "status": "failed",
                "subject": "Resumen de Cuenta VISA",
                "error": "ValueError: ambiguous DB.RG 5617",
            }
        ])
        self.assertTrue(report.startswith("⚠️"))
        self.assertIn("sin procesar", report.casefold())
        self.assertIn("unread", report)
        self.assertNotIn("✅", report)

    def test_failed_ledger_reports_any_archive_created_before_failure(self):
        report = render_report([{
            "status": "failed",
            "subject": "Expensas Período JUNIO-2026",
            "error": "Sheet readback mismatch",
            "artifacts": [{
                "name": "Expensas - Recibo 2026-06.pdf",
                "url": "https://drive.google.com/file/d/receipt/view",
            }],
        }])
        self.assertIn("Archivo creado antes del fallo", report)
        self.assertIn(
            "[Expensas - Recibo 2026-06.pdf](https://drive.google.com/file/d/receipt/view)",
            report,
        )

    def test_no_ledgers_is_silent(self):
        self.assertEqual(render_report([]), "[SILENT]")


class TransactionTests(unittest.TestCase):
    def test_target_conflict_stops_before_drive_sheet_and_gmail_mutations(self):
        manifest = {
            "message_id": "visa-id",
            "subject": "Resumen de Cuenta VISA",
            "items": [{
                "message_id": "visa-id",
                "type": "visa",
                "service": "Visa",
                "due_date": "2026-07-24",
                "sheet_range": "'Aux - Previsión'!F4:I4",
                "row": [[24, "M", "=3453744,11-32654,27", "73,82"]],
            }],
        }
        gmail, drive, sheets = MagicMock(), MagicMock(), MagicMock()
        with patch.object(commit_item, "target_state", return_value="conflict"), \
             patch.object(commit_item, "_upload_archives") as upload, \
             patch.object(commit_item, "_write_rows") as write:
            ledger = commit_item.commit_transaction(
                manifest, gmail=gmail, drive=drive, sheets=sheets
            )
        self.assertEqual(ledger["status"], "failed")
        self.assertIn("conflicting target rows", ledger["error"])
        upload.assert_not_called()
        write.assert_not_called()
        gmail.users.assert_not_called()


if __name__ == "__main__":
    unittest.main()
