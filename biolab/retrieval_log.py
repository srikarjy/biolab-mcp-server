"""The only module that writes to the retrieval log. One writer, one place — BLUEPRINT.md §5.

DB-write failures are not caught here — they propagate to the caller uncaught, hard-failing
the tool call rather than risking a paper returned without a retrieval_id. See BLUEPRINT.md §2
step 4 for why no retry logic exists.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

from biolab.models import RetrievalRecord


def write_retrieval(
    conn: sqlite3.Connection,
    query_text: str,
    pmid: str,
    agent_id: str,
    medline_status: str,
    pub_status: str,
    raw_response: str,
) -> RetrievalRecord:
    record = RetrievalRecord(
        retrieval_id=str(uuid.uuid4()),
        query_text=query_text,
        pmid=pmid,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        agent_id=agent_id,
        medline_status=medline_status,
        pub_status=pub_status,
        raw_response=raw_response,
    )
    conn.execute(
        """
        INSERT INTO retrievals
            (retrieval_id, query_text, pmid, retrieved_at, agent_id,
             medline_status, pub_status, raw_response)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.retrieval_id,
            record.query_text,
            record.pmid,
            record.retrieved_at,
            record.agent_id,
            record.medline_status,
            record.pub_status,
            record.raw_response,
        ),
    )
    conn.commit()
    return record
