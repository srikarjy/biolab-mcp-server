# Biolab MCP Server

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Go Version](https://img.shields.io/badge/go-1.23%2B-00ADD8)](https://golang.org)
[![MCP](https://img.shields.io/badge/MCP-1.28.1-purple)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/biolab-mcp)](https://pypi.org/project/biolab-mcp/)
[![Docker](https://img.shields.io/badge/docker-ghcr.io%2Fsrikarjy%2Fbiolab--mcp-blue)](https://github.com/srikarjy/biolab-mcp-server/pkgs/container/biolab-mcp)

> *"AI agents querying biological databases leave no audit trail. Six months later, nobody can answer: what exact query returned this result, when, and was that paper peer-reviewed at the time? Biolab solves that."*

A **dual-implementation** (Python + Go) [MCP](https://modelcontextprotocol.io) server that sits between AI agents and biological/scientific databases (PubMed, Europe PMC, ClinicalTrials.gov, bioRxiv/medRxiv). Every query is intercepted, logged with full retrieval context, and returns a `retrieval_id` that calling systems store alongside their reasoning traces — creating an end-to-end auditable chain from conclusion back to raw source.

**New to MCP?** It's a small, open standard (built by Anthropic) that lets an AI assistant — Claude, ChatGPT, Cursor, etc. — call out to external tools during a conversation. Add Biolab as an MCP server and any of those assistants gains four new abilities: searching PubMed, Europe PMC, ClinicalTrials.gov, and bioRxiv/medRxiv, with every single result permanently logged so it can be checked later.

## Use It Now — No Install

A hosted instance is running at `https://srikarjy025-biolab-mcp.hf.space/mcp`. Point your client at it and you're done — nothing to install, nothing to run locally, nothing to sign up for.

**Claude Code:**
```bash
claude mcp add --transport http biolab https://srikarjy025-biolab-mcp.hf.space/mcp
```

**Claude Desktop / Cursor** — add this to your MCP config file:
```json
{
  "mcpServers": {
    "biolab": {
      "url": "https://srikarjy025-biolab-mcp.hf.space/mcp"
    }
  }
}
```
(Add `"headers": {"Authorization": "Bearer <your key>"}` alongside `"url"` once you have a key — see the rate-limit note below.)

That's it — `search_pubmed`, `search_europepmc`, `search_clinicaltrials`, `search_biorxiv`, and `get_retrieval` are now available as tools your assistant can call. Every retrieval is written to a hash-chained audit trail you can inspect later (see [Audit Trail Schema](#audit-trail-schema-v2) below).

Also listed on the [official MCP Registry](https://registry.modelcontextprotocol.io) and [Smithery](https://smithery.ai/servers/srikarjy025/biolab-mcp) if you'd rather discover/install it from there.

**A note on rate limits.** The hosted server is shared and stays open — no signup required for casual use — but callers with no API key share one small, low-throughput budget (1 req/s to PubMed) so no single anonymous user can starve everyone else. If you're doing more than a handful of queries, ask for a key (below) and you get your own isolated, higher budget instead.

**Getting a key:**
```
Authorization: Bearer <your key>
```
Add that header in your client's MCP config (Claude Code: `claude mcp add --transport http biolab <url> --header "Authorization: Bearer <key>"`). Keys are issued with `biolab keys create <label>` — see [Managing API Keys](#managing-api-keys) below if you're running your own instance; otherwise ask the maintainer for one.

Want to run your own copy instead (local dev, your own storage, self-hosting)? Keep reading.

## The Problem

A drug discovery team uses an AI agent to research gene targets. The agent queries PubMed 200 times over three days and surfaces a paper claiming gene X is upregulated in pancreatic cancer. A scientist makes a decision based on that. Six months later, during FDA submission:

- What exact query returned that paper?
- What date was it retrieved?
- Was it peer-reviewed at retrieval time, or a preprint published later?
- Did the agent summarize it accurately, or hallucinate details?

Without Biolab, nobody can answer any of those questions. The retrieval is invisible.

## What Biolab Does

Biolab is an **interception and logging layer**, not a retrieval layer. It doesn't interpret evidence, rank it, or summarize it — it records what happened, verbatim, so an agent's claim can always be traced back to an unforgeable original.

```
Your AI Agent
    ↓  MCP tool call (e.g. search_pubmed)
Biolab MCP Server
    ↓  HTTP
Source API (PubMed, Europe PMC, ClinicalTrials.gov, bioRxiv/medRxiv)
    ↓  paper
Biolab writes a hash-chained retrieval record to the audit database
    ↓  paper + retrieval_id
Back to your agent
```

The agent gets the paper it asked for. Biolab gets a permanent, queryable, tamper-evident record of exactly what happened.

## Sources Supported

| Source | MCP Tool | CLI Command | Notes |
|--------|----------|-------------|-------|
| **PubMed** | `search_pubmed` | `biolab search` | E-utilities, full XML stored |
| **Europe PMC** | `search_europepmc` | `biolab search-europepmc` | Free, indexes bioRxiv/medRxiv |
| **ClinicalTrials.gov** | `search_clinicaltrials` | `biolab search-clinicaltrials` | API v2, condition-based search |
| **bioRxiv/medRxiv** | `search_biorxiv` | `biolab search-biorxiv` | Date-range pagination (API limit) |

All sources share a **single audit database** (SQLite locally, or [Turso](https://turso.tech) — a hosted, SQLite-compatible database — in production) with one source-agnostic schema.

## Build It Yourself

You don't need to know Python or Go to get this running locally — just follow these steps in order. All commands are run in a terminal.

### Prerequisites

- **Python 3.11 or newer** — check with `python3 --version`. Get it from [python.org](https://www.python.org/downloads/) if you don't have it.
- **Git** — to download (clone) the code. Check with `git --version`.

That's genuinely it for the Python path — no database server to install, no API keys required (PubMed works anonymously, just at a lower rate limit).

### 1. Get the code

```bash
git clone https://github.com/srikarjy/biolab-mcp-server.git
cd biolab-mcp-server
```

### 2. Install it

```bash
python3 -m venv .venv          # creates an isolated Python environment
source .venv/bin/activate      # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"        # installs the package + test tools
```

### 3. Try it

```bash
biolab demo --query "BRCA1 pancreatic cancer"
```

This searches PubMed for real, stores every result in a local `biolab.db` file (created automatically, no setup needed), and prints back the `retrieval_id` for each paper — the same ID an AI agent would get back over MCP.

### 4. Run the test suite (optional, confirms everything works)

```bash
pytest tests/ -v
```

Most tests hit the real PubMed/Europe PMC/ClinicalTrials.gov APIs on purpose (no mocking) — that's a deliberate project rule, not a bug, so a slow test run is normal.

### 5. Run it as an MCP server (what an AI agent actually connects to)

```bash
python -m biolab.server
```

This starts an HTTP server on `http://localhost:8000/mcp` — point Claude Desktop, Claude Code, or Cursor at that URL exactly like in [Use It Now](#use-it-now--no-install), just with `localhost:8000` instead of the hosted URL.

### 6. Build the Docker image (optional)

If you'd rather not install Python locally at all:

```bash
docker build -f space/Dockerfile -t biolab-mcp .
docker run -p 8000:8000 biolab-mcp
```

(Storage defaults to an ephemeral file inside the container unless you set `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` — see [Environment Variables](#environment-variables) below.)

### Prefer a pre-built release?

```bash
pipx install biolab-mcp      # or: pip install biolab-mcp
```

```bash
# Or the Go binary, no Python required at all:
curl -L https://github.com/srikarjy/biolab-mcp-server/releases/latest/download/biolab_darwin_arm64.tar.gz | tar xz
./biolab search "BRCA1 pancreatic cancer" --max 3
```

## Usage

### CLI (Scientist-Friendly)
```bash
# Search PubMed
biolab search "BRCA1 pancreatic cancer" --max 5

# Search Europe PMC
biolab search-europepmc "BRCA1 pancreatic cancer" --max 5

# Search ClinicalTrials.gov
biolab search-clinicaltrials "pancreatic cancer" --max 5

# List bioRxiv preprints (no free-text search - API limitation)
biolab search-biorxiv neuroscience --max 10
biolab search-biorxiv all --server medrxiv --max 10

# Retrieve full audit record
biolab get <retrieval_id>

# List recent retrievals
biolab list --source pubmed --limit 10

# Export for analysis
biolab export evidence.jsonl --source clinicaltrials

# Run demo
biolab demo --query "BRCA1 pancreatic cancer"
```

### MCP Tools (Agent-Friendly)
```json
// Search any source
{"name": "search_pubmed", "arguments": {"query": "BRCA1 pancreatic cancer", "agent_id": "aletheia:advocate", "max_results": 5}}
{"name": "search_europepmc", "arguments": {"query": "BRCA1 pancreatic cancer", "agent_id": "aletheia:advocate", "max_results": 5}}
{"name": "search_clinicaltrials", "arguments": {"query": "pancreatic cancer", "agent_id": "aletheia:advocate", "max_results": 5}}
{"name": "search_biorxiv", "arguments": {"category": "neuroscience", "agent_id": "aletheia:advocate", "max_results": 5, "server": "biorxiv"}}

// Retrieve full audit record (works for ALL sources)
{"name": "get_retrieval", "arguments": {"retrieval_id": "uuid-from-search"}}
```

### Python API
```python
from biolab.pubmed_client import search_and_fetch
from biolab.retrieval_log import write_retrieval, get_retrieval
from biolab.db import connect

conn = connect("biolab.db")
papers = search_and_fetch("BRCA1 pancreatic cancer", 3)
for p in papers:
    record = write_retrieval(conn, query="...", pmid=p.pmid, ...)
    print(record.retrieval_id)
```

## Managing API Keys

The server stays open to unauthenticated callers by design — but they all share one small, low-throughput rate-limit budget (see [Use It Now](#use-it-now--no-install)). Issuing someone a key gives them their own isolated, higher budget instead. This doesn't gate *access* — it's purely a fairness mechanism so one caller can't starve everyone else's share of PubMed's real rate limit.

```bash
# Issue a key — the raw key is shown once, save it immediately
biolab keys create alice

# List issued keys (never shows the raw key — only a hash is stored)
biolab keys list

# Revoke all of a label's active keys
biolab keys revoke alice
```

The caller sends the key back as `Authorization: Bearer <key>`. A missing header still works (anonymous tier); a header with an invalid or revoked key is rejected with `401`, not silently downgraded — a typo'd key should fail loudly, not quietly run at a lower tier.

## Environment Variables

All optional — the server runs with sensible defaults if you set none of these.

| Variable | Purpose | Default |
|----------|---------|---------|
| `BIOLAB_DB_PATH` | Local SQLite file path (ignored if `TURSO_DATABASE_URL` is set) | `biolab.db` |
| `TURSO_DATABASE_URL` | Remote [Turso](https://turso.tech) database URL — use this for real persistence in production | unset (uses local file) |
| `TURSO_AUTH_TOKEN` | Auth token for the Turso database above | unset |
| `BIOLAB_HOST` | Host the MCP server binds to | `0.0.0.0` |
| `BIOLAB_PORT` | Port the MCP server listens on | `8000` |
| `NCBI_API_KEY` | Raises the PubMed rate limit from 3 req/s to 10 req/s | unset (works fine without one) |

## Audit Trail Schema (v2)

```sql
CREATE TABLE retrievals (
    retrieval_id     TEXT PRIMARY KEY,  -- UUID
    source           TEXT NOT NULL,     -- "pubmed", "europepmc", "clinicaltrials", "biorxiv"
    external_id      TEXT NOT NULL,     -- PMID, NCT ID, DOI, etc.
    query_text       TEXT NOT NULL,     -- exact query sent to source
    retrieved_at     TEXT NOT NULL,     -- ISO 8601 UTC
    agent_id         TEXT NOT NULL,     -- e.g. "aletheia:advocate"
    source_metadata  TEXT NOT NULL,     -- JSON: source-specific fields
    raw_response     TEXT NOT NULL,     -- verbatim XML/JSON from source
    snapshot         TEXT NOT NULL,     -- JSON: structured fields (title, abstract, authors, journal, DOI, pub types, MeSH/conditions)
    response_hash    TEXT NOT NULL,     -- SHA-256(prev_hash + raw_response + retrieval_id + retrieved_at)
    prev_hash        TEXT NOT NULL      -- response_hash of the previous row — makes this a hash chain
);
```

**Key properties:**
- One row per paper retrieval (not per query)
- Raw response stored verbatim — parsing bugs are recoverable
- **Hash-chained**, not just hashed: each row's hash covers the previous row's hash too, so deleting or editing any row — even in the database directly — breaks the chain for every row after it. Call `retrieval_log.verify_chain(conn)` to check the whole log; it returns exactly which row broke, if any.
- Background write queue serializes all writes through one path, so the chain stays consistent even under concurrent agent calls

## Architecture

```
biolab/
├── cli.py                  # Typer CLI (search, get, list, export, demo)
├── server.py                # FastMCP server, streamable-http transport
├── db.py                    # Connection + schema (local SQLite or remote Turso)
├── models.py                 # RetrievalRecord dataclass
├── retrieval_log.py          # Only writer + background queue + hash chain
├── pubmed_client.py           # PubMed E-utilities wrapper + rate limiter
├── europepmc_client.py        # Europe PMC adapter
├── clinicaltrials_client.py   # ClinicalTrials.gov adapter
├── biorxiv_client.py          # bioRxiv/medRxiv adapter
└── migrations/                # Schema migration scripts

space/                      # Files pushed to the hosted Hugging Face Space
├── Dockerfile                # Python-server-specific image (see repo-root Dockerfile for the Go one)
└── README.md                  # Space config (title, hosting metadata)
```

**Design principles:**
- Python + Go implementations (same interface, different runtimes)
- MCP tools, not REST API — zero integration overhead for agents
- Database, not log files — structured queries across time
- Hard-fail, never degrade — paper without `retrieval_id` is worse than error
- Live-API tests, no mocks — real XML/JSON shape catches real bugs
- Single-writer queue, not row-level locking — simplest thing that keeps the hash chain consistent under concurrency

## Development

```bash
# Python
pip install -e ".[dev]"
pytest tests/ -v

# Go
cd go-biolab
go test ./...
go build -o biolab ./cmd/cli
go build -o biolab-server ./cmd/server
```

## Deployment

| Target | Method |
|--------|--------|
| **Hosted (no install)** | https://srikarjy025-biolab-mcp.hf.space/mcp — Hugging Face Space, Docker SDK, backed by Turso |
| **Local** | `pipx install biolab-mcp` or download binary |
| **CI/CD** | GitHub Actions → PyPI (Trusted Publishing/OIDC) + GHCR + GitHub Releases |
| **Containers** | `docker pull ghcr.io/srikarjy/biolab-mcp:latest`, or build `space/Dockerfile` yourself |
| **Linux packages** | `.deb`, `.rpm`, `.apk` via goreleaser |
| **Discovery** | [MCP Registry](https://registry.modelcontextprotocol.io) · [Smithery](https://smithery.ai/servers/srikarjy025/biolab-mcp) |

**Running cost: $0/month.** The Space runs on Hugging Face's free `cpu-basic` tier (this workload waits on network calls, not compute, so it never needed more). Turso's free tier is currently at 0% of its storage/read/write quotas, and has overages *disabled* — if usage ever did hit a limit, requests get rejected, not silently billed. There's no realistic query volume (short of literally millions/month) that would introduce a cost.

## Roadmap

- [ ] Evidence drift detection (retraction monitoring via response hashes)
- [ ] Provenance graph (cross-source linking by DOI)
- [ ] Nextflow/Snakemake plugins
- [ ] Rate limiting + caching (audit-safe)
- [ ] Auth + multi-tenant support

## License

MIT — see [LICENSE](LICENSE)

## Author

**Srikar Jy** — [srikarjy025@gmail.com](mailto:srikarjy025@gmail.com)
