import sqlite3
from gateway.database import _migrate

def test_migration_idempotent_and_backfill():
    # 1. Setup old schema
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'DETECTED'
        );
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id TEXT NOT NULL,
            sequence_number INTEGER NOT NULL,
            card_type TEXT NOT NULL,
            card_hash TEXT NOT NULL,
            card_json TEXT NOT NULL,
            idempotency_key TEXT,
            published_at TEXT
        );
        CREATE TABLE authorizations (
            authorization_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            authorization_type TEXT NOT NULL DEFAULT 'policy',
            plan_hash TEXT NOT NULL,
            action_hash TEXT NOT NULL,
            policy_rule TEXT,
            envelopes_json TEXT,
            expiry TEXT NOT NULL,
            consumed INTEGER DEFAULT 0,
            consumed_at TEXT,
            consumed_by TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE nonces (
            incident_id TEXT NOT NULL
        );
    """)

    # Insert old-schema data
    # PolicyAuthorization without card_hash
    db.execute(
        "INSERT INTO cards (incident_id, sequence_number, card_type, card_hash, card_json, published_at) "
        "VALUES ('inc-1', 1, 'PolicyAuthorization', 'hash-1', '{\"authorization_id\": \"auth-1\"}', '2023-01-01')"
    )
    db.execute(
        "INSERT INTO authorizations (authorization_id, incident_id, authorization_type, plan_hash, action_hash, expiry) "
        "VALUES ('auth-1', 'inc-1', 'policy', 'ph', 'ah', '2030-01-01')"
    )

    # StructuredApproval without card_hash/nonce
    db.execute(
        "INSERT INTO cards (incident_id, sequence_number, card_type, card_hash, card_json, published_at) "
        "VALUES ('inc-2', 1, 'StructuredApproval', 'hash-2', '{\"plan_hash\": \"ph2\", \"action_hash\": \"ah2\", \"nonce\": \"N123\"}', '2023-01-01')"
    )
    db.execute(
        "INSERT INTO authorizations (authorization_id, incident_id, authorization_type, plan_hash, action_hash, expiry) "
        "VALUES ('auth-2', 'inc-2', 'human_approval', 'ph2', 'ah2', '2030-01-01')"
    )

    # Ambiguous historical row
    db.execute(
        "INSERT INTO authorizations (authorization_id, incident_id, authorization_type, plan_hash, action_hash, expiry) "
        "VALUES ('auth-3', 'inc-3', 'human_approval', 'ph3', 'ah3', '2030-01-01')"
    )

    # 2. Run migration twice (idempotency)
    _migrate(db)
    _migrate(db)

    # 3. Assert columns exist
    cols = {row[1] for row in db.execute("PRAGMA table_info(authorizations)").fetchall()}
    assert "status" in cols
    assert "room_message_id" in cols
    assert "nonce" in cols
    assert "card_hash" in cols
    heartbeat_cols = {row[1] for row in db.execute("PRAGMA table_info(heartbeats)").fetchall()}
    assert "display_name" in heartbeat_cols
    assert "persona_title" in heartbeat_cols
    assert "persona_temperament" in heartbeat_cols

    # 4. Assert backfill worked for PolicyAuthorization
    auth1 = db.execute("SELECT card_hash, status FROM authorizations WHERE authorization_id='auth-1'").fetchone()
    assert auth1["card_hash"] == "hash-1"
    assert auth1["status"] == "PUBLISHED"

    # 5. Assert backfill worked for StructuredApproval
    auth2 = db.execute("SELECT card_hash, nonce, status FROM authorizations WHERE authorization_id='auth-2'").fetchone()
    assert auth2["card_hash"] == "hash-2"
    assert auth2["nonce"] == "N123"
    assert auth2["status"] == "PENDING"

    # 6. Assert ambiguous row left NULL
    auth3 = db.execute("SELECT card_hash, nonce FROM authorizations WHERE authorization_id='auth-3'").fetchone()
    assert auth3["card_hash"] is None
    assert auth3["nonce"] is None
