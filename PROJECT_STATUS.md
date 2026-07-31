# Biolab MCP Server — Status, Roadmap, and Architecture Decisions

Last updated: 2026-07-15
Branch: `main` @ `f3e48ad` (clean)

This is a working document, not repo documentation. `README.md` is the public
artifact; this file is the internal picture — what's actually built, what's
actually left, and why each decision went the way it did.

---

## 1. What Exists Today

### Shipped

**One MCP tool: `search_pubmed`.** Takes `query`, `agent_id`, and optional
`max_results` (default 5, hard-capped at 50). Hits PubMed E-utilities, writes one
retrieval record per paper, returns each paper with its `retrieval_id`.

The module layout is four files, each with exactly one job:

| File | Responsibility | Deliberate non-responsibility |
|---|---|---|
| `biolab/pubmed_client.py` | esearch → PMIDs → efetch → parsed `PubMedPaper` | No DB access, no logging |
| `biolab/retrieval_log.py` | The only module that writes to `retrievals` | No PubMed knowledge, no error swallowing |
| `biolab/db.py` | SQLite connection + `CREATE TABLE IF NOT EXISTS` | No queries, no migrations |
| `biolab/models.py` | `RetrievalRecord` dataclass shared by storage and tool output | No behavior |
| `biolab/server.py` | FastMCP entrypoint, input validation, orchestration | No parsing, no SQL |

**The `retrievals` table** (`biolab/db.py`), resolved against real PubMed
responses rather than guessed:

```sql
retrieval_id   TEXT PRIMARY KEY   -- UUID4, one row per paper (not per query)
query_text     TEXT NOT NULL      -- exact string sent to PubMed, unnormalized
pmid           TEXT NOT NULL
retrieved_at   TEXT NOT NULL      -- ISO 8601, UTC
agent_id       TEXT NOT NULL      -- e.g. "aletheia:advocate"
medline_status TEXT NOT NULL      -- verbatim MedlineCitation/@Status
pub_status     TEXT NOT NULL      -- verbatim PubmedData/PublicationStatus
raw_response   TEXT NOT NULL      -- this paper's <PubmedArticle> element, verbatim
```

**Test suite: 11 tests across three files** (`test_pubmed_client.py` ×5,
`test_retrieval_log.py` ×3, `test_server.py` ×3). No fixtures, no mocks — every
run hits the live PubMed API.

**Security review passed.** Two findings fixed in `a2d57a6`:
- Untrusted network XML now parsed with `defusedxml`, not stdlib `ElementTree`
  (entity-expansion / "billion laughs" defense). Stdlib `ET` is retained only for
  `tostring()`, which never parses.
- `max_results` capped at 50, so a caller can't force unbounded memory use and
  unbounded DB writes in a single call.

### Proven end-to-end, with one honest caveat

Aletheia called `search_pubmed` over a live MCP connection, received a real
`retrieval_id`, and stored it next to `source_paper_id` in its own `provenance`
table. That is the exact link this project exists to create, and it is real.

The caveat, stated precisely: the call came from Aletheia's **Phase 1 retrieval
script**, not from a reasoning agent. Aletheia's advocate agent (Phase 2) does not
exist yet. The mechanical chain works; the "agent" half of the pitch is still ahead.

The local `biolab.db` corroborates this — 35 retrieval records, 5 distinct PMIDs,
spanning 2026-07-13 to 2026-07-14, from two agent IDs:

| `agent_id` | rows |
|---|---|
| `aletheia:advocate` | 20 |
| `aletheia:phase1-retrieval` | 15 |

(`*.db` is gitignored, so this is local evidence only — see §4, Open Issue 3.)

### One real bug found and fixed along the way

`_full_text()` in `pubmed_client.py` exists because `.text` and `.findtext()` only
return text up to the first child element. A real PubMed title containing
`m<sup>5</sup>C` was silently truncated at the `<sup>` tag. The fix uses
`itertext()` to concatenate everything. This is worth remembering — it's the kind
of failure that produces a corrupted audit trail while every test still passes.

---

## 2. Architecture Decisions

Each of these is a decision with a live alternative, not a default that got picked
because it was first to hand.

### AD-1 — Python, not Go

The official MCP SDK is Python, Aletheia is Python, and biotech reads Python. Go
would introduce a language boundary at the single most critical integration point.
The usual justification for that boundary is throughput, and it doesn't apply:
Aletheia makes sequential agent calls, not ten thousand concurrent ones.

**Reversal trigger:** a real concurrency requirement that Python can't serve. Not
in sight.

### AD-2 — MCP tool, not REST API

Aletheia's agents call tools, not endpoints. Exposing Biolab as an MCP tool means
zero integration code on the Aletheia side — the agent calls it exactly the way it
calls anything else in its environment. A REST API would require Aletheia to grow
a client, an auth story, and error-mapping for a service that has exactly one
consumer.

### AD-3 — Database, not log files

An audit trail has to answer structured questions across time. "Show me everything
retrieved for BRCA1 between June and August" is a SQL query. Log files can't
answer it; grep is not an audit interface.

### AD-4 — SQLite, not Postgres (yet)

SQLite is one file, zero operational surface, and correct for the current write
pattern: one writer, sequential calls, ~35 rows.

**Reversal trigger, stated in advance so it isn't rationalized later:** concurrent
writers. When more than one agent process writes to the log simultaneously,
SQLite's write lock becomes a real constraint and Postgres earns its cost. Not
before. The schema is deliberately plain SQL with no SQLite-specific types, so the
migration is a dump-and-load, not a rewrite.

### AD-5 — No `evidence_level` column

The original schema sketch had one. Real PubMed records killed it: a single RCT
record carried **five** simultaneous `PublicationType` tags. A scalar column would
have to pick one and discard four, which is lossy in exactly the way an audit trail
must never be. Evidence ranking is also explicitly Aletheia's job — Biolab records
what happened, it doesn't interpret it.

### AD-6 — No `abstract_snapshot` column

The abstract is parsed out of `raw_response` at read time rather than stored twice.
Two copies of the same fact are two things that can drift, and in a provenance
system a drifted copy is worse than no copy. One source of truth: the verbatim XML.

### AD-7 — Store raw XML verbatim, uninterpreted

`raw_response` holds the paper's own `<PubmedArticle>` element exactly as PubMed
sent it. Any parsing bug we ship today is recoverable tomorrow, because the ground
truth is still on disk. This is the same principle as AD-6, one layer down: never
let the interpretation become the record.

### AD-8 — Hard-fail, never degrade

Both the PubMed call and the DB write fail loudly. `retrieval_log.write_retrieval`
deliberately does **not** catch DB errors — they propagate uncaught and kill the
tool call. There is no retry logic.

The reasoning: a paper returned to an agent *without* a `retrieval_id` is worse
than an error, because the agent will happily use it and the audit chain now has a
silent hole that nobody discovers until an FDA submission. An exception is visible.
A missing row is not.

### AD-9 — One writer, one place

`retrieval_log.py` is the only module that writes to `retrievals`. `pubmed_client`
has no DB access; `db.py` has no queries. If the audit trail is ever wrong, there
is exactly one file to read.

### AD-10 — One row per paper, not per query

`retrieval_id` is the primary key and it identifies a *paper retrieval*, not a
search. This is what lets Aletheia store one `retrieval_id` alongside one
`source_paper_id` in its provenance table. A per-query ID would force a join and a
disambiguation step at exactly the moment you least want ambiguity.

### AD-11 — Query text stored unnormalized

`query_text` is the exact string sent to PubMed. Normalizing it would mean the log
records what we *meant* to ask rather than what we *actually* asked. Reproducing a
six-month-old retrieval requires the latter.

### AD-12 — No LangChain, no LangGraph

Same reasoning as Aletheia. These frameworks hide the exact artifact at each step
inside abstractions you don't own. Provenance tracing *is* the product here — every
step has to produce an inspectable record, which requires code you control.

### AD-13 — Live-API tests, no mocks

The suite hits real PubMed on every run. The cost is honest: the tests are slow and
they fail when NCBI has a bad day. The benefit is that they test the thing that
actually breaks — PubMed's real XML shape. A mock would have happily returned a
clean `<ArticleTitle>` and never caught the `<sup>` truncation bug in §1.

**Reversal trigger:** if NCBI flakiness starts producing false failures often
enough to erode trust in the suite, add a recorded-cassette layer *alongside* the
live tests — not replacing them.

---

## 3. Future Tasks

Ordered by what unblocks the most. Nothing here is scheduled; this is a queue, not
a plan.

### Tier 1 — Completes the pitch

- [ ] **Aletheia advocate agent calls `search_pubmed` (Phase 2).** This is the one
      item that closes the gap named in §1. Until a reasoning agent — not a script —
      drives the retrieval, the README's central claim is half-proven. Blocked on
      Aletheia, not on Biolab.
- [ ] **Ship the query interface.** The entire justification for AD-3 (database,
      not log files) is that the trail is queryable — and right now nothing exposes
      a query. `sqlite3` on the CLI is not a deliverable. Minimum viable: a
      `get_retrieval(retrieval_id)` MCP tool that returns the full record including
      the abstract parsed from `raw_response`. This is the thinnest thing that makes
      AD-3 true in practice rather than in principle.
- [ ] **Write the demo.** "Conclusion → `retrieval_id` → raw source, queryable" as
      a runnable script. This is the 90-day deliverable and the interview artifact.

### Tier 2 — Correctness and durability

- [ ] **Fix the dangling doc references.** `server.py`, `db.py`, `retrieval_log.py`,
      and `pubmed_client.py` all cite `BLUEPRINT.md` and `QUESTIONS_AND_ANSWERS.md`
      in their docstrings. Commit `92f35ea` deleted both files. Every one of those
      pointers is now dead — a reader following them finds nothing. Either inline
      the reasoning at the call site or drop the references. (See §4, Open Issue 1.)
- [ ] **Decide the duplicate-retrieval semantics.** The same PMID retrieved twice
      writes two rows with two `retrieval_id`s. That is almost certainly correct —
      two retrievals *are* two events, and the second may return different content —
      but it's currently emergent rather than decided. Write it down as an AD, and
      add a test that asserts it.
- [ ] **Index `pmid`, `agent_id`, `retrieved_at`.** The README's motivating query
      ("everything for BRCA1 between June and August") is a full table scan today.
      Cheap now, annoying at a million rows.
- [ ] **Connection lifecycle.** `server.py` opens `_conn` at import time and never
      closes it. Fine for a single-process stdio server; a landmine the moment
      anything else imports the module. Worth a look before it becomes a debugging
      session.

### Tier 3 — Reach

- [ ] **A second data source.** ClinicalTrials.gov or bioRxiv. This is the decision
      that tests whether the schema generalizes or whether `medline_status` /
      `pub_status` quietly hardcoded PubMed's model into the audit trail. Worth
      doing partly *because* it might reveal that.
- [ ] **Rate limiting / NCBI API key.** PubMed allows 3 req/s unauthenticated, 10
      with a key. Not a problem at current volume. Per Commandment 1, don't build it
      until a real query fails without it.
- [ ] **Postgres migration.** Held behind the AD-4 trigger. Do not do this early.

### Explicitly not doing

- Caching PubMed responses. A cache means a retrieval record that describes a
  request that never happened, which is a lie in an audit trail.
- Storing agent summaries. Commandment 4. One is interpretation, one is ground
  truth.
- Any auth layer, until there is a second consumer to authenticate.

---

## 4. Open Issues

1. **Dead doc pointers in four source files.** `BLUEPRINT.md` and
   `QUESTIONS_AND_ANSWERS.md` are gone (`92f35ea`) but still cited in docstrings.
   The reasoning they held is real and mostly reconstructed in §2 above — but a
   reader of `retrieval_log.py` has no way to reach it. This is the highest-value
   cheap fix in the queue.

2. **This file's own status is undecided.** Commit `92f35ea` removed planning docs
   from the repo on purpose. This document is a planning doc. It is currently
   untracked and uncommitted by design — the choice is yours: gitignore it, keep it
   untracked, or reverse `92f35ea`'s policy deliberately rather than by accident.

3. **`biolab.db` is gitignored (`*.db`) and 1.8 MB of real evidence lives only on
   this machine.** The 35 records proving the Aletheia integration are not backed
   up anywhere. Keeping them out of git is right; having no copy is not.

---

## 5. Commandments

1. Don't add infrastructure until a real query fails without it.
2. Every retrieval produces a permanent, queryable record.
3. The `retrieval_id` is not optional — it is the link that makes Aletheia's traces
   auditable.
4. Never log the agent's summary instead of the raw source. One is interpretation.
   One is ground truth.
