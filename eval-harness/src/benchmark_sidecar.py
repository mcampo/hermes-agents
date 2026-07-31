"""Capture and atomically persist executed benchmark sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "executed-benchmark-v1"


def _json_snapshot(value: Any) -> Any:
    """Return a detached JSON-compatible value, rejecting non-finite data."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _manifest_path(task_dir: Path, configured_path: Any) -> Path:
    if not isinstance(configured_path, str) or not configured_path:
        raise ValueError("benchmark_metadata.manifest_path must be a non-empty relative path")
    candidate = Path(configured_path)
    if candidate.is_absolute():
        raise ValueError("benchmark_metadata.manifest_path must be relative to the task directory")
    task_root = task_dir.resolve()
    resolved = (task_root / candidate).resolve()
    if task_root not in resolved.parents:
        raise ValueError("benchmark_metadata.manifest_path must stay inside the task directory")
    return resolved


def capture_benchmark_metadata(task: Any) -> dict[str, Any] | None:
    """Snapshot opted-in task metadata before model execution.

    The returned structure is intentionally detached from the source manifest,
    so later task/model mutations cannot alter the data written to the sidecar.
    """
    descriptor = task.config.get("benchmark_metadata")
    if descriptor is None:
        return None
    if not isinstance(descriptor, Mapping):
        raise ValueError("benchmark_metadata must be an object")
    task_dir = getattr(task, "task_dir", None)
    if not isinstance(task_dir, Path):
        raise ValueError("task directory is required for benchmark_metadata")
    manifest_path = _manifest_path(task_dir, descriptor.get("manifest_path"))
    include = descriptor.get("include")
    if not isinstance(include, list) or not include or any(
        not isinstance(key, str) or not key for key in include
    ):
        raise ValueError("benchmark_metadata.include must be a non-empty list of field names")
    if len(set(include)) != len(include):
        raise ValueError("benchmark_metadata.include must not contain duplicate field names")

    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load benchmark manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("benchmark manifest must contain a JSON object")
    missing = [key for key in include if key not in manifest]
    if missing:
        raise ValueError(
            "benchmark manifest is missing declared fields: " + ", ".join(sorted(missing))
        )

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": manifest_path.relative_to(task_dir.resolve()).as_posix(),
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "manifest": _json_snapshot({key: manifest[key] for key in include}),
    }


def build_executed_sidecar(
    captured_metadata: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    run_id: str,
    runtime_artifacts: Mapping[str, str],
) -> dict[str, Any]:
    """Bind an immutable pre-run snapshot to the persisted result row."""
    session_id = row.get("session_id")
    if not isinstance(session_id, str) or not session_id or session_id == "N/A":
        raise ValueError("an executed benchmark sidecar requires a real session_id")
    transcript_path = row.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise ValueError("an executed benchmark sidecar requires a transcript_path")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("an executed benchmark sidecar requires a run_id")

    if "validation_score" not in row:
        raise ValueError("an executed benchmark sidecar requires completed validation")

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "executed",
        "benchmark": _json_snapshot(captured_metadata),
        "run": {
            "run_id": run_id,
            "timestamp": row.get("timestamp"),
            "datetime": row.get("datetime"),
            "task": row.get("task"),
            "run_number": row.get("run_number"),
            "session_id": session_id,
            "provider": row.get("provider"),
            "model": row.get("model"),
            "reasoning_effort": row.get("reasoning_effort"),
            "config_name": row.get("config_name"),
        },
        "recorded": {
            "validation_score": row.get("validation_score"),
            "transcript_path": transcript_path,
        },
        "runtime_artifacts": _json_snapshot(dict(runtime_artifacts)),
    }


def sidecar_path(session_dir: Path, session_id: str) -> Path:
    if not session_id or session_id in {".", ".."} or any(
        separator in session_id for separator in ("/", "\\")
    ):
        raise ValueError("session_id cannot be used as a sidecar filename")
    return session_dir / f"{session_id}.benchmark.json"


def write_sidecar(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace a sidecar, leaving no temporary partial on failure."""
    serialized = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def persist_executed_sidecar(
    session_dir: Path,
    captured_metadata: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    run_id: str,
    runtime_artifacts: Mapping[str, str],
) -> Path:
    """Create one executed sidecar next to the current session transcript."""
    path = sidecar_path(session_dir, str(row.get("session_id") or ""))
    payload = build_executed_sidecar(
        captured_metadata,
        row,
        run_id=run_id,
        runtime_artifacts=runtime_artifacts,
    )
    write_sidecar(path, payload)
    return path
