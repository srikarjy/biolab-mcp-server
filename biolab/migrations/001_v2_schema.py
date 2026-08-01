"""Migration 001: v1 -> v2 schema generalization.

v1 schema (PubMed-specific):
  retrieval_id, query_text, pmid, retrieved_at, agent_id, medline_status, pub_status, raw_response

v2 schema (source-agnostic):
  retrieval_id, source, external_id, query_text, retrieved_at, agent_id,
  source_metadata (JSON), raw_response, snapshot (JSON), response_hash
"""

import hashlib
import json
import sqlite3

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS retrievals_v2 (
    retrieval_id     TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    query_text       TEXT NOT NULL,
    retrieved_at     TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    source_metadata  TEXT NOT NULL,
    raw_response     TEXT NOT NULL,
    snapshot         TEXT NOT NULL,
    response_hash    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrievals_v2_external_id ON retrievals_v2(external_id);
CREATE INDEX IF NOT EXISTS idx_retrievals_v2_agent_id ON retrievals_v2(agent_id);
CREATE INDEX IF NOT EXISTS idx_retrievals_v2_retrieved_at ON retrievals_v2(retrieved_at);
CREATE INDEX IF NOT EXISTS idx_retrievals_v2_source ON retrievals_v2(source);
"""


def compute_hash(raw_response: str) -> str:
    return hashlib.sha256(raw_response.encode("utf-8")).hexdigest()


def build_snapshot(raw_xml: str, medline_status: str, pub_status: str) -> dict:
    """Extract structured fields from raw PubMed XML for the snapshot."""
    import defusedxml.ElementTree as SafeET

    root = SafeET.fromstring(raw_xml)
    medline_citation = root.find("MedlineCitation")
    article = medline_citation.find("Article") if medline_citation is not None else None

    def full_text(elem):
        return "".join(elem.itertext()) if elem is not None else ""

    title = full_text(article.find(".//ArticleTitle")) if article is not None else ""
    abstract = " ".join(
        full_text(node)
        for node in medline_citation.findall(".//AbstractText")
    ) if medline_citation is not None else ""

    authors = []
    if article is not None:
        for author in article.findall(".//Author"):
            lastname = full_text(author.find("LastName"))
            fore = full_text(author.find("ForeName"))
            initials = full_text(author.find("Initials"))
            if lastname or fore or initials:
                authors.append({
                    "lastname": lastname,
                    "forename": fore,
                    "initials": initials,
                })

    journal = {}
    if article is not None:
        journal_elem = article.find(".//Journal")
        if journal_elem is not None:
            journal = {
                "title": full_text(journal_elem.find("Title")),
                "iso_abbreviation": full_text(journal_elem.find("ISOAbbreviation")),
                "issn": full_text(journal_elem.find(".//ISSN")),
                "pub_date": full_text(journal_elem.find(".//PubDate")),
            }

    pub_types = [
        full_text(pt) for pt in root.findall(".//PublicationType")
    ]

    mesh_terms = [
        full_text(mh.find("DescriptorName"))
        for mh in root.findall(".//MeshHeading")
        if mh.find("DescriptorName") is not None
    ]

    doi = ""
    for id_elem in root.findall(".//ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = full_text(id_elem)
            break

    return {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "publication_types": pub_types,
        "mesh_terms": mesh_terms,
        "doi": doi,
        "medline_status": medline_status,
        "pub_status": pub_status,
    }


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    # Create v2 table
    conn.executescript(SCHEMA_V2)

    # Check if v1 table exists and has data
    v1_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='retrievals'"
    ).fetchone()

    if v1_exists:
        rows = conn.execute(
            "SELECT retrieval_id, query_text, pmid, retrieved_at, agent_id, "
            "medline_status, pub_status, raw_response FROM retrievals"
        ).fetchall()

        print(f"Migrating {len(rows)} rows from v1 to v2...")

        for row in rows:
            retrieval_id, query_text, pmid, retrieved_at, agent_id, \
                medline_status, pub_status, raw_response = row

            source_metadata = json.dumps({
                "medline_status": medline_status,
                "pub_status": pub_status,
            })

            snapshot = build_snapshot(raw_response, medline_status, pub_status)
            response_hash = compute_hash(raw_response)

            conn.execute(
                """
                INSERT INTO retrievals_v2
                    (retrieval_id, source, external_id, query_text, retrieved_at,
                     agent_id, source_metadata, raw_response, snapshot, response_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_id,
                    "pubmed",
                    pmid,
                    query_text,
                    retrieved_at,
                    agent_id,
                    source_metadata,
                    raw_response,
                    json.dumps(snapshot),
                    response_hash,
                ),
            )

        print(f"Migrated {len(rows)} rows successfully.")

        # Verify
        count = conn.execute("SELECT COUNT(*) FROM retrievals_v2").fetchone()[0]
        print(f"Verification: {count} rows in retrievals_v2")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "biolab.db"
    migrate(db_path)