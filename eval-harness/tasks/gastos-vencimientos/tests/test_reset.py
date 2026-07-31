from __future__ import annotations

import copy
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

TASK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_DIR))
import google_helper as helper
import reset as reset_module


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.manifest = helper.load_benchmark_manifest()
        self.config = helper.load_task_config()
        self.expected = helper.load_expected_fixture()
        self.original = helper.load_original_sheet()
        self.resolved = [
            {
                "id": f"id-{index}",
                "subject": item["subject_contains"],
                "subject_contains": item["subject_contains"],
                "fixture_type": item["type"],
            }
            for index, item in enumerate(self.expected["expected_items"])
        ]
        self.states = {
            message["id"]: {"unread": True, "label_ids": ["eval-id", "UNREAD"]}
            for message in self.resolved
        }

    def _patch_baseline(self, stack: ExitStack):
        h = reset_module.helper
        stack.enter_context(
            patch.dict(
                os.environ,
                {"GASTOS_VENCIMIENTOS_ALLOW_PRODUCTION_OVERLAP": ""},
                clear=False,
            )
        )
        stack.enter_context(patch.object(h, "load_benchmark_manifest", return_value=self.manifest))
        stack.enter_context(patch.object(h, "benchmark_integrity_errors", return_value=[]))
        stack.enter_context(patch.object(h, "load_task_config", return_value=self.config))
        stack.enter_context(patch.object(h, "load_expected_fixture", return_value=self.expected))
        stack.enter_context(patch.object(h, "load_original_sheet", return_value=self.original))
        stack.enter_context(patch.object(h, "validate_static_data"))
        stack.enter_context(patch.object(h, "get_credentials", return_value=object()))
        stack.enter_context(patch.object(h, "get_services", return_value={"gmail": object(), "drive": object(), "sheets": object()}))
        stack.enter_context(patch.object(h, "get_gmail_profile", return_value={"emailAddress": helper.EVAL_ACCOUNT}))
        stack.enter_context(patch.object(h, "resolve_gmail_label", return_value={"id": "eval-id", "name": "eval"}))
        stack.enter_context(patch.object(h, "verify_sheet_identity", return_value={"locale": "es_AR"}))
        stack.enter_context(patch.object(h, "verify_drive_root_identity", return_value={"id": helper.EVAL_DRIVE_ROOT_ID}))
        stack.enter_context(patch.object(h, "list_eval_messages", side_effect=[self.resolved, [], [], self.resolved]))
        stack.enter_context(patch.object(h, "resolve_expected_messages", return_value=self.resolved))
        stack.enter_context(patch.object(h, "restore_sheet"))
        stack.enter_context(patch.object(h, "read_sheet_formulas", side_effect=[self.original, self.original]))
        stack.enter_context(patch.object(h, "trash_drive_descendants"))
        stack.enter_context(patch.object(h, "list_drive_tree", side_effect=[[], []]))
        stack.enter_context(patch.object(h, "mark_messages_unread"))
        stack.enter_context(patch.object(h, "get_message_label_states", return_value=self.states))
        stack.enter_context(patch.object(h, "get_gmail_profile_history_id", return_value="123"))
        stack.enter_context(patch.object(h, "validate_runtime_state"))
        written = {}
        stack.enter_context(patch.object(h, "write_runtime_state", side_effect=lambda state: written.update(state)))
        stack.enter_context(patch.object(h, "load_runtime_state", side_effect=lambda: copy.deepcopy(written)))
        return h

    def test_success(self):
        with ExitStack() as stack:
            self._patch_baseline(stack)
            reset_module.reset()

    def test_benchmark_integrity_failure_raises_before_auth_or_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.benchmark_integrity_errors.return_value = [
                "installed eval skill SHA-256 mismatch"
            ]
            with self.assertRaisesRegex(RuntimeError, "benchmark integrity failed"):
                reset_module.reset()
            h.get_credentials.assert_not_called()
            h.restore_sheet.assert_not_called()

    def test_authentication_failure_raises_before_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.get_credentials.side_effect = RuntimeError("auth")
            with self.assertRaisesRegex(RuntimeError, "auth"):
                reset_module.reset()
            h.restore_sheet.assert_not_called()

    def test_wrong_resource_identity_raises_before_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.verify_sheet_identity.side_effect = ValueError("wrong sheet")
            with self.assertRaisesRegex(ValueError, "wrong sheet"):
                reset_module.reset()
            h.restore_sheet.assert_not_called()

    def test_production_query_overlap_raises_before_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.list_eval_messages.side_effect = [self.resolved, [self.resolved[0]]]
            with self.assertRaisesRegex(RuntimeError, "overlaps"):
                reset_module.reset()
            h.restore_sheet.assert_not_called()

    def test_post_reset_production_query_overlap_raises_before_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.list_eval_messages.side_effect = [
                self.resolved,
                [],
                [self.resolved[0]],
            ]
            with self.assertRaisesRegex(RuntimeError, "after reset marks it unread"):
                reset_module.reset()
            h.restore_sheet.assert_not_called()
            h.mark_messages_unread.assert_not_called()

    def test_explicit_operator_override_allows_production_overlap(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {"GASTOS_VENCIMIENTOS_ALLOW_PRODUCTION_OVERLAP": "1"},
                    clear=False,
                )
            )
            h.list_eval_messages.side_effect = [
                self.resolved,
                [self.resolved[0]],
                [self.resolved[0]],
                self.resolved,
            ]
            reset_module.reset()
            h.restore_sheet.assert_called_once()
            h.mark_messages_unread.assert_called_once()

    def test_message_count_mismatch_raises_before_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.resolve_expected_messages.side_effect = ValueError("five expected")
            with self.assertRaisesRegex(ValueError, "five expected"):
                reset_module.reset()
            h.restore_sheet.assert_not_called()

    def test_sheet_verification_failure_raises(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.restore_sheet.side_effect = RuntimeError("sheet verify")
            with self.assertRaisesRegex(RuntimeError, "sheet verify"):
                reset_module.reset()
            h.trash_drive_descendants.assert_not_called()

    def test_drive_cleanup_failure_raises_before_gmail_mutation(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.list_drive_tree.side_effect = [[{"relative_path": "leftover"}]]
            with self.assertRaisesRegex(RuntimeError, "not empty"):
                reset_module.reset()
            h.mark_messages_unread.assert_not_called()

    def test_runtime_state_write_failure_raises(self):
        with ExitStack() as stack:
            h = self._patch_baseline(stack)
            h.write_runtime_state.side_effect = OSError("disk full")
            with self.assertRaisesRegex(OSError, "disk full"):
                reset_module.reset()


if __name__ == "__main__":
    unittest.main()
