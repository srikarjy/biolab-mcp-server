"""Tests for the one module that writes to the retrieval log.

Uses a real temporary SQLite file per test (via pytest's tmp_path), not an in-memory
mock — sqlite3 is the real production engine here, so there's nothing to gain by
faking it.
"""

import json

from biolab import db, retrieval_log


def test_write_retrieval_persists_a_real_row(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    record = retrieval_log.write_retrieval(
        conn,
        query_text="BRCA1 pancreatic cancer",
        external_id="42431391",
        agent_id="aletheia:advocate",
        source="pubmed",
        source_metadata={"medline_status": "MEDLINE", "pub_status": "ppublish"},
        raw_response="<PubmedArticle/>",
        snapshot={"title": "Test", "abstract": "Test abstract"},
    )

    row = conn.execute(
        "SELECT query_text, external_id, agent_id, source, source_metadata, raw_response, snapshot "
        "FROM retrievals WHERE retrieval_id = ?",
        (record.retrieval_id,),
    ).fetchone()

    assert row[0] == "BRCA1 pancreatic cancer"
    assert row[1] == "42431391"
    assert row[2] == "aletheia:advocate"
    assert row[3] == "pubmed"
    assert json.loads(row[4]) == {"medline_status": "MEDLINE", "pub_status": "ppublish"}
    assert row[5] == "<PubmedArticle/>"
    assert json.loads(row[6]) == {"title": "Test", "abstract": "Test abstract"}


def test_write_retrieval_generates_a_unique_id_per_call(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    first = retrieval_log.write_retrieval(
        conn, "q", "1", "a", "pubmed", {}, "<x/>", {}
    )
    second = retrieval_log.write_retrieval(
        conn, "q", "2", "a", "pubmed", {}, "<x/>", {}
    )

    assert first.retrieval_id != second.retrieval_id
    count = conn.execute("SELECT count(*) FROM retrievals").fetchone()[0]
    assert count == 2


def test_write_retrieval_sets_a_retrieved_at_timestamp(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    record = retrieval_log.write_retrieval(
        conn, "q", "1", "a", "pubmed", {}, "<x/>", {}
    )
    assert record.retrieved_at


def test_get_retrieval_returns_record(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    written = retrieval_log.write_retrieval(
        conn,
        query_text="test query",
        external_id="12345",
        agent_id="test:agent",
        source="pubmed",
        source_metadata={"key": "value"},
        raw_response="<xml/>",
        snapshot={"title": "Test Paper"},
    )

    retrieved = retrieval_log.get_retrieval(conn, written.retrieval_id)
    assert retrieved is not None
    assert retrieved.retrieval_id == written.retrieval_id
    assert retrieved.query_text == "test query"
    assert retrieved.external_id == "12345"
    assert retrieved.agent_id == "test:agent"
    assert retrieved.source == "pubmed"
    assert json.loads(retrieved.source_metadata) == {"key": "value"}
    assert retrieved.raw_response == "<xml/>"
    assert json.loads(retrieved.snapshot) == {"title": "Test Paper"}


def test_get_retrieval_returns_none_for_missing(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    result = retrieval_log.get_retrieval(conn, "non-existent-id")
    assert result is None