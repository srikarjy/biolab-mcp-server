"""Migration 002: add prev_hash column, turning response_hash into a hash chain.

Before this migration, response_hash = sha256(raw_response) — tampering with or
deleting a row is undetectable, since each row's hash is independent of every
other row. After this migration, each new row's response_hash also covers the
previous row's response_hash, so altering or deleting any row breaks the chain
for every row after it. See retrieval_log.get_last_hash / verify_chain.

Existing rows get prev_hash = '' (they predate the chain and cannot be
retroactively chained without invalidating their original response_hash).
"""

import sqlite3


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(retrievals)").fetchall()}
    if "prev_hash" not in columns:
        conn.execute("ALTER TABLE retrievals ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''")
        conn.commit()
        print("Added prev_hash column to retrievals.")
    else:
        print("prev_hash column already present; nothing to do.")

    conn.close()


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "biolab.db"
    migrate(db_path)
