"""Tests for API key issuance/verification."""

from biolab import auth, db


def test_verify_api_key_accepts_a_freshly_created_key(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    raw_key = auth.create_api_key(conn, "alice", "user:alice")

    assert auth.verify_api_key(conn, raw_key) == "user:alice"


def test_verify_api_key_rejects_an_unknown_key(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    assert auth.verify_api_key(conn, "blk_not-a-real-key") is None


def test_verify_api_key_rejects_a_revoked_key(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    raw_key = auth.create_api_key(conn, "alice", "user:alice")
    auth.revoke_api_key(conn, "alice")

    assert auth.verify_api_key(conn, raw_key) is None


def test_revoke_api_key_returns_zero_for_an_unknown_label(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    assert auth.revoke_api_key(conn, "nobody") == 0


def test_list_api_keys_never_exposes_the_raw_key(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    raw_key = auth.create_api_key(conn, "alice", "user:alice")

    rows = auth.list_api_keys(conn)
    assert len(rows) == 1
    assert rows[0]["label"] == "alice"
    assert rows[0]["agent_id"] == "user:alice"
    assert rows[0]["revoked"] is False
    assert raw_key not in str(rows)


def test_two_different_keys_hash_to_different_rows(tmp_path):
    conn = db.connect(str(tmp_path / "test.db"))
    auth.create_api_key(conn, "alice", "user:alice")
    auth.create_api_key(conn, "bob", "user:bob")

    rows = auth.list_api_keys(conn)
    assert {r["label"] for r in rows} == {"alice", "bob"}
