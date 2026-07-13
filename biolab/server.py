"""MCP server entrypoint. Registers the search_pubmed tool — see BLUEPRINT.md §2 for the
full request flow (including why steps 2 and 4 both hard-fail instead of degrading).
"""

import os

from mcp.server.fastmcp import FastMCP

from biolab import db, pubmed_client, retrieval_log

DB_PATH = os.environ.get("BIOLAB_DB_PATH", "biolab.db")
MAX_RESULTS_CAP = 50  # hard ceiling — an uncapped max_results lets a caller force
                        # unbounded memory use and DB writes per call; 50 matches
                        # PubMed's own esearch API default retmax

mcp = FastMCP("biolab")
_conn = db.connect(DB_PATH)


@mcp.tool()
def search_pubmed(query: str, agent_id: str, max_results: int = 5) -> dict:
    """Search PubMed and log every retrieved paper to the audit trail.

    Args:
        query: exact search string, sent to PubMed verbatim — no normalization
        agent_id: which agent is asking, e.g. "aletheia:advocate"
        max_results: how many papers to retrieve (default 5)
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not agent_id.strip():
        raise ValueError("agent_id must not be empty")
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_CAP}")

    papers = pubmed_client.search_and_fetch(query, max_results)
    if not papers:
        raise ValueError(f"no PubMed results for query: {query!r}")

    results = []
    for paper in papers:
        record = retrieval_log.write_retrieval(
            _conn,
            query_text=query,
            pmid=paper.pmid,
            agent_id=agent_id,
            medline_status=paper.medline_status,
            pub_status=paper.pub_status,
            raw_response=paper.raw_xml,
        )
        results.append({
            "pmid": paper.pmid,
            "retrieval_id": record.retrieval_id,
            "title": paper.title,
            "abstract": paper.abstract,
        })

    return {"query_echo": query, "papers": results}


if __name__ == "__main__":
    mcp.run()
