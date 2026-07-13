"""Retrieval record schema — shared by db.py (storage) and server.py (tool output)."""

from dataclasses import dataclass


@dataclass
class RetrievalRecord:
    retrieval_id: str
    query_text: str
    pmid: str
    retrieved_at: str  # ISO 8601, UTC
    agent_id: str
    medline_status: str
    pub_status: str
    raw_response: str
