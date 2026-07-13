# Biolab MCP Server — Technical Blueprint

**Status:** Pre-code. Zero lines of implementation exist (`git log` shows one commit:
`README.md`). This document turns README's decisions into implementation-ready detail
for the single committed v1 deliverable: one live MCP tool, `search_pubmed`.

**Scope note on why this doc exists at all:** the FlowCast rules doc (kept in this
repo as cross-project discipline) says "no new architecture without a working failure
first." This blueprint is not new architecture — it's making README's already-decided
architecture (Python, MCP tool, DB-backed audit log) concrete enough to type. Anything
below marked **DRAFT — pick one** is a real open decision, not settled by this doc.
Resolve those in `QUESTIONS_AND_ANSWERS.md` before writing the code that depends on
them.

---

## 1. The one thing v1 has to do

> Take a query string, retrieve papers from PubMed, write a retrieval record, return
> papers + `retrieval_id` to the calling agent.

Everything below decomposes that sentence. If a component doesn't serve it, it doesn't
belong in v1.

---

## 2. Request flow (expanded with failure paths)

```
Aletheia Advocate Agent
    │  MCP tool call: search_pubmed(query, agent_id)
    ▼
Biolab MCP Server
    │
    ├─ 1. Validate input (non-empty query, known agent_id)
    │       └─ fail → return MCP error, NOTHING written to DB
    │
    ├─ 2. Call PubMed E-utilities (esearch → efetch)
    │       └─ fail (network / rate limit / 0 results) → return MCP error,
    │          NOTHING written to DB — a failed retrieval is not a retrieval
    │
    ├─ 3. Snapshot the response exactly as returned (see §4, open question)
    │
    ├─ 4. Write retrieval record to DB, get retrieval_id (one write per paper,
    │      see §3 resolution below)
    │       └─ fail (DB down) → RESOLVED 2026-07-13: hard-fail, no retry.
    │          write_retrieval() lets sqlite3 exceptions propagate uncaught;
    │          the tool call fails loudly rather than returning a paper without
    │          a retrieval_id. No retry logic: retry solves a distributed-systems
    │          problem (transient network blips to a remote DB) that a local
    │          SQLite file doesn't have — a write failure here means disk-full or
    │          a permissions problem, not something a retry fixes. Revisit only
    │          if/when the Postgres migration (§6) actually happens.
    │
    └─ 5. Return { retrieval_id, papers } to the agent
```

**Why step 2 and step 4 both hard-fail instead of degrading gracefully:** a paper
returned without a `retrieval_id`, or a `retrieval_id` logged without a real paper
behind it, is worse than an error — it's a silent audit-trail gap that looks fine
until someone needs it. No fallback path is acceptable here without saying so
explicitly.

---

## 3. MCP tool interface (concrete signature)

```python
# tool: search_pubmed

# Input
{
  "query": str,        # required, the exact search string — verbatim, no normalization
  "agent_id": str,      # required, e.g. "aletheia:advocate" — who is asking
  "max_results": int,   # optional, default TBD — DRAFT, pick a number and say why
}

# Output
{
  "query_echo": str,    # the exact query_text that was logged (proves no silent mutation)
  "papers": [
    {
      "pmid": str,
      "retrieval_id": str,   # UUID — the audit-trail link for THIS paper specifically
      "title": str,
      "abstract": str,
    }
  ]
}
```

**RESOLVED 2026-07-13 — `retrieval_id` moved from top-level to per-paper.** Originally a
single top-level `retrieval_id` covered every paper in the response. That doesn't
reconcile with §4's schema, where `retrieval_id` is the primary key on a table where
`pmid` is a plain column — a PK can't be shared across N rows. Decided: one row per
paper, so one `retrieval_id` per paper. Consequence for Aletheia's integration: it
stores `retrieval_id` per `source_paper_id`, not once per query — which is actually
the more correct provenance link anyway ("what exact retrieval produced *this*
paper," not "what query batch happened to include it").

**Why `query_echo` is in the output, not just the DB row:** if Aletheia is going to
store `retrieval_id` next to `source_paper_id`, the agent needs to be able to sanity
check, in the same response, that the query it asked for is the query that got logged
— otherwise a bug in the server could silently log the wrong query and nothing at the
call site would ever catch it.

---

## 4. Retrieval log schema

**RESOLVED 2026-07-10** — against real PubMed `esearch`/`efetch` responses (PMIDs
`42410220`, `42372741`), not guessed. Full reasoning and the raw evidence in
`QUESTIONS_AND_ANSWERS.md` §A.

```
retrieval_id    UUID, primary key
query_text      TEXT — exact search string sent to PubMed
pmid            TEXT — PubMed ID returned
retrieved_at    TIMESTAMPTZ — UTC
agent_id        TEXT — which agent made the call
medline_status  TEXT — verbatim MedlineCitation/@Status (e.g. "MEDLINE", "Publisher")
pub_status      TEXT — verbatim PubmedData/PublicationStatus (e.g. "ppublish",
                  "aheadofprint") — this is the field that answers "was it a preprint
                  at retrieval time"
raw_response    TEXT — full PubMed response snapshot, verbatim, uninterpreted
```

**Why no `abstract_snapshot` or `evidence_level` columns:** both were candidates in
the original DRAFT table below. Real data showed `evidence_level` can't be a scalar —
a single RCT record carried five simultaneous `PublicationType` tags — and README
already scopes evidence-ranking to Aletheia, not Biolab, so it's not reintroduced
structured here. `abstract_snapshot` is parsed from `raw_response` at read time
instead of duplicated into its own column — no named query needs it indexed
separately yet, and one source of truth avoids drift between what the tool returns
to the agent and what's logged. `raw_response_hash` remains explicitly out of scope
for v1 (unchanged from the original table).

<details>
<summary>Original DRAFT candidate table (superseded, kept for the record)</summary>

| Candidate column | Query it would need to answer | Decided? |
|---|---|---|
| `publication_status_at_retrieval` | "Was this a preprint when the agent read it, even if it's since been published?" | Superseded — split into `medline_status` + `pub_status`, see above |
| `abstract_snapshot` | "What did the abstract actually say at retrieval time, independent of PubMed's current copy?" | Rejected as a separate column — folded into `raw_response` |
| `evidence_level` | "Can we filter/rank retrievals by study type (RCT vs review vs preprint) without re-fetching from PubMed?" | Rejected — out of scope per README, and not a scalar in real data anyway |
| `raw_response_hash` | "Can we prove, cryptographically, that the snapshot wasn't altered after the fact?" | Still out of scope for v1 |

</details>

---

## 5. Module layout (Python package)

```
biolab/
├── server.py          # MCP server entrypoint, registers search_pubmed tool
├── pubmed_client.py    # thin wrapper over PubMed E-utilities — no logging logic here
├── retrieval_log.py     # the ONLY module that writes to the DB — one writer, one place
├── models.py            # retrieval record schema (dataclass/pydantic), shared by db + tool
├── db.py                # connection/session setup — SQLite now, see §6
└── tests/
    └── test_retrieval_log.py   # exists once real retrievals exist to test against —
                                  # not before (FlowCast rule: no infra before a real run)
```

**Why `pubmed_client.py` and `retrieval_log.py` are separate files:** the interception
layer is the entire value proposition. If retrieval and logging live in the same
function, it becomes possible to accidentally return a paper without logging it — a
silent violation of commandment #2 ("every retrieval produces a permanent, queryable
record"). Separating them makes that failure mode a two-file diff to introduce, not a
one-line typo.

---

## 6. Storage: SQLite now, Postgres later

**Decided:** start on SQLite (README).
**DRAFT — not decided:** what specific, measured signal triggers the migration to
Postgres. Candidates to choose from, not yet chosen:
- Concurrent writers (multiple agents logging simultaneously) causing SQLite lock
  contention — measured, not assumed
- A query pattern SQLite can't index well (e.g., full-text search over
  `abstract_snapshot`, if that column gets added)

Whichever it is, write it down here once decided — "start simple, migrate when needed"
is not itself a plan; the trigger condition is the plan.

---

## 7. Explicitly out of scope for v1

Mirrors README's commandments — repeated here so implementation doesn't quietly grow
beyond the 90-day deliverable:

- No REST API surface — MCP only
- No caching layer — no measured latency problem yet
- No multi-agent support beyond a single `agent_id` string field — no auth/identity system
- No retry/backoff tuning beyond "fail loudly" — see §2
- No evidence-level ranking or search — that's Aletheia's job, not Biolab's

---

## 8. What "done" looks like for v1

One passing end-to-end run: a real call to `search_pubmed` with a real query, a real
row in the DB, a real `retrieval_id` returned, and Aletheia storing that ID next to a
`source_paper_id` in its own provenance table. No metric or claim about this system
goes in a commit message, README, or interview answer until that run has actually
happened once, on real data — same rule as FlowCast's rule #2, applied here.

**Status 2026-07-13 — half done.** The Biolab-side half of this is real and confirmed:
a real MCP client called `search_pubmed` over stdio (not a bypass script) against a
real query, got back real `retrieval_id`s, and the rows are verified sitting in a real
SQLite file. The error path was also run for real — an empty query correctly returns
`isError: True` and writes zero rows. **Not yet done:** the Aletheia half — no call has
been made from Aletheia's actual advocate agent, and no `retrieval_id` has been stored
in Aletheia's provenance table. Don't claim full v1 "done" until that side happens too,
in the Aletheia repo.
