"""YITING Gateway Database — SQLite schema and connection management.

Single-file SQLite database for:
- Incidents and state machine
- Card chain with integrity hashing
- Suppression rules (bounded local learning)
- Nonce lifecycle for human approval
- Authorization lifecycle for PolicyAuthorization
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Default DB path — can be overridden via env var
DEFAULT_DB_PATH = Path("yiting.db")

SCHEMA = """
-- Alerts (raw ingest, before room creation)
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT UNIQUE NOT NULL,
    fingerprint TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    preliminary_severity TEXT DEFAULT 'unknown',
    security_relevant INTEGER DEFAULT 0,
    raw_payload TEXT,
    received_at TEXT NOT NULL,
    incident_id TEXT,  -- NULL until correlated to an incident
    suppressed INTEGER DEFAULT 0
);

-- Incidents (state machine)
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'DETECTED',
    severity TEXT,
    room_id TEXT,
    room_alias_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    alert_count INTEGER DEFAULT 1
);

-- Cards (integrity chain — core of the audit trail)
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    card_type TEXT NOT NULL,
    card_hash TEXT NOT NULL,
    card_json TEXT NOT NULL,
    idempotency_key TEXT,
    prepared_by_role TEXT,     -- Agent role that prepared (for confirm-time ACL)
    request_fp TEXT,           -- Pre-enrichment request fingerprint (for idempotency)
    created_at TEXT NOT NULL,
    published_at TEXT,        -- NULL until confirmed published to an incident room
    room_message_id TEXT,     -- Room message ID published after confirmation
    UNIQUE(incident_id, sequence_number),
    UNIQUE(incident_id, idempotency_key),
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
);

-- Suppression rules (Gateway SQLite)
CREATE TABLE IF NOT EXISTS suppression_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    reason TEXT,
    source_incident_id TEXT,  -- The FALSE_ALARM incident that created this rule
    created_at TEXT NOT NULL,
    expires_at TEXT,           -- Optional TTL
    suppression_count INTEGER DEFAULT 0,  -- How many alerts suppressed by this rule
    max_suppressions INTEGER DEFAULT 3,   -- Bounded — max 3 suppressions per rule (Council mandate)
    active INTEGER DEFAULT 1
);

-- Nonces (human approval challenge-response)
CREATE TABLE IF NOT EXISTS nonces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    nonce TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    action_hash TEXT NOT NULL,     -- SHA-256 of ExecutionEnvelopes — binds approval to exact actions
    plan_revision INTEGER DEFAULT 1,
    expiry TEXT NOT NULL,
    consumed INTEGER DEFAULT 0,
    invalidated INTEGER DEFAULT 0,
    consumed_by TEXT,              -- sender_id of the human who consumed (audit trail)
    consumed_at TEXT,              -- ISO timestamp of consumption
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(incident_id, nonce)
);

-- Authorizations (PolicyAuthorization consumption tracking)
CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    authorization_type TEXT NOT NULL DEFAULT 'policy',  -- 'policy' or 'human_approval'
    plan_hash TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    policy_rule TEXT,
    envelopes_json TEXT,       -- JSON array of approved ExecutionEnvelopes
    expiry TEXT NOT NULL,
    consumed INTEGER DEFAULT 0, -- 0=unused, 1=consumed (single-use)
    consumed_at TEXT,          -- NULL until consumed
    consumed_by TEXT,          -- agent that consumed (operator)
    status TEXT DEFAULT 'PENDING',  -- PENDING -> PUBLISHED -> CONSUMED
    room_message_id TEXT,      -- Room message ID published after confirmation
    nonce TEXT,                -- Bound nonce for human_approval
    card_hash TEXT,            -- Bound card_hash of the sealed card
    created_at TEXT DEFAULT (datetime('now'))
);

-- Agent heartbeats (live status for dashboard)
CREATE TABLE IF NOT EXISTS heartbeats (
    agent_role TEXT PRIMARY KEY,
    agent_id TEXT,
    framework TEXT,
    model TEXT,
    display_name TEXT,
    persona_title TEXT,
    persona_temperament TEXT,
    last_seen TEXT NOT NULL
);

-- Gateway-owned incident rooms.  This is the Alibaba/Qwen collaboration
-- substrate for agent coordination.
CREATE TABLE IF NOT EXISTS incident_rooms (
    room_id TEXT PRIMARY KEY,
    incident_id TEXT UNIQUE,
    title TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
);

CREATE TABLE IF NOT EXISTS incident_room_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    role TEXT,
    display_name TEXT,
    joined_at TEXT NOT NULL,
    UNIQUE(room_id, participant_id),
    FOREIGN KEY (room_id) REFERENCES incident_rooms(room_id)
);

CREATE TABLE IF NOT EXISTS incident_room_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    room_id TEXT NOT NULL,
    incident_id TEXT,
    sender_id TEXT NOT NULL,
    sender_role TEXT,
    sender_type TEXT DEFAULT 'Agent',
    content TEXT NOT NULL,
    mentions_json TEXT DEFAULT '[]',
    message_type TEXT DEFAULT 'message',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    inserted_at TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES incident_rooms(room_id),
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alerts_incident ON alerts(incident_id);
CREATE INDEX IF NOT EXISTS idx_cards_incident ON cards(incident_id);
CREATE INDEX IF NOT EXISTS idx_cards_hash ON cards(card_hash);
CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents(state);
CREATE INDEX IF NOT EXISTS idx_suppression_fingerprint ON suppression_rules(fingerprint, active);
CREATE INDEX IF NOT EXISTS idx_nonces_incident ON nonces(incident_id);
CREATE INDEX IF NOT EXISTS idx_incident_rooms_incident ON incident_rooms(incident_id);
CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON incident_room_messages(room_id, id);
CREATE INDEX IF NOT EXISTS idx_room_messages_incident ON incident_room_messages(incident_id, id);
"""


def get_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create a database connection with proper settings.

    Uses isolation_level=None for explicit transaction control
    (required by seal_card's BEGIN IMMEDIATE pattern).
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    db = sqlite3.connect(str(path), isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Initialize the database with schema and return connection."""
    db = get_db(db_path)
    db.executescript(SCHEMA)
    _migrate(db)
    return db


def _migrate(db: sqlite3.Connection) -> None:
    """Forward-only migrations for schema additions.

    Each migration is idempotent — safe to re-run on every startup.
    """
    # Round 10: add request_fp column for pre-enrichment idempotency
    cols = {row[1] for row in db.execute("PRAGMA table_info(cards)").fetchall()}
    if "request_fp" not in cols:
        db.execute("ALTER TABLE cards ADD COLUMN request_fp TEXT")

    # Nonce consumption: add action_hash, consumed_by, consumed_at
    nonce_cols = {row[1] for row in db.execute("PRAGMA table_info(nonces)").fetchall()}
    if "action_hash" not in nonce_cols:
        db.execute("ALTER TABLE nonces ADD COLUMN action_hash TEXT NOT NULL DEFAULT ''")
    if "consumed_by" not in nonce_cols:
        db.execute("ALTER TABLE nonces ADD COLUMN consumed_by TEXT")
    if "consumed_at" not in nonce_cols:
        db.execute("ALTER TABLE nonces ADD COLUMN consumed_at TEXT")
    if "challenge_message_id" not in nonce_cols:
        db.execute("ALTER TABLE nonces ADD COLUMN challenge_message_id TEXT")

    incident_cols = {row[1] for row in db.execute("PRAGMA table_info(incidents)").fetchall()}
    if "room_id" not in incident_cols:
        db.execute("ALTER TABLE incidents ADD COLUMN room_id TEXT")
        incident_cols.add("room_id")
    if "room_alias_id" not in incident_cols:
        db.execute("ALTER TABLE incidents ADD COLUMN room_alias_id TEXT")
        incident_cols.add("room_alias_id")

    db.execute(
        """CREATE TABLE IF NOT EXISTS heartbeats (
            agent_role TEXT PRIMARY KEY,
            agent_id TEXT,
            framework TEXT,
            model TEXT,
            last_seen TEXT NOT NULL
        )"""
    )
    heartbeat_cols = {row[1] for row in db.execute("PRAGMA table_info(heartbeats)").fetchall()}
    if "display_name" not in heartbeat_cols:
        db.execute("ALTER TABLE heartbeats ADD COLUMN display_name TEXT")
    if "persona_title" not in heartbeat_cols:
        db.execute("ALTER TABLE heartbeats ADD COLUMN persona_title TEXT")
    if "persona_temperament" not in heartbeat_cols:
        db.execute("ALTER TABLE heartbeats ADD COLUMN persona_temperament TEXT")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS incident_rooms (
            room_id TEXT PRIMARY KEY,
            incident_id TEXT UNIQUE,
            title TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE TABLE IF NOT EXISTS incident_room_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            participant_id TEXT NOT NULL,
            role TEXT,
            display_name TEXT,
            joined_at TEXT NOT NULL,
            UNIQUE(room_id, participant_id),
            FOREIGN KEY (room_id) REFERENCES incident_rooms(room_id)
        );

        CREATE TABLE IF NOT EXISTS incident_room_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            room_id TEXT NOT NULL,
            incident_id TEXT,
            sender_id TEXT NOT NULL,
            sender_role TEXT,
            sender_type TEXT DEFAULT 'Agent',
            content TEXT NOT NULL,
            mentions_json TEXT DEFAULT '[]',
            message_type TEXT DEFAULT 'message',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            inserted_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES incident_rooms(room_id),
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );
        CREATE INDEX IF NOT EXISTS idx_incident_rooms_incident ON incident_rooms(incident_id);
        CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON incident_room_messages(room_id, id);
        CREATE INDEX IF NOT EXISTS idx_room_messages_incident ON incident_room_messages(incident_id, id);
        """
    )

    # Keep room_id and room_alias_id aligned for existing stored rows.
    db.execute(
        """
        UPDATE incidents
        SET room_id = COALESCE(room_id, room_alias_id)
        WHERE room_id IS NULL AND room_alias_id IS NOT NULL
        """
    )
    db.execute(
        """
        UPDATE incidents
        SET room_alias_id = COALESCE(room_alias_id, room_id)
        WHERE room_alias_id IS NULL AND room_id IS NOT NULL
        """
    )

    # Authorization table: ensure it exists on old databases
    db.executescript("""
        CREATE TABLE IF NOT EXISTS authorizations (
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
    """)

    # --- Migrate authorizations columns ---
    auth_cols = {row[1] for row in db.execute('PRAGMA table_info(authorizations)').fetchall()}
    for col, typedef in [
        ('authorization_type', 'TEXT DEFAULT \'policy\''),
        ('envelopes_json', 'TEXT'),
        ('consumed', 'INTEGER DEFAULT 0'),
        ('consumed_by', 'TEXT'),
        ('consumed_at', 'TEXT'),
        ('status', "TEXT DEFAULT 'PENDING'"),
        ('room_message_id', 'TEXT'),
        ('nonce', 'TEXT'),
        ('card_hash', 'TEXT'),
    ]:
        if col not in auth_cols:
            db.execute(f'ALTER TABLE authorizations ADD COLUMN {col} {typedef}')

    # Create indexes for the newly added columns
    db.execute("CREATE INDEX IF NOT EXISTS idx_auth_card_hash ON authorizations(card_hash)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_auth_incident_nonce_type ON authorizations(incident_id, nonce, authorization_type)")

    # Deterministic historical migration
    db.execute("""
        UPDATE authorizations SET status = 'CONSUMED'
        WHERE consumed_at IS NOT NULL AND (status IS NULL OR status = 'PENDING')
    """)
    db.execute("""
        UPDATE authorizations SET status = 'PUBLISHED'
        WHERE (status IS NULL OR status = 'PENDING')
        AND authorization_id IN (
            SELECT a.authorization_id FROM authorizations a
            JOIN cards c ON c.incident_id = a.incident_id
                AND c.card_type = 'PolicyAuthorization'
                AND c.published_at IS NOT NULL
        )
    """)

    # Backfill missing card_hash for PolicyAuthorization
    db.execute("""
        UPDATE authorizations
        SET card_hash = (
            SELECT c.card_hash FROM cards c
            WHERE c.incident_id = authorizations.incident_id
              AND c.card_type = 'PolicyAuthorization'
              AND json_extract(c.card_json, '$.authorization_id') = authorizations.authorization_id
        )
        WHERE authorization_type = 'policy' AND card_hash IS NULL
    """)

    # Backfill missing card_hash and nonce for StructuredApproval
    # We match using plan_hash and action_hash where unambiguously 1 card exists
    db.execute("""
        UPDATE authorizations
        SET 
            card_hash = (
                SELECT c.card_hash FROM cards c
                WHERE c.incident_id = authorizations.incident_id
                  AND c.card_type = 'StructuredApproval'
                  AND json_extract(c.card_json, '$.plan_hash') = authorizations.plan_hash
                  AND json_extract(c.card_json, '$.action_hash') = authorizations.action_hash
                LIMIT 1
            ),
            nonce = (
                SELECT json_extract(c.card_json, '$.nonce') FROM cards c
                WHERE c.incident_id = authorizations.incident_id
                  AND c.card_type = 'StructuredApproval'
                  AND json_extract(c.card_json, '$.plan_hash') = authorizations.plan_hash
                  AND json_extract(c.card_json, '$.action_hash') = authorizations.action_hash
                LIMIT 1
            )
        WHERE authorization_type = 'human_approval' AND card_hash IS NULL
    """)
