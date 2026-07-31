from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TASK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_DIR))
import google_helper as helper


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return copy.deepcopy(self.value)


class GmailMessages:
    def __init__(self):
        self.pages = {
            None: {"messages": [{"id": "b"}], "nextPageToken": "p2"},
            "p2": {"messages": [{"id": "a"}]},
        }

    def list(self, **kwargs):
        return Request(self.pages[kwargs.get("pageToken")])

    def get(self, **kwargs):
        message_id = kwargs["id"]
        return Request({
            "id": message_id,
            "threadId": "t" + message_id,
            "labelIds": ["UNREAD", "eval-id"],
            "payload": {"headers": [
                {"name": "Subject", "value": f"=?utf-8?q?Fixture_{message_id}?="},
                {"name": "From", "value": "sender@example.com"},
            ]},
        })


class GmailUsers:
    def __init__(self):
        self._messages = GmailMessages()

    def messages(self):
        return self._messages


class Gmail:
    def __init__(self):
        self._users = GmailUsers()

    def users(self):
        return self._users


class DriveFiles:
    def __init__(self):
        self.updated = []
        self.pages = {
            (helper.EVAL_DRIVE_ROOT_ID, None): {
                "files": [{"id": "folder", "name": "2026", "mimeType": helper.FOLDER_MIME}],
                "nextPageToken": "more",
            },
            (helper.EVAL_DRIVE_ROOT_ID, "more"): {
                "files": [{"id": "loose", "name": "z.txt", "mimeType": "text/plain"}],
            },
            ("folder", None): {
                "files": [{"id": "file", "name": "a.pdf", "mimeType": "application/pdf"}],
            },
        }

    def list(self, **kwargs):
        parent = kwargs["q"].split("'")[1]
        return Request(self.pages.get((parent, kwargs.get("pageToken")), {"files": []}))

    def update(self, **kwargs):
        self.updated.append(kwargs["fileId"])
        return Request({"id": kwargs["fileId"], "trashed": True})


class Drive:
    def __init__(self):
        self._files = DriveFiles()

    def files(self):
        return self._files


class FakeValues:
    def __init__(self, values):
        self.values = copy.deepcopy(values)
        self.cleared = False

    def batchClear(self, **kwargs):
        self.cleared = True
        self.values = []
        return Request({})

    def update(self, **kwargs):
        self.values = copy.deepcopy(kwargs["body"]["values"])
        return Request({"updatedRows": len(self.values)})

    def get(self, **kwargs):
        return Request({"values": self.values})


class FakeSpreadsheets:
    def __init__(self, values):
        self._values = FakeValues(values)

    def values(self):
        return self._values


class FakeSheets:
    def __init__(self, values):
        self._spreadsheets = FakeSpreadsheets(values)

    def spreadsheets(self):
        return self._spreadsheets


class GoogleHelperTests(unittest.TestCase):
    def test_benchmark_manifest_matches_task_and_skill_tree(self):
        manifest = helper.load_benchmark_manifest()
        self.assertEqual(
            helper.benchmark_integrity_errors(
                manifest,
                installed_skill_dir=TASK_DIR / "skill",
            ),
            [],
        )

    def test_benchmark_integrity_detects_installed_skill_drift(self):
        import tempfile

        manifest = helper.load_benchmark_manifest()
        with tempfile.TemporaryDirectory() as directory:
            drifted_skill = Path(directory)
            (drifted_skill / "SKILL.md").write_text(
                "drifted during model run\n",
                encoding="utf-8",
            )
            errors = helper.benchmark_integrity_errors(
                manifest,
                installed_skill_dir=drifted_skill,
            )
        self.assertTrue(any(
            "installed eval skill SHA-256 mismatch" in error for error in errors
        ))

    def test_benchmark_integrity_detects_missing_installed_skill(self):
        import tempfile

        manifest = helper.load_benchmark_manifest()
        with tempfile.TemporaryDirectory() as directory:
            errors = helper.benchmark_integrity_errors(
                manifest,
                installed_skill_dir=Path(directory) / "missing",
            )
        self.assertTrue(any(
            "installed eval skill unavailable" in error for error in errors
        ))

    def test_benchmark_integrity_detects_task_local_skill_drift(self):
        manifest = helper.load_benchmark_manifest()
        expected_hash = manifest["evaluation_skill_tree_sha256"]
        with patch.object(
            helper,
            "skill_tree_sha256",
            side_effect=["0" * 64, expected_hash],
        ):
            errors = helper.benchmark_integrity_errors(
                manifest,
                installed_skill_dir=TASK_DIR / "skill",
            )
        self.assertTrue(any(
            "task-local skill SHA-256 mismatch" in error for error in errors
        ))
        self.assertFalse(any(
            "installed eval skill SHA-256 mismatch" in error for error in errors
        ))

    def test_benchmark_integrity_detects_pinned_revision_drift(self):
        pinned = helper.load_benchmark_manifest()
        pinned = copy.deepcopy(pinned)
        pinned["scoring_revision"] = "stale-revision"
        errors = helper.benchmark_integrity_errors(
            pinned,
            installed_skill_dir=TASK_DIR / "skill",
        )
        self.assertIn(
            "benchmark-manifest.json changed after task discovery",
            errors,
        )

    def test_gmail_pagination_and_subject_decoding_are_deterministic(self):
        messages = helper.list_eval_messages(Gmail(), "label:eval")
        self.assertEqual([message["id"] for message in messages], ["a", "b"])
        self.assertEqual([message["subject"] for message in messages], ["Fixture a", "Fixture b"])

    def test_drive_tree_paginates_and_cleanup_preserves_root(self):
        drive = Drive()
        tree = helper.list_drive_tree(drive, helper.EVAL_DRIVE_ROOT_ID)
        self.assertEqual(
            [entry["relative_path"] for entry in tree],
            ["2026", "2026/a.pdf", "z.txt"],
        )
        helper.trash_drive_descendants(drive, helper.EVAL_DRIVE_ROOT_ID)
        self.assertEqual(set(drive._files.updated), {"folder", "file", "loose"})
        self.assertNotIn(helper.EVAL_DRIVE_ROOT_ID, drive._files.updated)
        with self.assertRaises(ValueError):
            helper.trash_drive_descendants(drive, "production-root")

    def test_range_parsing_and_canonical_lookup(self):
        self.assertEqual(
            helper.parse_a1_range("'Aux - Previsión'!Z12:AC12"),
            ("Aux - Previsión", 12, 26, 12, 29),
        )
        self.assertEqual(helper.canonical_range("Visa", "Junio"), "'Aux - Previsión'!B4:E4")
        with self.assertRaises(ValueError):
            helper.parse_a1_range("B4")

    def test_formula_and_argentine_numeric_normalization(self):
        self.assertEqual(helper.normalize_number("$2.360.015,28"), "2360015.28")
        self.assertEqual(helper.normalize_number("1.731,24"), "1731.24")
        self.assertEqual(helper.normalize_number("$0"), "0")
        self.assertTrue(helper.raw_amount_matches(" =5306400,91 - 2946385,63 ", "=5306400,91-2946385,63"))
        self.assertFalse(helper.raw_amount_matches("=1,00-0,50", "=1,00-0,40"))

    def test_allowlist_diff_detects_cells_beyond_snapshot_dimensions(self):
        original = [["a", "b"]]
        current = [["a", "changed", "extra"], ["new"]]
        diffs = helper.compare_sheet_with_allowlist(original, current, ["B1:B1"])
        self.assertEqual(diffs, ["C1: expected '', actual 'extra'", "A2: expected '', actual 'new'"])

    def test_score_apportionment_and_validation_failures(self):
        self.assertAlmostEqual(helper.score_fraction(0.15, 2, 3), 0.10)
        self.assertEqual(helper.score_fraction(0.05, 0, 0), 0.05)
        expected = helper.load_expected_fixture()
        helper.validate_expected_fixture(expected)
        duplicate = copy.deepcopy(expected)
        duplicate["expected_items"][1]["subject_contains"] = duplicate["expected_items"][0]["subject_contains"]
        with self.assertRaisesRegex(ValueError, "duplicate subject"):
            helper.validate_expected_fixture(duplicate)
        bad_range = copy.deepcopy(expected)
        bad_range["expected_items"][0]["expected_sheet_rows"][0]["range"] = "'Aux - Previsión'!B9:E9"
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            helper.validate_expected_fixture(bad_range)

    def test_mock_sheet_restore_round_trip_preserves_values(self):
        original = [["Name", "Amount", "Blank"], ["Visa", "=10,50-1,25", ""], ["Agua", 33136.68]]
        sheets = FakeSheets([["dirty"]])
        helper.restore_sheet(sheets, "eval-sheet", "Aux - Previsión", original)
        self.assertTrue(sheets.spreadsheets().values().cleared)
        self.assertEqual(sheets.spreadsheets().values().values, original)


if __name__ == "__main__":
    unittest.main()
