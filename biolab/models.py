"""Retrieval record schema — shared by db.py (storage) and server.py (tool output)."""

from dataclasses import dataclass


@dataclass
class RetrievalRecord:
    retrieval_id: str
    source: str
    external_id: str
    query_text: str
    retrieved_at: str  # ISO 8601, UTC
    agent_id: str
    source_metadata: str  # JSON string
    raw_response: str
    snapshot: str  # JSON string
    response_hash: str
