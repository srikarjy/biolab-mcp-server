"""MCP server entrypoint. Registers the search_pubmed and get_retrieval tools."""

import os
import sys

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from biolab import (
    auth,
    biorxiv_client,
    clinicaltrials_client,
    db,
    europepmc_client,
    pubmed_client,
    retrieval_log,
)

DB_PATH = os.environ.get("BIOLAB_DB_PATH", "biolab.db")
MAX_RESULTS_CAP = 50  # hard ceiling — an uncapped max_results lets a caller force
                        # unbounded memory use and DB writes per call; 50 matches
                        # PubMed's own esearch API default retmax

mcp = FastMCP(
    "biolab",
    host=os.environ.get("BIOLAB_HOST", "0.0.0.0"),
    port=int(os.environ.get("BIOLAB_PORT", "8000")),
)
_conn = db.connect(DB_PATH)

# Start background writer for thread-safe DB writes
retrieval_log.start_writer(DB_PATH)


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
        retrieval_input = pubmed_client.paper_to_retrieval_input(paper)
        record = retrieval_log.write_retrieval(
            _conn,
            query_text=query,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        results.append({
            "pmid": paper.pmid,
            "retrieval_id": record.retrieval_id,
            "title": paper.title,
            "abstract": paper.abstract,
        })

    return {"query_echo": query, "papers": results}


@mcp.tool()
def search_europepmc(query: str, agent_id: str, max_results: int = 5) -> dict:
    """Search Europe PMC and log every retrieved article to the audit trail.

    Args:
        query: exact search string, sent to Europe PMC verbatim — no normalization
        agent_id: which agent is asking, e.g. "aletheia:advocate"
        max_results: how many articles to retrieve (default 5)
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not agent_id.strip():
        raise ValueError("agent_id must not be empty")
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_CAP}")

    articles = europepmc_client.search_and_fetch(query, max_results)
    if not articles:
        raise ValueError(f"no Europe PMC results for query: {query!r}")

    results = []
    for article in articles:
        retrieval_input = europepmc_client.paper_to_retrieval_input(article)
        record = retrieval_log.write_retrieval(
            _conn,
            query_text=query,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        results.append({
            "id": article.id,
            "retrieval_id": record.retrieval_id,
            "title": article.title,
            "abstract": article.abstract_text,
        })

    return {"query_echo": query, "articles": results}


@mcp.tool()
def search_clinicaltrials(query: str, agent_id: str, max_results: int = 5) -> dict:
    """Search ClinicalTrials.gov and log every retrieved study to the audit trail.

    Args:
        query: condition/disease search string, sent to ClinicalTrials.gov verbatim
        agent_id: which agent is asking, e.g. "aletheia:advocate"
        max_results: how many studies to retrieve (default 5)
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not agent_id.strip():
        raise ValueError("agent_id must not be empty")
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_CAP}")

    studies = clinicaltrials_client.search_and_fetch(query, max_results)
    if not studies:
        raise ValueError(f"no ClinicalTrials.gov results for query: {query!r}")

    results = []
    for study in studies:
        retrieval_input = clinicaltrials_client.paper_to_retrieval_input(study)
        record = retrieval_log.write_retrieval(
            _conn,
            query_text=query,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        results.append({
            "nct_id": study.nct_id,
            "retrieval_id": record.retrieval_id,
            "title": study.brief_title,
            "status": study.overall_status,
            "phase": study.phase,
        })

    return {"query_echo": query, "studies": results}


@mcp.tool()
def search_biorxiv(category: str, agent_id: str, max_results: int = 5, server: str = "biorxiv") -> dict:
    """List bioRxiv/medRxiv preprints by category and log each to the audit trail.

    No free-text search exists on this API — only category listing (last 30 days).

    Args:
        category: category, e.g. "neuroscience", "bioinformatics", or "all"
        agent_id: which agent is asking, e.g. "aletheia:advocate"
        max_results: how many preprints to retrieve (default 5)
        server: "biorxiv" or "medrxiv" (default "biorxiv")
    """
    if not category.strip():
        raise ValueError("category must not be empty")
    if not agent_id.strip():
        raise ValueError("agent_id must not be empty")
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_CAP}")
    if server not in ("biorxiv", "medrxiv"):
        raise ValueError('server must be "biorxiv" or "medrxiv"')

    preprints = biorxiv_client.list_and_fetch(server, category, max_results)
    if not preprints:
        raise ValueError(f"no {server} results for category: {category!r}")

    query_text = f"category:{category}"
    results = []
    for preprint in preprints:
        retrieval_input = biorxiv_client.paper_to_retrieval_input(preprint, server)
        record = retrieval_log.write_retrieval(
            _conn,
            query_text=query_text,
            external_id=retrieval_input["external_id"],
            agent_id=agent_id,
            source=retrieval_input["source"],
            source_metadata=retrieval_input["source_metadata"],
            raw_response=retrieval_input["raw_response"],
            snapshot=retrieval_input["snapshot"],
        )
        results.append({
            "doi": preprint.doi,
            "retrieval_id": record.retrieval_id,
            "title": preprint.title,
            "date": preprint.date,
            "category": preprint.category,
        })

    return {"category_echo": category, "preprints": results}


@mcp.tool()
def get_retrieval(retrieval_id: str) -> dict:
    """Retrieve a full retrieval record by its retrieval_id.

    Args:
        retrieval_id: the UUID returned by search_pubmed
    """
    if not retrieval_id.strip():
        raise ValueError("retrieval_id must not be empty")

    record = retrieval_log.get_retrieval(_conn, retrieval_id)
    if record is None:
        raise ValueError(f"no retrieval found for id: {retrieval_id!r}")

    import json
    return {
        "retrieval_id": record.retrieval_id,
        "source": record.source,
        "external_id": record.external_id,
        "query_text": record.query_text,
        "retrieved_at": record.retrieved_at,
        "agent_id": record.agent_id,
        "source_metadata": json.loads(record.source_metadata),
        "raw_response": record.raw_response,
        "snapshot": json.loads(record.snapshot),
        "response_hash": record.response_hash,
    }


class ApiKeyAuthMiddleware:
    """Sets auth.current_identity for every HTTP request, based on an optional
    `Authorization: Bearer <key>` header.

    The server stays open to callers with no header at all (identity =
    "anonymous", a low shared rate-limit budget — see pubmed_client.py). A
    header that doesn't match a valid, non-revoked key is rejected outright
    rather than silently downgraded, so a typo'd key fails loudly instead of
    quietly running at the anonymous tier.

    Plain ASGI (not Starlette's BaseHTTPMiddleware) because streamable-http
    keeps connections open for server-sent events; BaseHTTPMiddleware's
    response buffering doesn't play well with that.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        identity = "anonymous"
        if auth_header.startswith("Bearer "):
            raw_key = auth_header[len("Bearer ") :].strip()
            resolved = auth.verify_api_key(_conn, raw_key)
            if resolved is None:
                response = JSONResponse({"error": "invalid or revoked API key"}, status_code=401)
                await response(scope, receive, send)
                return
            identity = resolved

        token = auth.current_identity.set(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            auth.current_identity.reset(token)


if __name__ == "__main__":
    # stdio mode serves local same-machine clients that spawn this server as
    # a subprocess (e.g. Aletheia's mcp_client) -- no HTTP port, no API-key
    # middleware; the caller is anonymous (auth.current_identity stays None),
    # which is the same trust domain as the process that spawned it.
    if "--stdio" in sys.argv or os.environ.get("BIOLAB_TRANSPORT", "").lower() == "stdio":
        try:
            mcp.run(transport="stdio")
        finally:
            retrieval_log.stop_writer()
    else:
        import uvicorn

        app = mcp.streamable_http_app()
        app.add_middleware(ApiKeyAuthMiddleware)

        try:
            uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
        finally:
            retrieval_log.stop_writer()
