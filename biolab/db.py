"""libSQL connection and schema setup.

Uses the `libsql` package (SQLite-compatible, DB-API-like) so the same code path
works against a local file and a remote Turso database. When TURSO_DATABASE_URL
is set, that takes precedence over the given local db_path; otherwise db_path is
used as a plain local SQLite/libSQL file, same as before.
"""

import os
from typing import Any

import libsql

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS retrievals (
    retrieval_id     TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    query_text       TEXT NOT NULL,
    retrieved_at     TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    source_metadata  TEXT NOT NULL,
    raw_response     TEXT NOT NULL,
    snapshot         TEXT NOT NULL,
    response_hash    TEXT NOT NULL,
    prev_hash        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_retrievals_external_id ON retrievals(external_id);
CREATE INDEX IF NOT EXISTS idx_retrievals_agent_id ON retrievals(agent_id);
CREATE INDEX IF NOT EXISTS idx_retrievals_retrieved_at ON retrievals(retrieved_at);
CREATE INDEX IF NOT EXISTS idx_retrievals_source ON retrievals(source);
"""

# Tracks the target (Turso URL or local path) most recently connected to, so
# retrieval_log's writer-matching logic doesn't have to introspect the
# connection object (libSQL's remote-connection PRAGMA behavior isn't
# guaranteed to mirror sqlite3's).
_current_target: str | None = None


def resolve_target(db_path: str) -> tuple[str, str | None]:
    """Return (target, auth_token). target is the Turso URL if configured, else db_path."""
    url = os.environ.get("TURSO_DATABASE_URL")
    if url:
        return url, os.environ.get("TURSO_AUTH_TOKEN")
    return db_path, None


def current_target() -> str | None:
    """The target most recently passed to connect()."""
    return _current_target


def connect(db_path: str) -> Any:
    global _current_target
    target, token = resolve_target(db_path)

    conn = libsql.connect(target, auth_token=token) if token else libsql.connect(target)
    conn.executescript(SCHEMA_V2)
    conn.commit()
    _current_target = target
    return conn
