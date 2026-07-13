# Biolab MCP Server — Design Q&A (Interview Reference)

Living log of every substantive design question raised while building this project —
questions you asked, and questions asked back to you. Kept so you can defend every
decision in an interview, not just describe what the system does. Traces
**Problem → Requirement → Design** for each entry. Append to this file as the project
grows; don't let a decision exist that isn't traceable back here.

---

## A. Resolved — decisions you can already defend

These were made and written into `README.md` at project init. Reframed here as the
questions an interviewer would actually ask.

### Q: Why Python, not Go or Node, for the MCP server?
**A:** The official MCP SDK is Python. Aletheia (the consumer) is Python. The biotech
ecosystem is Python. A Go service would introduce a language boundary at the single
most critical integration point, with no performance justification — Aletheia makes
sequential agent calls, not thousands of concurrent ones. Python eliminates the
boundary entirely.
**Watch for the follow-up:** *"What would make you reconsider?"* — a real, measured
concurrency bottleneck. Not a preference. (Same rule the FlowCast rules doc encodes
as "no new architecture without a working failure first.")

### Q: Why an MCP tool interface instead of a REST API?
**A:** The consumer (Aletheia's agents) calls tools, not endpoints. Wrapping Biolab as
an MCP tool means zero integration overhead on the calling side — the agent invokes it
exactly like any other tool in its environment. A REST API would add a translation
layer that doesn't serve any real client.

### Q: Why a database instead of log files for the audit trail?
**A:** An audit trail has to be queryable. "Show me everything retrieved for BRCA1
between June and August" is a SQL query, not a grep. Log files can't answer structured
questions across time; a database can.
**Watch for the follow-up:** *"Why not both — logs for cheap durability, DB for query?"*
— worth having an answer ready; not yet asked or resolved.

### Q: Why no LangChain / LangGraph?
**A:** Same reasoning as Aletheia. These frameworks hide the exact artifact produced at
each step behind abstractions you don't control. Provenance tracing — proving exactly
what was retrieved and when — is the core product, not an add-on. Every step has to
produce a record you can inspect, which requires owning the code that produces it.

---

### Bug found on a real end-to-end run: XML title truncation
**Found:** 2026-07-13, first real call through the actual MCP server (not a bypass
script) — `search_pubmed("BRCA1 pancreatic cancer")`, PMID `42431391`.
**What happened:** the real title is `"TRDMT1-Mediated mRNA m⁵C Methylation
Decreases..."` — PubMed encodes the "5" as `<sup>5</sup>` inside `<ArticleTitle>`.
`ElementTree.findtext()` / `.text` only return text up to the first child element, so
the parsed title silently truncated to `"TRDMT1-Mediated mRNA m"` — everything after
the `<sup>` tag was dropped, no exception, no warning.
**Fix:** `pubmed_client._full_text()` now walks `element.itertext()` to concatenate
all text nodes including inside inline markup, applied to both `ArticleTitle` and
`AbstractText`. Re-run confirmed the full title comes through correctly.
**Why it's logged here and not just in the commit:** this is a real bug caught by
running against real data, not a hypothetical — exactly the class of thing the
project's own discipline (README/CLAUDE.md rule: nothing claimed unless it's
actually running on real data) exists to catch. If asked in an interview "how did you
validate the parser," this is a concrete, truthful answer.

---

### Security review before making the repo public (2026-07-13)
Manual review (the `/security-review` skill's own git-diff step assumes an `origin`
remote, which didn't exist yet — reviewed the full diff since init by hand instead).
No secrets, no SQL injection (parameterized queries throughout), no eval/exec/subprocess.
Two real findings, both fixed:
1. **XML entity-expansion DoS**: `pubmed_client.py` parsed network-fetched XML with
   stdlib `ElementTree.fromstring`, vulnerable to "billion laughs" attacks. Likelihood
   was low (fixed HTTPS endpoint, not attacker-controlled), but fixed anyway —
   `defusedxml.ElementTree.fromstring` now does the parsing; stdlib `ET.tostring` is
   still used for serialization only, which doesn't process untrusted input.
2. **Unbounded `max_results`**: no upper limit meant a caller could force arbitrarily
   large memory use and DB writes per call. Added `MAX_RESULTS_CAP = 50` in
   `server.py` (matches PubMed's own esearch API default), tool now raises `ValueError`
   outside `[1, 50]`.
Both fixes re-verified against a real MCP client/server run before pushing anywhere.

---

## B. Open — decisions you have NOT made yet (don't claim these in an interview)

These are real gaps. Saying "TBD" honestly beats guessing — that's the standing
collaboration rule for this project.

### Q: What columns does the retrieval log need to survive an FDA-style audit?
**Status:** RESOLVED 2026-07-10, against real data — see below.
**Context:** Current starter schema only has `retrieval_id, query_text, pmid,
retrieved_at, agent_id`. The README's own pitch ("was it peer-reviewed at the time?")
is not yet answerable by this schema. Candidate additions on the table:
`publication_status_at_retrieval`, `abstract_snapshot`, `evidence_level`. None chosen.
**Why it matters for interviews:** this is the load-bearing claim of the whole project.
If asked "walk me through the schema," the honest current answer is "the base
retrieval event is captured; the audit-specific columns are still being designed" —
say that, don't invent an answer on the spot.

**Resolution (evidence, not guesswork):** Before picking columns, pulled two real
PubMed records via `esearch`/`efetch` (no code written yet, just raw curl):
- PMID `42410220` (a survey article, ahead-of-print at the time of the call):
  `MedlineCitation/@Status="Publisher"`, `PubmedData/PublicationStatus="aheadofprint"`
- PMID `42372741` (a full RCT publication): `MedlineCitation/@Status="MEDLINE"`,
  `PubmedData/PublicationStatus="ppublish"`, and a `PublicationTypeList` carrying
  **five** simultaneous tags (`Journal Article`, `Randomized Controlled Trial`,
  `Clinical Trial, Phase III`, `Multicenter Study`, `Comparative Study`)

Two things this proved that the abstract candidate-column table above got wrong:
1. "Publication status" isn't one field in PubMed's response — it's two
   (`MedlineCitation/@Status` = indexing state, `PublicationStatus` = print/electronic
   release state). Collapsing them into a single `publication_status_at_retrieval`
   column would silently throw one away.
2. `evidence_level` was never going to work as a single scalar column — real records
   carry multiple `PublicationType` tags at once. A single column forces picking one
   and discarding the rest.

**Decision:**
- `medline_status TEXT` — verbatim `MedlineCitation/@Status`
- `pub_status TEXT` — verbatim `PubmedData/PublicationStatus` (this is the field that
  answers "was it a preprint at retrieval time": `pub_status = 'aheadofprint'`)
- `raw_response TEXT` — the full PubMed response snapshot, verbatim, uninterpreted.
  Abstract text and publication types are both derived from this at read time, not
  stored as separate columns — no query has been named yet that needs them indexed
  separately (per the blueprint's own rule: don't add a column you can't name a query
  for). The MCP tool's `abstract` output field (BLUEPRINT.md §3) is parsed from this
  raw snapshot at request time, not duplicated into its own column — one source of
  truth, no drift risk between "what we told the agent" and "what we logged."
- `evidence_level` as a structured column: **rejected**, not deferred — README already
  scopes evidence-level ranking to Aletheia, not Biolab (see README "Explicitly out of
  scope"). The raw `PublicationTypeList` data is preserved (inside `raw_response`) for
  Aletheia or a future pass to parse, but Biolab doesn't get to invent a ranking
  schema for something it was told isn't its job.
- `raw_response_hash`: still explicitly out of scope for v1, per BLUEPRINT.md §4 — a
  conscious exclusion, not revisited here.

### Q: How do you actually prove a paper was peer-reviewed *at retrieval time*,
### versus later?
**Status:** OPEN, and harder than it looks.
**Context:** PubMed doesn't hand you a clean "was this a preprint on this exact date"
flag. You need to decide: snapshot the metadata PubMed returns at retrieval time
(publication status, date, journal) verbatim, and treat that snapshot — not a live
re-query later — as the source of truth. That's a design decision, not a detail.
**Why it's unresolved:** no schema field or snapshot mechanism has been designed yet.

### Q: SQLite or Postgres for v1?
**Status:** OPEN. README says "TBD (SQLite → PostgreSQL), start simple, migrate when
query patterns are known." No migration trigger has been defined yet.
**Follow-up to have ready:** *"What's the specific signal that tells you to migrate?"*
— needs an answer before this is interview-safe (e.g., "concurrent writes" or "a query
pattern SQLite can't index well" — not decided yet, don't guess one now).

### Q: What happens if PubMed later retracts or revises a paper you already logged?
**Status:** OPEN. Not addressed anywhere yet. If the abstract snapshot is the source
of truth, does a retraction get a new row, or mutate the old one? Mutating breaks the
"permanent record" commandment (#2 in README). Leaning answer: append-only, new row —
but this hasn't been decided, only reasoned about here.

---

## C. Process questions from this session (Claude → you)

### Q: The `CLAUDE.md` in this folder is actually FlowCast's Cardinal Rules doc, not
### Biolab's. Move it, delete it, or leave it?
**A (you):** Leave it, and treat its rules as governing engineering discipline across
projects, not just FlowCast literally — i.e., "no architecture before a real failure,"
"nothing claimed without real data," "no premature infrastructure" apply to Biolab too,
even though the doc's specific stack references (Go, Nextflow, MultiQC) don't.

### Q: What should this Q&A file capture?
**A (you):** Every question you ask Claude and every question Claude asks you, kept as
a running reference for future job interviews.

### Q: What should `BLUEPRINT.md` cover?
**A (you):** Not yet answered explicitly — see the top of `BLUEPRINT.md` for the
default taken (technical architecture, not a milestone roadmap) and why.
