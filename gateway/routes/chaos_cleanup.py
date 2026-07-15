"""Atomic cleanup helpers for controlled YITING chaos demonstrations."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

# Current full-pipeline triggers use INC-CHAOS-*.  The deploy-demo prefix is also
# removed by Reset Demo Environment.
_DEMO_PREFIXES: tuple[str, ...] = ("INC-CHAOS-%", "INC-SUSDEP-%")
_PROTECTED_INCIDENT_IDS: tuple[str, ...] = ("INC-JUDGE-001",)


def _demo_incident_ids(db: sqlite3.Connection) -> list[str]:
    clauses = " OR ".join("incident_id LIKE ?" for _ in _DEMO_PREFIXES)
    rows = db.execute(
        f"SELECT incident_id FROM incidents WHERE {clauses}",
        _DEMO_PREFIXES,
    ).fetchall()
    return [str(row[0]) for row in rows]


def _protected_incident_ids(db: sqlite3.Connection) -> list[str]:
    placeholders = ",".join("?" for _ in _PROTECTED_INCIDENT_IDS)
    rows = db.execute(
        f"SELECT incident_id FROM incidents WHERE incident_id IN ({placeholders})",
        _PROTECTED_INCIDENT_IDS,
    ).fetchall()
    return [str(row[0]) for row in rows]


def _delete_for_incidents(
    db: sqlite3.Connection,
    table: str,
    column: str,
    incident_ids: Sequence[str],
) -> int:
    if not incident_ids:
        return 0
    placeholders = ",".join("?" for _ in incident_ids)
    cursor = db.execute(
        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
        tuple(incident_ids),
    )
    return max(cursor.rowcount, 0)


def _room_ids_for_incidents(
    db: sqlite3.Connection,
    incident_ids: Sequence[str],
) -> list[str]:
    if not incident_ids:
        return []
    placeholders = ",".join("?" for _ in incident_ids)
    rows = db.execute(
        f"SELECT room_id FROM incident_rooms WHERE incident_id IN ({placeholders})",
        tuple(incident_ids),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _delete_for_rooms(
    db: sqlite3.Connection,
    table: str,
    column: str,
    room_ids: Sequence[str],
) -> int:
    if not room_ids:
        return 0
    placeholders = ",".join("?" for _ in room_ids)
    cursor = db.execute(
        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
        tuple(room_ids),
    )
    return max(cursor.rowcount, 0)


def remove_demo_incidents(db: sqlite3.Connection) -> dict[str, object]:
    """Delete only synthetic demo incidents and their local dependent records.

    Synthetic incident rooms are deleted with their demo incidents.  The
    operation changes no schema, does not touch real incidents, and is atomic
    under BEGIN IMMEDIATE.
    """
    protected_incidents = _protected_incident_ids(db)
    incident_ids = _demo_incident_ids(db)
    if not incident_ids:
        return {
            "cleaned_incidents": 0,
            "deleted_records": {},
            "rooms_deleted": 0,
            "protected_incidents": protected_incidents,
        }

    deleted: dict[str, int] = {}
    try:
        db.execute("BEGIN IMMEDIATE")
        room_ids = _room_ids_for_incidents(db, incident_ids)
        deleted["incident_room_messages"] = _delete_for_rooms(
            db, "incident_room_messages", "room_id", room_ids
        )
        deleted["incident_room_messages"] += _delete_for_incidents(
            db, "incident_room_messages", "incident_id", incident_ids
        )
        deleted["incident_room_participants"] = _delete_for_rooms(
            db, "incident_room_participants", "room_id", room_ids
        )
        deleted["incident_rooms"] = _delete_for_incidents(
            db, "incident_rooms", "incident_id", incident_ids
        )
        deleted["suppression_rules"] = _delete_for_incidents(
            db, "suppression_rules", "source_incident_id", incident_ids
        )
        deleted["authorizations"] = _delete_for_incidents(
            db, "authorizations", "incident_id", incident_ids
        )
        deleted["nonces"] = _delete_for_incidents(
            db, "nonces", "incident_id", incident_ids
        )
        deleted["cards"] = _delete_for_incidents(
            db, "cards", "incident_id", incident_ids
        )
        deleted["alerts"] = _delete_for_incidents(
            db, "alerts", "incident_id", incident_ids
        )
        deleted["alerts"] += _delete_for_incidents(
            db, "alerts", "alert_id", incident_ids
        )
        deleted["incidents"] = _delete_for_incidents(
            db, "incidents", "incident_id", incident_ids
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    return {
        "cleaned_incidents": len(incident_ids),
        "deleted_records": deleted,
        "rooms_deleted": deleted.get("incident_rooms", 0),
        "protected_incidents": protected_incidents,
    }
