from __future__ import annotations

from gateway.database import init_db
from gateway.routes.chaos_cleanup import remove_demo_incidents


def _insert_incident(db, incident_id: str) -> None:
    db.execute(
        """
        INSERT INTO incidents (incident_id, state, severity, created_at, updated_at)
        VALUES (?, 'EXECUTED', 'P1', datetime('now'), datetime('now'))
        """,
        (incident_id,),
    )


def _insert_room_with_message(db, incident_id: str) -> None:
    room_id = f"room-{incident_id}"
    db.execute(
        """
        INSERT INTO incident_rooms (
            room_id, incident_id, title, created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, 'test', datetime('now'), datetime('now'))
        """,
        (room_id, incident_id, f"Room for {incident_id}"),
    )
    db.execute(
        """
        INSERT INTO incident_room_participants (
            room_id, participant_id, role, display_name, joined_at
        )
        VALUES (?, 'agent-test', 'triage', 'Test Agent', datetime('now'))
        """,
        (room_id,),
    )
    db.execute(
        """
        INSERT INTO incident_room_messages (
            message_id, room_id, incident_id, sender_id, sender_role, content,
            created_at, inserted_at
        )
        VALUES (?, ?, ?, 'agent-test', 'triage', 'Synthetic message',
            datetime('now'), datetime('now'))
        """,
        (f"msg-{incident_id}", room_id, incident_id),
    )


def test_demo_cleanup_reports_and_preserves_canonical_judge_incident() -> None:
    db = init_db(":memory:")
    _insert_incident(db, "INC-JUDGE-001")
    _insert_incident(db, "INC-CHAOS-AB12CD")

    result = remove_demo_incidents(db)

    assert result["cleaned_incidents"] == 1
    assert result["protected_incidents"] == ["INC-JUDGE-001"]
    assert result["rooms_deleted"] == 0
    remaining = [
        row["incident_id"]
        for row in db.execute("SELECT incident_id FROM incidents ORDER BY incident_id").fetchall()
    ]
    assert remaining == ["INC-JUDGE-001"]


def test_demo_cleanup_deletes_room_children_before_incident_parent() -> None:
    db = init_db(":memory:")
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    _insert_incident(db, "INC-JUDGE-001")
    _insert_incident(db, "INC-CHAOS-AB12CD")
    _insert_room_with_message(db, "INC-CHAOS-AB12CD")

    result = remove_demo_incidents(db)

    assert result["cleaned_incidents"] == 1
    assert result["rooms_deleted"] == 1
    assert result["deleted_records"]["incident_room_messages"] == 1
    assert result["deleted_records"]["incident_room_participants"] == 1
    assert result["deleted_records"]["incident_rooms"] == 1
    assert [
        row["incident_id"]
        for row in db.execute("SELECT incident_id FROM incidents ORDER BY incident_id").fetchall()
    ] == ["INC-JUDGE-001"]
    assert db.execute("SELECT COUNT(*) FROM incident_rooms").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM incident_room_participants").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM incident_room_messages").fetchone()[0] == 0
