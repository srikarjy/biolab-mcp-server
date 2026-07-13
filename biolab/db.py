"""SQLite connection and schema setup. Migration trigger to Postgres: BLUEPRINT.md §6 (not yet met)."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS retrievals (
    retrieval_id   TEXT PRIMARY KEY,
    query_text     TEXT NOT NULL,
    pmid           TEXT NOT NULL,
    retrieved_at   TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    medline_status TEXT NOT NULL,
    pub_status     TEXT NOT NULL,
    raw_response   TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn
