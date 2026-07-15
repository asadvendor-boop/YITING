#!/usr/bin/env python3
"""Create and verify a local YITING SQLite backup.

Run this on the ECS VM before recording final videos. It is intentionally
database-local and does not read or print secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up and restore-test YITING SQLite state.")
    parser.add_argument("--sqlite-db", type=Path, required=True, help="Gateway SQLite database, e.g. /data/yiting.db")
    parser.add_argument("--victim-db", type=Path, help="Optional victim/idempotency SQLite database.")
    parser.add_argument("--backup-dir", type=Path, required=True, help="Backup directory, e.g. /opt/apps/backups/yiting")
    parser.add_argument("--output-json", type=Path, help="Write sanitized restore-test report.")
    parser.add_argument(
        "--live-submission-evidence",
        action="store_true",
        help="Mark the sanitized report as reviewed live submission evidence.",
    )
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def _integrity_check(path: Path) -> dict[str, Any]:
    with sqlite3.connect(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        table_count = db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    return {
        "ok": integrity == "ok",
        "integrity": integrity,
        "table_count": int(table_count),
    }


def _copy_and_verify(source: Path, backup_dir: Path, label: str) -> dict[str, Any]:
    backup_path = backup_dir / f"{label}.sqlite"
    _sqlite_backup(source, backup_path)
    restore = _integrity_check(backup_path)
    return {
        "label": label,
        "source_name": source.name,
        "backup_name": backup_path.name,
        "size_bytes": backup_path.stat().st_size,
        "sha256": _sha256(backup_path),
        "restore": restore,
        "passed": restore["ok"],
    }


def run(
    sqlite_db: Path,
    backup_dir: Path,
    *,
    victim_db: Path | None = None,
    live_submission_evidence: bool = False,
) -> dict[str, Any]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = backup_dir / timestamp
    backups = [_copy_and_verify(sqlite_db, run_dir, "gateway")]
    if victim_db is not None and victim_db.exists():
        backups.append(_copy_and_verify(victim_db, run_dir, "victim"))
    elif victim_db is not None:
        backups.append({
            "label": "victim",
            "source_name": victim_db.name,
            "passed": False,
            "error": "victim database not found",
        })
    return {
        "format": "yiting-backup-restore-v1",
        "project": "YITING",
        "artifact_class": "live_backup_restore" if live_submission_evidence else "backup_restore_report",
        "submission_evidence": live_submission_evidence,
        "verified_live": live_submission_evidence,
        "generated_at": datetime.now(UTC).isoformat(),
        "backup_dir_name": run_dir.name,
        "passed": all(item.get("passed") is True for item in backups),
        "backups": backups,
        "note": "Same-VM backups protect logical/container state, not total ECS host loss unless copied off-host.",
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run(
            args.sqlite_db,
            args.backup_dir,
            victim_db=args.victim_db,
            live_submission_evidence=args.live_submission_evidence,
        )
    except Exception as exc:
        report = {
            "format": "yiting-backup-restore-v1",
            "project": "YITING",
            "generated_at": datetime.now(UTC).isoformat(),
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "project": "YITING"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
