from __future__ import annotations

import sqlite3

from scripts import backup_restore_check


def test_yiting_sqlite_backup_restore_check(tmp_path):
    db_path = tmp_path / "yiting.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table incidents(id text primary key, title text not null)")
        db.execute("insert into incidents values ('INC-1', 'restore test')")
        db.commit()

    report = backup_restore_check.run(db_path, tmp_path / "backups")

    assert report["passed"] is True
    assert report["project"] == "YITING"
    assert report["artifact_class"] == "backup_restore_report"
    assert report["submission_evidence"] is False
    assert report["verified_live"] is False
    assert report["backups"][0]["label"] == "gateway"
    assert report["backups"][0]["restore"]["ok"] is True
    assert report["backups"][0]["restore"]["table_count"] >= 1


def test_yiting_optional_missing_victim_db_fails_restore_check(tmp_path):
    db_path = tmp_path / "yiting.db"
    with sqlite3.connect(db_path) as db:
        db.execute("create table incidents(id text primary key)")
        db.commit()

    report = backup_restore_check.run(
        db_path,
        tmp_path / "backups",
        victim_db=tmp_path / "missing-victim.db",
    )

    assert report["passed"] is False
    assert report["backups"][1]["label"] == "victim"
    assert report["backups"][1]["error"] == "victim database not found"


def test_yiting_backup_restore_can_mark_reviewed_live_evidence(tmp_path):
    db_path = tmp_path / "yiting.db"
    victim_path = tmp_path / "victim.db"
    for path in (db_path, victim_path):
        with sqlite3.connect(path) as db:
            db.execute("create table incidents(id text primary key)")
            db.commit()

    report = backup_restore_check.run(
        db_path,
        tmp_path / "backups",
        victim_db=victim_path,
        live_submission_evidence=True,
    )

    assert report["passed"] is True
    assert report["artifact_class"] == "live_backup_restore"
    assert report["submission_evidence"] is True
    assert report["verified_live"] is True
    assert {item["label"] for item in report["backups"]} == {"gateway", "victim"}
