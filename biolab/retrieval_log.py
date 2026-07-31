"""The only module that writes to the retrieval log. One writer, one place.

DB-write failures are not caught here — they propagate to the caller uncaught, hard-failing
the tool call rather than risking a paper returned without a retrieval_id.

Includes a write-queue for concurrent access safety (v2+).
"""

import json
import queue
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from biolab.models import RetrievalRecord


_write_queue: queue.Queue[tuple] = queue.Queue()
_writer_thread: threading.Thread | None = None
_writer_stop = threading.Event()
_writer_db_path: str | None = None


def _writer_loop(db_path: str) -> None:
    """Writer loop runs in its own thread with its own SQLite connection."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    try:
        while not _writer_stop.is_set() or not _write_queue.empty():
            try:
                item = _write_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            record, done_event = item
            try:
                conn.execute(
                    """
                    INSERT INTO retrievals
                        (retrieval_id, source, external_id, query_text, retrieved_at,
                         agent_id, source_metadata, raw_response, snapshot, response_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.retrieval_id,
                        record.source,
                        record.external_id,
                        record.query_text,
                        record.retrieved_at,
                        record.agent_id,
                        record.source_metadata,
                        record.raw_response,
                        record.snapshot,
                        record.response_hash,
                    ),
                )
                conn.commit()
            finally:
                done_event.set()
    finally:
        conn.close()


def start_writer(db_path: str) -> None:
    """Start the background writer thread (call once at server startup)."""
    global _writer_thread, _writer_db_path
    if _writer_thread is not None and _writer_thread.is_alive():
        if _writer_db_path == db_path:
            return  # already running for this db
        stop_writer()  # different db, restart
    _writer_stop.clear()
    _writer_db_path = db_path
    _writer_thread = threading.Thread(target=_writer_loop, args=(db_path,), daemon=True)
    _writer_thread.start()


def stop_writer() -> None:
    """Stop the background writer thread (call at shutdown)."""
    _writer_stop.set()
    _write_queue.put(None)
    if _writer_thread is not None:
        _writer_thread.join(timeout=5)


def _write_sync(
    conn: sqlite3.Connection,
    record: RetrievalRecord,
) -> None:
    """Synchronous write fallback (used in tests or when writer not running)."""
    conn.execute(
        """
        INSERT INTO retrievals
            (retrieval_id, source, external_id, query_text, retrieved_at,
             agent_id, source_metadata, raw_response, snapshot, response_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.retrieval_id,
            record.source,
            record.external_id,
            record.query_text,
            record.retrieved_at,
            record.agent_id,
            record.source_metadata,
            record.raw_response,
            record.snapshot,
            record.response_hash,
        ),
    )
    conn.commit()


def write_retrieval(
    conn: sqlite3.Connection,
    query_text: str,
    external_id: str,
    agent_id: str,
    source: str,
    source_metadata: dict,
    raw_response: str,
    snapshot: dict,
) -> RetrievalRecord:
    """Write a retrieval record. Uses background writer for thread safety."""
    import hashlib

    response_hash = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()

    record = RetrievalRecord(
        retrieval_id=str(uuid.uuid4()),
        source=source,
        external_id=external_id,
        query_text=query_text,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        agent_id=agent_id,
        source_metadata=json.dumps(source_metadata),
        raw_response=raw_response,
        snapshot=json.dumps(snapshot),
        response_hash=response_hash,
    )

    # Check if writer is running for this database
    global _writer_thread, _writer_db_path
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    if _writer_thread is not None and _writer_thread.is_alive() and _writer_db_path == db_path:
        # Use background writer
        done_event = threading.Event()
        _write_queue.put((record, done_event))
        done_event.wait()
    else:
        # Fallback to synchronous write (tests, or writer not started)
        _write_sync(conn, record)

    return record


def get_retrieval(conn: sqlite3.Connection, retrieval_id: str) -> RetrievalRecord | None:
    """Retrieve a single retrieval record by ID."""
    row = conn.execute(
        """
        SELECT retrieval_id, source, external_id, query_text, retrieved_at,
               agent_id, source_metadata, raw_response, snapshot, response_hash
        FROM retrievals WHERE retrieval_id = ?
        """,
        (retrieval_id,),
    ).fetchone()

    if row is None:
        return None

    return RetrievalRecord(
        retrieval_id=row[0],
        source=row[1],
        external_id=row[2],
        query_text=row[3],
        retrieved_at=row[4],
        agent_id=row[5],
        source_metadata=row[6],
        raw_response=row[7],
        snapshot=row[8],
        response_hash=row[9],
    )
