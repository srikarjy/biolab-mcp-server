# Biolab MCP Server

> *"AI agents querying biological databases leave no audit trail. Six months later, nobody can answer: what exact query returned this result, when, and was that paper peer-reviewed at the time? Biolab solves that."*

A Python MCP server that sits between AI agents and biological databases. Every query is intercepted, logged with full retrieval context, and returns a `retrieval_id` that calling systems can store alongside their own reasoning traces — creating an end-to-end auditable chain from conclusion back to raw source.

---

## Status (as of 2026-07-13)

**v1 shipped and verified for real, not estimated.** The `search_pubmed` MCP tool is
live, tested against real PubMed data (11 passing tests, no fixtures/mocks — the
suite hits the real API on every run), security-reviewed, and running.

The full cross-project chain has also been proven for real: [Aletheia](https://github.com/srikarjy/Aletheia)
called `search_pubmed` over a live MCP connection, got back a real `retrieval_id`,
and stored it alongside `source_paper_id` in its own `provenance` table — the exact
link this project exists to create. One caveat, stated precisely rather than
rounded up: that call came from a retrieval script (Aletheia's Phase 1), not yet
from an actual reasoning agent — Aletheia's advocate agent (Phase 2) doesn't exist
yet. The mechanical chain is real; the "agent" half of the pitch below is still
ahead.

---

## The Problem

A drug discovery team uses an AI agent to research gene targets. The agent queries PubMed 200 times over three days and surfaces a paper claiming gene X is upregulated in pancreatic cancer. A scientist makes a decision based on that. Six months later, during FDA submission:

- What exact query returned that paper?
- What date was it retrieved?
- Was it peer-reviewed at retrieval time, or a preprint that was published later?
- Did the agent summarize it accurately, or did it hallucinate details?

Without Biolab, nobody can answer any of those questions. The retrieval is invisible.

---

## What Biolab Does

Biolab is an **interception and logging layer**, not a retrieval layer.

When an agent calls the PubMed tool:

```
Aletheia Advocate Agent
    ↓  MCP tool call
Biolab MCP Server
    ↓  HTTP
PubMed API
    ↓  paper
Biolab writes retrieval record to database
    ↓  paper + retrieval_id
Back to Advocate Agent
```

The agent gets the paper it asked for. Biolab gets a permanent, queryable record of exactly what happened.

---

## How It Fits Into Aletheia

Biolab is a dependency of [Aletheia](../Aletheia/README.md), a multi-agent scientific reasoning system. Aletheia's advocate agent retrieves evidence through Biolab. Aletheia stores `retrieval_id` alongside `source_paper_id` in its own provenance table.

This creates the link:

```
Aletheia provenance table
    claim | agent | source_paper_id | retrieval_id | action | timestamp
                                          ↓
                              Biolab retrieval record
                              (full query context, abstract at retrieval time, evidence level)
```

Without `retrieval_id`, you know which paper was used but not what it said when it was retrieved. With it, the chain is complete.

---

## Why Every Decision Exists

### Python, not Go
The official MCP SDK is Python. Aletheia is Python. The biotech ecosystem is Python. A Go service introduces a language boundary at the most critical integration point with no performance justification — Aletheia makes sequential agent calls, not 10,000 concurrent ones. Python eliminates the boundary entirely.

### MCP tool, not REST API
Aletheia's agents call tools, not endpoints. Wrapping Biolab as an MCP tool means zero integration overhead on the Aletheia side — the agent calls it exactly like any other tool in its environment.

### Database, not log files
An audit trail needs to be queryable. "Show me everything retrieved for BRCA1 between June and August" is a SQL query, not a grep. Log files cannot answer structured questions across time. A database can.

### No LangChain, no LangGraph
Same reason as Aletheia: these frameworks hide the exact artifact at each step inside abstractions you don't control. Provenance tracing is the core product. Every step must produce an inspectable record. That requires code you own.

---

## Retrieval Log Schema

> **Shipped**, resolved against real PubMed `esearch`/`efetch` responses, not
> guessed — see the commit history for the reasoning.

```
retrieval_id    → UUID, primary key (one row per paper, not per query)
query_text      → the exact search string sent to PubMed
pmid            → PubMed paper ID returned
retrieved_at    → UTC timestamp of retrieval
agent_id        → which agent made the call (e.g. "aletheia:advocate")
medline_status  → verbatim MedlineCitation/@Status (e.g. "MEDLINE", "Publisher")
pub_status      → verbatim PubmedData/PublicationStatus — this is the field that
                   answers "was it a preprint at retrieval time" (e.g. "aheadofprint")
raw_response    → full PubMed response snapshot, verbatim, uninterpreted
```

No `evidence_level` column — real PubMed records carry multiple simultaneous
`PublicationType` tags (a single RCT record had 5), so a scalar column would be
lossy, and evidence ranking is explicitly Aletheia's job, not Biolab's (see
Commandments below). `abstract_snapshot` isn't a separate column either — it's
parsed from `raw_response` at read time instead of duplicated, so there's one
source of truth instead of two copies that could drift.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Official MCP SDK, zero boundary with Aletheia, biotech reads Python |
| Protocol | MCP | Aletheia agents call tools, not endpoints |
| External API | PubMed E-utilities | Real, citable, stable biological literature source |
| Storage | SQLite | Migrate to Postgres only if a real query pattern (e.g. concurrent writers) proves SQLite insufficient — not yet the case |

---

## 90-Day Deliverable

One live MCP tool: `search_pubmed`. Takes a query string, retrieves papers from PubMed, writes a retrieval record to the database, returns papers plus `retrieval_id` to the calling agent.

A demo showing Aletheia's advocate agent calling `search_pubmed`, receiving a sourced result, and storing the `retrieval_id` in Aletheia's provenance table — making the full chain from conclusion to raw source queryable.

---

## Commandments

1. Don't add infrastructure until a real query fails without it.
2. Every retrieval produces a permanent, queryable record.
3. The `retrieval_id` is not optional — it is the link that makes Aletheia's traces auditable.
4. Never log the agent's summary instead of the raw source. One is interpretation. One is ground truth.
