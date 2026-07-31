from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


HARNESS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS_DIR / "src"))

import benchmark_sidecar
import harness


def result_row(**overrides):
    row = {
        "timestamp": 1785331200,
        "datetime": "2026-07-29T12:00:00",
        "task": "fixture-task",
        "run_number": 2,
        "session_id": "20260729_120000_abcdef",
        "provider": "provider-a",
        "model": "model-a",
        "reasoning_effort": "high",
        "config_name": "model-a (high)",
        "validation_score": 0.95,
        "transcript_path": "/results/sessions/20260729_120000_abcdef.json",
    }
    row.update(overrides)
    return row


class BenchmarkSidecarTests(unittest.TestCase):
    def _opted_in_task(self, directory: Path):
        manifest = {
            "fixture_revision": "fixture-v5",
            "scoring_revision": "score-v5",
            "validator_sha256": "abc123",
            "review_note": "must not be copied to executed metadata",
        }
        (directory / "benchmark-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        task = SimpleNamespace(
            task_dir=directory,
            config={
                "benchmark_metadata": {
                    "manifest_path": "benchmark-manifest.json",
                    "include": ["fixture_revision", "scoring_revision", "validator_sha256"],
                }
            },
        )
        return task, manifest

    def test_opted_in_sidecar_binds_immutable_manifest_session_score_and_artifacts(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            task, manifest = self._opted_in_task(directory)
            captured = benchmark_sidecar.capture_benchmark_metadata(task)
            self.assertEqual(captured["manifest"]["fixture_revision"], "fixture-v5")

            manifest["fixture_revision"] = "mutated-after-capture"
            (directory / "benchmark-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            sessions = directory / "sessions"
            path = benchmark_sidecar.persist_executed_sidecar(
                sessions,
                captured,
                result_row(),
                run_id="harness-run-123",
                runtime_artifacts={"TASK_LEDGER_DIR": "/results/ledgers/fixture-task/harness-run-123"},
            )

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.name, "20260729_120000_abcdef.benchmark.json")
            self.assertEqual(payload["benchmark"]["manifest"]["fixture_revision"], "fixture-v5")
            self.assertNotIn("review_note", payload["benchmark"]["manifest"])
            self.assertEqual(payload["run"]["session_id"], "20260729_120000_abcdef")
            self.assertEqual(payload["run"]["model"], "model-a")
            self.assertEqual(payload["recorded"]["validation_score"], 0.95)
            self.assertEqual(payload["recorded"]["transcript_path"], result_row()["transcript_path"])
            self.assertEqual(
                payload["runtime_artifacts"]["TASK_LEDGER_DIR"],
                "/results/ledgers/fixture-task/harness-run-123",
            )

    def test_task_without_metadata_does_not_capture_or_create_a_sidecar(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            task = SimpleNamespace(task_dir=directory, config={})
            self.assertIsNone(benchmark_sidecar.capture_benchmark_metadata(task))
            self.assertFalse((directory / "sessions").exists())

    def test_atomic_replacement_leaves_only_the_complete_new_sidecar(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            path = directory / "session.benchmark.json"
            benchmark_sidecar.write_sidecar(path, {"value": "old"})
            benchmark_sidecar.write_sidecar(path, {"value": "new"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": "new"})
            self.assertEqual(list(directory.glob(".session.benchmark.json.*.tmp")), [])

    def test_serialization_error_leaves_no_partial_sidecar(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            path = directory / "session.benchmark.json"
            with self.assertRaises(TypeError):
                benchmark_sidecar.write_sidecar(path, {"not_json": object()})
            self.assertFalse(path.exists())
            self.assertEqual(list(directory.glob(".session.benchmark.json.*.tmp")), [])

    def test_missing_validation_or_transcript_prevents_sidecar_creation(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            task, _ = self._opted_in_task(directory)
            captured = benchmark_sidecar.capture_benchmark_metadata(task)
            sessions = directory / "sessions"

            incomplete_validation = result_row()
            del incomplete_validation["validation_score"]
            with self.assertRaisesRegex(ValueError, "completed validation"):
                benchmark_sidecar.persist_executed_sidecar(
                    sessions,
                    captured,
                    incomplete_validation,
                    run_id="run",
                    runtime_artifacts={},
                )
            missing_transcript = result_row(transcript_path="")
            with self.assertRaisesRegex(ValueError, "transcript_path"):
                benchmark_sidecar.persist_executed_sidecar(
                    sessions,
                    captured,
                    missing_transcript,
                    run_id="run",
                    runtime_artifacts={},
                )
            self.assertFalse((sessions / "20260729_120000_abcdef.benchmark.json").exists())


    def test_harness_persists_no_sidecar_for_a_task_without_metadata(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            csv_path = directory / "eval_results.csv"
            sessions = directory / "sessions"
            path = harness.persist_result_and_sidecar(
                result_row(),
                csv_path,
                sessions,
                None,
                run_id="run",
                runtime_artifacts={},
            )
            self.assertIsNone(path)
            self.assertTrue(csv_path.is_file())
            self.assertFalse(sessions.exists())

    def test_harness_does_not_write_sidecar_when_transcript_persistence_failed(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            task, _ = self._opted_in_task(directory)
            captured = benchmark_sidecar.capture_benchmark_metadata(task)
            csv_path = directory / "eval_results.csv"
            sessions = directory / "sessions"
            with self.assertRaisesRegex(RuntimeError, "persisted transcript"):
                harness.persist_result_and_sidecar(
                    result_row(transcript_path=str(directory / "missing.json")),
                    csv_path,
                    sessions,
                    captured,
                    run_id="run",
                    runtime_artifacts={},
                )
            self.assertTrue(csv_path.is_file())
            self.assertFalse((sessions / "20260729_120000_abcdef.benchmark.json").exists())

    def test_harness_allocates_a_unique_retained_directory_for_declared_artifacts(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            task = SimpleNamespace(
                name="fixture-task",
                config={"runtime_artifacts": {"TASK_LEDGER_DIR": "ledgers"}},
            )
            environment = harness.allocate_runtime_artifacts(task, directory, "run-123")
            destination = Path(environment["TASK_LEDGER_DIR"])
            self.assertTrue(destination.is_dir())
            self.assertEqual(destination, directory / "ledgers" / "fixture-task" / "run-123")

if __name__ == "__main__":
    unittest.main()
