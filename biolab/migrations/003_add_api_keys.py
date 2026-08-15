"""Migration 003: add the api_keys table.

Supports per-caller rate-limit fairness on the public server: unauthenticated
callers share a small pool, each API key gets its own higher, isolated budget.
A brand-new database already gets this table from db.py's schema; this script
is for databases created before this migration existed.
"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0
);
"""


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print("api_keys table present.")


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "biolab.db"
    migrate(db_path)
