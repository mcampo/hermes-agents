from __future__ import annotations

import copy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

TASK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_DIR))
import google_helper as helper
import validator as validator_module


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.config = helper.load_task_config()
        self.expected = helper.load_expected_fixture()
        self.original = helper.load_original_sheet()
        self.runtime = {
            "fixture_revision": self.expected["fixture_revision"],
            "started_at": "2026-07-25T12:00:00+00:00",
            "gmail_history_id": "123",
            "messages": [
                {
                    "id": f"id-{index}",
                    "subject": item["subject_contains"],
                    "subject_contains": item["subject_contains"],
                    "fixture_type": item["type"],
                    "baseline_label_ids": ["eval-id", "INBOX", "UNREAD"],
                }
                for index, item in enumerate(self.expected["expected_items"])
            ],
            "sheet_baseline": copy.deepcopy(self.original),
            "resource_ids": {
                "spreadsheet_id": helper.EVAL_SPREADSHEET_ID,
                "sheet_id": helper.EVAL_SHEET_ID,
                "drive_root_id": helper.EVAL_DRIVE_ROOT_ID,
            },
        }
        self.formulas = copy.deepcopy(self.original)
        self.formatted = copy.deepcopy(self.original)
        for item in self.expected["expected_items"]:
            for row in item["expected_sheet_rows"]:
                _, sr, sc, _, _ = helper.parse_a1_range(row["range"])
                while len(self.formulas[sr - 1]) < sc + 3:
                    self.formulas[sr - 1].append("")
                self.formulas[sr - 1][sc - 1:sc + 3] = [
                    row["due_day"], row["manual_auto"], row["ars_raw"], row["usd_raw"]
                ]
                while len(self.formatted[sr - 1]) < sc + 3:
                    self.formatted[sr - 1].append("")
                self.formatted[sr - 1][sc - 1:sc + 3] = [
                    str(row["due_day"]), row["manual_auto"], row["ars_formatted"], row["usd_formatted"]
                ]
        self.tree = self._perfect_tree()
        self.label_states = {
            message["id"]: {"unread": False, "label_ids": ["eval-id", "INBOX"]}
            for message in self.runtime["messages"]
        }

    def _perfect_tree(self):
        entries = []
        for index, path in enumerate(helper.expected_drive_tree_paths(self.expected)):
            is_file = path in helper.expected_drive_paths(self.expected)
            entries.append({
                "id": f"drive-{index}",
                "name": path.rsplit("/", 1)[-1],
                "mime_type": "application/pdf" if is_file else helper.FOLDER_MIME,
                "relative_path": path,
                "web_view_link": f"https://drive.google.com/file/d/drive-{index}/view",
                "created_time": "2026-07-25T12:01:00Z",
            })
        return entries

    def _perfect_output(self):
        file_ids = [
            entry["id"] for entry in self.tree
            if entry["relative_path"] in helper.expected_drive_paths(self.expected)
        ]
        links = " ".join(f"https://drive.google.com/file/d/{file_id}/view" for file_id in file_ids)
        return f"✅ Procesados y archivados correctamente. {links}"

    def _patch_state(self, stack: ExitStack):
        h = validator_module.helper
        stack.enter_context(patch.object(h, "benchmark_integrity_errors", return_value=[]))
        stack.enter_context(patch.object(h, "load_task_config", return_value=self.config))
        stack.enter_context(patch.object(h, "load_expected_fixture", return_value=self.expected))
        stack.enter_context(patch.object(h, "load_original_sheet", return_value=self.original))
        stack.enter_context(patch.object(h, "load_runtime_state", return_value=self.runtime))
        stack.enter_context(patch.object(h, "get_credentials", return_value=object()))
        stack.enter_context(patch.object(h, "get_services", return_value={"gmail": object(), "drive": object(), "sheets": object()}))
        stack.enter_context(patch.object(h, "get_gmail_profile", return_value={"emailAddress": helper.EVAL_ACCOUNT}))
        stack.enter_context(patch.object(h, "verify_sheet_identity", return_value={"sheetId": helper.EVAL_SHEET_ID}))
        stack.enter_context(patch.object(h, "verify_drive_root_identity", return_value={"id": helper.EVAL_DRIVE_ROOT_ID}))
        stack.enter_context(patch.object(h, "read_sheet_formulas", return_value=self.formulas))
        stack.enter_context(patch.object(h, "read_sheet_formatted", return_value=self.formatted))
        stack.enter_context(patch.object(h, "list_drive_tree", return_value=self.tree))
        stack.enter_context(patch.object(h, "get_message_label_states", return_value=self.label_states))
        stack.enter_context(patch.object(h, "get_gmail_label_change_details", return_value={}))
        return h

    def test_perfect_state_scores_one(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(self._perfect_output())
        self.assertEqual(result["score"], 1.0, "\n".join(result["details"]))

    def test_benchmark_integrity_failure_is_hard_zero_before_observation(self):
        with ExitStack() as stack:
            h = self._patch_state(stack)
            h.benchmark_integrity_errors.return_value = [
                "installed eval skill SHA-256 mismatch"
            ]
            result = validator_module.validate(self._perfect_output())
            h.get_services.assert_not_called()
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [benchmark_integrity]", result["details"][0])

    def test_partial_state_scores_proportionally(self):
        self.tree = []
        self.label_states = {
            message["id"]: {"unread": True, "label_ids": ["eval-id", "INBOX", "UNREAD"]}
            for message in self.runtime["messages"]
        }
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate("Issues: no se pudo archivar; mensajes unread.")
        self.assertEqual(result["score"], 0.57, "\n".join(result["details"]))

    def test_non_allowlisted_sheet_change_is_hard_zero(self):
        self.formulas = copy.deepcopy(self.formulas)
        self.formulas[2][0] = "Gas changed"
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(self._perfect_output())
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [sheet_safety]", result["details"][0])

    def test_outside_gmail_change_is_hard_zero(self):
        with ExitStack() as stack:
            h = self._patch_state(stack)
            h.get_gmail_label_change_details.return_value = {"outside-id": {"-UNREAD"}}
            result = validator_module.validate(self._perfect_output())
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [gmail_safety]", result["details"][0])

    def test_observation_failure_is_hard_zero(self):
        with ExitStack() as stack:
            h = self._patch_state(stack)
            h.read_sheet_formulas.side_effect = RuntimeError("API unavailable")
            result = validator_module.validate(self._perfect_output())
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [observation]", result["details"][0])

    def test_missing_runtime_state_is_hard_zero(self):
        with patch.object(validator_module.helper, "benchmark_integrity_errors", return_value=[]), \
             patch.object(validator_module.helper, "load_task_config", return_value=self.config), \
             patch.object(validator_module.helper, "load_expected_fixture", return_value=self.expected), \
             patch.object(validator_module.helper, "load_original_sheet", return_value=self.original), \
             patch.object(validator_module.helper, "load_runtime_state", side_effect=FileNotFoundError("missing")):
            result = validator_module.validate("")
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [state]", result["details"][0])

    def test_final_report_weight_is_exactly_point_zero_five(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            passed = validator_module.validate(self._perfect_output())
        with ExitStack() as stack:
            self._patch_state(stack)
            failed = validator_module.validate("Processed successfully, but no links.")
        self.assertAlmostEqual(passed["score"] - failed["score"], 0.05)
        self.assertTrue(any("FAIL [final_report]" in detail for detail in failed["details"]))

    def test_reported_early_failure_with_later_mutation_is_hard_zero(self):
        self.runtime["sheet_baseline"] = copy.deepcopy(self.original)
        visa_row = self.expected["expected_items"][2]["expected_sheet_rows"][0]
        _, sr, sc, _, _ = helper.parse_a1_range(visa_row["range"])
        while len(self.runtime["sheet_baseline"][sr - 1]) < sc:
            self.runtime["sheet_baseline"][sr - 1].append("")
        self.runtime["sheet_baseline"][sr - 1][sc - 1] = 1
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate("Visa PDF download failed, error vencido.")
        self.assertEqual(result["score"], 0.0)
        self.assertIn("HARD FAIL [transaction_order]", result["details"][0])

    def test_review_diff_is_not_classified_as_final_report_or_failure_claim(self):
        output = (
            "  ┊ review diff\n"
            "+ Visa PDF download failed with error before upload\n"
            "+ no se pudo procesar Expensas\n\n"
            + self._perfect_output()
        )
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(output)
        self.assertEqual(result["score"], 1.0, "\n".join(result["details"]))

    def test_blank_baseline_gets_no_field_correctness_credit(self):
        self.formulas = copy.deepcopy(self.original)
        self.formatted = copy.deepcopy(self.original)
        self.tree = []
        self.label_states = {
            message["id"]: {"unread": True, "label_ids": ["eval-id", "INBOX", "UNREAD"]}
            for message in self.runtime["messages"]
        }
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate("⚠️ Issues: todos sin procesar y unread.")
        self.assertEqual(result["score"], 0.12, "\n".join(result["details"]))
        for category in (
            "sheet_target_dispatch",
            "due_day_manual_auto",
            "ars_semantics",
            "usd_semantics",
        ):
            self.assertFalse(
                any(f"PASS [{category}]" in detail for detail in result["details"]),
                category,
            )

    def test_success_claim_on_observable_mismatches_fails_report_credit(self):
        self.tree = []
        self.label_states = {
            message["id"]: {"unread": True, "label_ids": ["eval-id", "INBOX", "UNREAD"]}
            for message in self.runtime["messages"]
        }
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate("✅ Procesados todos correctamente.")
        self.assertTrue(any(
            "FAIL [final_report] summary does not match" in detail
            and "observed absent or non-unique expected artifacts" in detail
            for detail in result["details"]
        ))

    def test_report_failures_accumulate_summary_and_link_errors(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate("⚠️ Issues: processing failed.")
        final_detail = next(
            detail for detail in result["details"] if "FAIL [final_report]" in detail
        )
        self.assertIn("summary does not match", final_detail)
        self.assertIn("missing links for present Drive artifacts", final_detail)


    def test_all_success_report_allows_truthful_english_negated_issue_phrases(self):
        for phrase in ("No issues.", "No problems."):
            with self.subTest(phrase=phrase), ExitStack() as stack:
                self._patch_state(stack)
                result = validator_module.validate(f"{self._perfect_output()} {phrase}")
            self.assertEqual(result["score"], 1.0, "\n".join(result["details"]))

    def test_all_success_report_allows_truthful_spanish_negated_issue_phrase(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(f"{self._perfect_output()} Sin problemas.")
        self.assertEqual(result["score"], 1.0, "\n".join(result["details"]))

    def test_positive_issue_claim_still_loses_all_success_report_credit(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(
                f"{self._perfect_output()} Issues detected after processing."
            )
        self.assertEqual(result["score"], 0.95, "\n".join(result["details"]))
        self.assertTrue(any("FAIL [final_report]" in detail for detail in result["details"]))

    def test_mixed_success_and_issue_report_still_loses_all_success_report_credit(self):
        with ExitStack() as stack:
            self._patch_state(stack)
            result = validator_module.validate(
                f"{self._perfect_output()} ⚠️ Problemas: requiere revisión."
            )
        self.assertEqual(result["score"], 0.95, "\n".join(result["details"]))

if __name__ == "__main__":
    unittest.main()
