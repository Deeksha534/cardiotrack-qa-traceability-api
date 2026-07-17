# Project Design and Implementation

## 1. Data model

Two stores, split by shape and lifecycle.

**SQLite (SQLAlchemy)** — the structured, relational, versioned side:

- `documents(id, name)` — a logical manual (e.g. `ct200`).
- `versions(id, document_id, number, source_hash, created_at)` — one row per
  ingest. Re-ingesting the same `name` appends `number = max+1`; nothing is
  mutated or deleted.
- `nodes(id, version_id, parent_id, logical_id, heading, level, body,
  content_hash, path, order_index)` — one heading section, **scoped to a single
  version**. `parent_id` gives the tree. `content_hash = sha256(heading + normalized body)`
  is the staleness primitive. `logical_id` is the *cross-version* identity
  (see §3).
- `selections(id, name, created_at)` and `selection_items(id, selection_id, node_id)`.
  A selection pins **node rows**. Because every node row belongs to exactly one
  version, referencing a `node_id` is inherently version-pinned — old selections
  keep resolving to the exact text they were created against even after v2 lands.

**JSON document store** (`app/doc_store.py`) — the LLM-output / NoSQL side. Each
generation record holds the test cases plus a **snapshot** of the exact source
content it was generated from: `[{logical_id, heading, body, content_hash,
version_number, document_id, document_name}]`. The snapshot is deliberately
self-contained so staleness can be computed later without depending on the
original rows still existing.

Why a JSON store instead of MongoDB: the access pattern is append-only
documents read by id / selection_id / node logical_id — document-shaped but with
no need for a server process. A JSON file keeps the submission runnable with
zero infra. The module exposes a narrow `create/get/find_*` interface, so
swapping in `pymongo` is a one-file change. The assignment explicitly allows a
"well-justified JSON store."

## 2. Tree-parsing decisions (and each irregularity)

The parser (`app/parser.py`) is line-based with an explicit ancestor **stack**.
It is not a generic markdown parser — it targets this file. What I found in the
document that a first naive attempt (regex `^#+` per line, parent = previous
heading) got wrong, and how each is handled:

| Irregularity in the file | Naive failure | How I found it | Handling |
|---|---|---|---|
| **Duplicate sibling headings** — `## 2.1 Cuff Pressure Limits` appears twice under `2. Safety` | Second overwrites/merges into first, or path collides | Wrote a unit test asserting two distinct node IDs; it failed | `logical_id` disambiguates duplicates with a `#2` suffix; both keep the same parent. Distinct nodes, distinct hashes. |
| **Skipped heading level** — `### 3.1.1` directly under `# 3. Operation` (no H2) | H3 mis-parented (attached to previous heading regardless of level, or treated as top-level) | Manual inspection of the tree output; H3 showed up as a sibling of H1 | Parent = nearest ancestor on the stack with **strictly smaller level**, popping deeper/equal levels first. |
| **`#` inside a fenced code block** — the E3 pseudocode has `# error selection routine` | Comment lines become phantom headings, body split apart | Search returned a bogus "error selection routine" node | Track fence open/close (```` ``` ````/`~~~`); suppress heading detection inside fences. |
| **Preamble before first heading** — title/revision lines before `# 1. Overview` | Silently dropped (no open node to attach to) | Byte count of reassembled text < input | Captured as a synthetic `(document preamble)` node so nothing is lost. |
| **Heading whitespace / closing hashes** — `#   1. Overview   ###` | Heading text includes stray spaces/hashes; hashes drift across versions | Content hash differed on cosmetically-identical headings | Regex strips leading/trailing space and trailing `#`; body normalized per line before hashing. |

Design stance from the brief: **a clean-looking but wrong tree is worse than a
visibly failing one.** So the parser never silently attaches content to "the
last heading it saw" — parenting is always by level, and un-attributable text
(preamble) becomes its own visible node rather than vanishing.

## 3. Version-matching strategy

**Path-based matching.** A node's `logical_id` is the normalized heading path
from the root (e.g. `/2. safety/2.1 cuff pressure limits`), with a `#n` suffix
to disambiguate duplicate siblings. On re-ingest, a v2 node is "the same logical
node" as a v1 node iff their `logical_id` matches. Then `content_hash` decides
changed-vs-unchanged.

Why path over the alternatives: hashing the body can't be identity (a changed
body must stay the *same* node, flagged — that's the whole point). Fuzzy title
matching is non-deterministic and hard to defend in a regulated context. Path is
deterministic, explainable, and stable under body edits and sibling reordering.

**Where it breaks (known failure modes):**

- **Renaming a heading** looks like *delete old + add new*. The old logical node
  reports `removed`, a brand-new one appears. Any generation pinned to the old
  section is correctly flagged (as `removed`), so we fail safe — but we lose the
  link that it's "the same section, renamed."
- **Renumbering** (`2.1` → `2.2` across a global renumber) is a rename by this
  definition and breaks the same way.
- **Moving a section** to a different parent changes its path → treated as
  remove+add.
- **Duplicate-sibling reordering**: if the two `2.1` blocks swap order between
  versions, the `#2` suffix is assigned by document order, so the matcher would
  pair v1-first with v2-first even though their bodies swapped. Positional, not
  content-aware.

These are documented rather than fixed on purpose; a content-similarity second
pass would mitigate renames but adds the non-determinism I wanted to avoid for a
first version.

## 4. Staleness / impact detection

A generation stored the `content_hash` of every source section. At **retrieval**
(`GET /generations/{id}`, and the selection/node retrieval routes), for each
snapshot section we look up the *current latest version* of its document, find
the node with the same `logical_id`, and compare hashes:

- hash equal → `current`
- section gone → `removed`
- hash differs → `stale`, plus a severity from `classify_staleness`:
  - **`material`** if any numeric token changed (e.g. `300 → 320 mmHg`) — the
    dangerous case for a medical device.
  - **`cosmetic`** if text similarity ≥ 0.95 and no numbers moved.
  - When uncertain we round **up** to `material` — better a false warning than
    false reassurance.

**Honest limits.** This is a heuristic over raw text. A one-word wording change
and a changed pressure threshold *both* flip the content hash; the numeric-token
check is what lets us escalate the threshold case, but it's shallow — it can't
tell that "deflate within 2 seconds" → "within 5 seconds" is material if we only
watched for *new* numbers vs. *changed* ones (we compare the set, so a changed
number is caught, but a material change with no number — "must" → "should" —
would be classified `cosmetic`). We surface severity as advisory metadata, never
as an auto-accept/auto-reject.

## 5. LLM prompt design + structured-output / retry strategy

- **Prompt** (`app/llm.py`): system prompt fixes the role (QA engineer, medical
  device), constrains output to test cases derived *only* from the provided
  sections, and specifies an exact JSON schema. Each section is passed with its
  `logical_id` so the model can attribute test cases back to sources.
- **Schema**: Pydantic `TestCaseSet` — 3–5 `TestCase`s, each with a non-empty
  title, ≥1 step, and an expected result.
- **We never trust the model.** Every response goes through `_extract_json`
  (handles prose wrapping and ```` ```json ```` fences) then Pydantic
  validation. On failure we **retry up to 3×**, feeding the validation error
  back into the prompt as a repair instruction.
- **On total failure** the generation is stored with `status="failed"` plus the
  raw attempts, and the API returns `502` with that record attached — the
  failure is auditable, not swallowed. "It usually works" is explicitly not the
  design.

**Duplicate-submission policy.** Submitting the same selection twice returns the
**cached** generation (idempotent) rather than generating again, keyed on
`selection_id + signature(pinned content hashes)`. Rationale: the inputs are
version-pinned and immutable, so a repeat is asking the same question about the
same text — regenerating would cost money and risk silent divergence between two
"identical" results. `?force=true` overrides to create a fresh generation on
purpose. If the underlying document is re-versioned, the *pinned* selection is
unchanged so it still dedupes; a new selection against v2 has a different
signature and generates fresh.

## 6. Future Improvements

- Content-similarity second pass in the matcher to recover renames/renumbers
  without losing determinism (e.g. only fuzzy-match among unmatched nodes,
  logged as lower-confidence links).
- Field-level staleness: diff the specific claim a test case depends on, not the
  whole section body, so a change to an unrelated paragraph doesn't flag every
  test case in the section.
- Real MongoDB behind the same `doc_store` interface, and Alembic migrations.
- An integration test suite (currently only the parser is unit-tested; the
  end-to-end flow is covered by `scripts/demo.sh`).

---

## Decision log

**1. What's the one part most likely to silently give wrong results without
erroring? How would you catch it?**
The **parser's parenting**, and after it, **path-based version matching**. Both
can produce a tree/match that looks structurally fine but attaches the wrong
body to the wrong section — no exception, just quietly wrong traceability, which
is the worst outcome for QA. I catch parenting with the targeted unit tests
(duplicate headings, level skips, fenced `#`) and by asserting no content is
dropped (preamble node + reassembly check). Matching I'd catch with a
reconciliation report on each re-ingest: counts of matched / new / removed
nodes, eyeballed against the expected diff — a rename silently showing up as
"1 removed + 1 added" is the tell.

**2. Where did you choose simplicity over correctness because of time, and what
breaks first in production?**
Staleness severity is a raw-text heuristic (numeric-token diff + similarity),
not a semantic understanding of what each test case actually depends on. First
thing to break in production: a **material change with no number** — e.g. "the
device must auto-deflate" → "the device should auto-deflate" — gets classified
`cosmetic` and under-warns a reviewer. Also the JSON store isn't concurrency-safe
beyond a single-process lock; under real concurrent writers it would need a real
DB.

**3. Name one input you did not handle, and what the system does when it sees
it.**
A **renamed heading** across versions (parser/matcher input). The system does
not recognize it as the same section: the old `logical_id` is reported `removed`
and a new node appears. Any generation pinned to the old section is flagged
`removed` at retrieval — so we fail *safe* (the user is warned the source is
gone) but we lose the "same section, new title" link and would make the reviewer
re-select and regenerate manually.

## Conclusion

This project demonstrates a version-aware QA traceability system that combines
structured storage, document versioning, and AI-assisted test case generation.
The design prioritizes reproducibility, traceability, and safe handling of
document updates through version-pinned selections and staleness detection.