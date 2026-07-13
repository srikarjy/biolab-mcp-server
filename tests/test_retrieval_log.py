"""Tests for the one module that writes to the retrieval log.

Uses a real temporary SQLite file per test (via pytest's tmp_path), not an in-memory
mock — sqlite3 is the real production engine here, so there's nothing to gain by
faking it.
"""

from biolab import db, retrieval_log


def test_write_retrieval_persists_a_real_row(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    record = retrieval_log.write_retrieval(
        conn,
        query_text="BRCA1 pancreatic cancer",
        pmid="42431391",
        agent_id="aletheia:advocate",
        medline_status="MEDLINE",
        pub_status="ppublish",
        raw_response="<PubmedArticle/>",
    )

    row = conn.execute(
        "SELECT query_text, pmid, agent_id, medline_status, pub_status, raw_response "
        "FROM retrievals WHERE retrieval_id = ?",
        (record.retrieval_id,),
    ).fetchone()

    assert row == (
        "BRCA1 pancreatic cancer",
        "42431391",
        "aletheia:advocate",
        "MEDLINE",
        "ppublish",
        "<PubmedArticle/>",
    )


def test_write_retrieval_generates_a_unique_id_per_call(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    first = retrieval_log.write_retrieval(
        conn, "q", "1", "a", "MEDLINE", "ppublish", "<x/>"
    )
    second = retrieval_log.write_retrieval(
        conn, "q", "2", "a", "MEDLINE", "ppublish", "<x/>"
    )

    assert first.retrieval_id != second.retrieval_id
    count = conn.execute("SELECT count(*) FROM retrievals").fetchone()[0]
    assert count == 2


def test_write_retrieval_sets_a_retrieved_at_timestamp(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    record = retrieval_log.write_retrieval(
        conn, "q", "1", "a", "MEDLINE", "ppublish", "<x/>"
    )
    assert record.retrieved_at
