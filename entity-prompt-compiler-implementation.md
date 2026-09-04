# Entity Spec → Prompt Compiler
## End-to-End System Process Flow & Implementation Guide

**Scope:** 20K credit agreement documents, 200 ground-truth fields (mixed primitive / derivative).
**Core principle:** Nobody writes 200 prompts. Entity specs are data; prompts are build artifacts compiled from them. Ground truth turns prompt authoring into a measurable search problem.

---

## 0. System Overview

```
                    ┌─────────────────────────────────────────────┐
                    │            SPEC REGISTRY (YAML)             │
                    │   200 entity specs, versioned + immutable   │
                    └──────────────┬──────────────────────────────┘
                                   │
   ┌──────────────┐   ┌────────────▼──────────┐   ┌──────────────────┐
   │  S1 GROUNDING│──▶│  S4 PROMPT COMPILER   │──▶│ S5 EXTRACTION    │
   │  PROBE       │   │  6 archetypes         │   │ RUNTIME (ADK)    │
   │ (no LLM)     │   │  spec → prompt        │   │ section bundles  │
   └──────┬───────┘   └───────────────────────┘   └────────┬─────────┘
          │                                                 │
          │ unresolved fields                        claims + evidence
          ▼                                                 ▼
   ┌──────────────┐                              ┌──────────────────┐
   │ S2 RLM       │                              │ S6 DERIVATIVE    │
   │ DERIVATION   │                              │ DAG (determinist)│
   │ MINER        │                              └────────┬─────────┘
   │ (design-time)│                                       │
   └──────────────┘                              ┌────────▼─────────┐
                                                 │ S7 EVAL HARNESS  │
                                                 │ per-field gates  │
                                                 └────────┬─────────┘
                          ┌───────────────────────────────┤
                          ▼                               ▼
                 ┌──────────────────┐          ┌────────────────────┐
                 │ S8 RALPH+GEPA    │          │ S9 DISCOVERY LOOP  │
                 │ optimize the     │          │ residuals/anomaly/ │
                 │ failing tail     │          │ contradictions     │
                 └────────┬─────────┘          └────────┬───────────┘
                          │                             │
                          │  new spec version           │ new field candidates
                          └──────────┬──────────────────┘
                                     ▼
                          ┌────────────────────────┐
                          │  CLUSTER ADJUDICATION  │
                          │  BOARD (HITL)          │
                          └────────────────────────┘
```

**Loop invariant:** every change to system behaviour is a change to a YAML spec version. No prompt is ever hand-edited. No code deploy is required to add a field.

---

## 1. Data Model (PostgreSQL — sole state store)

```sql
-- corpus
document(doc_id PK, family_id, doc_type, effective_date, page_count,
         sha256, parsed_at, parser_version)
document_family(family_id PK, base_doc_id, amendment_count)
document_text(doc_id PK, full_text, char_len)          -- offsets are sacred
document_section(doc_id, section_id, path, heading, level,
                 char_start, char_end, page_from, page_to)
defined_term(doc_id, term, definition_text, char_start, char_end)

-- labels
ground_truth(doc_id, field_id, value_raw, value_norm,
             provenance_span NULL, split)               -- split at FAMILY level
label_audit(doc_id, field_id, verdict, adjudicated_by, adjudicated_at)

-- specs & artifacts
entity_spec(field_id, version, tier, archetype, yaml_body,
            status, created_at)                          -- immutable per version
spec_release(release_id, created_at, pinned JSONB, signed_by)
prompt_artifact(field_id, spec_version, prompt_hash, template_id, prompt_text)

-- probe & mining
grounding_probe(field_id, doc_id, match_type, section_id,
                char_start, char_end, score)
derivation_recipe(field_id, recipe_id, expr, coverage, sample_n, source)

-- runtime
extraction_run(run_id, doc_id, release_id, model, cost_usd, latency_ms, status)
extraction_claim(claim_id, run_id, doc_id, field_id, value_raw, value_norm,
                 confidence, evidence_span, section_id, route)
validator_result(claim_id, validator_id, passed, detail)
derived_value(doc_id, field_id, value_norm, rule_id, inputs JSONB)

-- eval & discovery
eval_result(field_id, spec_version, split, n, exact, norm_exact,
            list_f1, evidence_iou, abstain_rate)
residual_span(doc_id, char_start, char_end, salience, cluster_id)
discovery_candidate(candidate_id, kind, cluster_id, leverage, exemplars JSONB, status)
adjudication_cluster(cluster_id, compile_target, size, status)
```

Queue mechanics: `SELECT FOR UPDATE SKIP LOCKED` for work claiming, `LISTEN/NOTIFY` for wake-up. Runs are idempotent on `(doc_id, release_id)`.

---

## 2. Stage-by-Stage Implementation

### STAGE 0 — Corpus & Ground Truth Preparation

**Goal:** every document is text with preserved character offsets, a section tree, and a defined-terms index; every GT value is loaded and split.

1. **Parse with offset preservation.** Layout-aware extraction (page → text) writing a `char → (page, bbox)` map. Do not lose offsets; every downstream stage — probe, evidence spans, IoU scoring, adjudication provenance — depends on them.
2. **Build document families.** Credit agreements travel as base + amendments + amended-and-restated. Link by borrower/facility identifiers and order by `effective_date`. Wrong family linkage silently corrupts every cross-document field.
3. **Segment sections.** Credit agreements are highly regular: Article/Section numbering, ToC, Schedules, Exhibits. Regex over the numbering hierarchy plus heading detection gets you 90%+. Store as a tree with char ranges.
4. **Extract defined terms.** Section 1.01 "Definitions" gives you a per-document dictionary (term → definition → span). This is the single most reusable asset in the corpus and is required for cross-reference resolution later.
5. **Load ground truth.** Normalize by inferred type (money, date, percent, enum, string, list). Keep `value_raw` alongside `value_norm`.
6. **Split at family level, not document level.** Splitting amendments away from their base agreement leaks answers into dev/test. Freeze the split and never touch test until release gates.

**Exit criteria:** 100% of docs have a section tree; offset map round-trips; GT loaded for all labeled docs; splits frozen and hashed.

---

### STAGE 1 — Grounding Probe (no LLM, highest leverage)

**Goal:** classify all 200 fields into tiers, and harvest section anchors + few-shot examples for free.

Run on a labeled subset of 300–500 documents.

1. **Build a matcher cascade per field**, driven by inferred type:
   - exact string
   - whitespace/case/punctuation-normalized
   - numeric: currency symbols, scale words (million/MM), thousands separators, parentheses-negatives
   - date: multi-format parse then compare as date
   - fuzzy: token-set ratio ≥ 0.90
   - enum: synonym table
2. **Record every match** with `section_id` and char span, not just the first hit.
3. **Compute per-field diagnostics:**
   - `literal_hit_rate` — fraction of labeled docs where the value appears in text
   - `ambiguity` — mean candidate spans per doc (high = needs disambiguation, not better wording)
   - `section_entropy` — how concentrated the true span is (low entropy = strong anchor)
   - `page_position` distribution
4. **Rule induction over the misses.** For fields with low hit rate, search a bounded operator set to reproduce the value from *other GT fields*:
   - identity / aliasing
   - arithmetic: sum, difference, ratio, min/max over a field set
   - date arithmetic: offset in days/months, business-day roll
   - enum mapping / threshold bucketing
   - conditional: `if A then X else Y`
   Validate any candidate expression across **all** labeled docs, not the sample it was induced from.
5. **Assign tiers:**

| Tier | Name | Test | Gets a prompt? |
|---|---|---|---|
| T0 | PRIMITIVE_SPAN | hit ≥ 0.85, low ambiguity | Yes — span extract |
| T1 | PRIMITIVE_NORMALIZED | hit high only after normalization | Yes — extract + normalize |
| T2 | PRIMITIVE_AGGREGATE | list/table, multi-span | Yes — table extract |
| T3 | DERIVATIVE_DETERMINISTIC | rule reproduces ≥ 0.98 | **No — code only** |
| T4 | DERIVATIVE_JUDGMENT | needs reasoning over text | Yes — rule-apply |
| T5 | CROSS_DOC | needs family/amendment resolution | Yes — crossref + RLM |

6. **Human spot-check 20 fields** across tiers before proceeding. A misclassified field wastes an entire optimization cycle.

**Exit criteria:** tier + confidence for all 200 fields; section anchors captured for T0–T2; few-shot span library populated.

**Expected shape:** roughly 60% T0–T2, 25% T3, 15% T4–T5. Only that last 15% needs real prompt engineering.

---

### STAGE 2 — RLM Derivation Mining (design-time only)

**Goal:** for T4/T5 and unclassified fields, author the derivation recipe automatically instead of by hand.

RLMs load the long prompt into a REPL as a variable and let the root model slice, search, and recursively sub-query it — which is exactly the regime where a full agreement family exceeds useful attention. Cost is amortized here because this runs once over ~20 documents per field, not 20K.

1. **Stand up the RLM harness.** Root model = reasoning-tier (Gemini 2.5 Pro); sub-call function = Flash. The document family, section tree, and defined-terms dict are loaded as REPL variables.
2. **Invert the task.** Provide the *known correct GT value* and ask for the **derivation**, not the answer: which sections, which defined terms, which amendment supersedes which, what rule converts evidence to value.
3. **Sample 15–25 labeled docs per field.** Collect derivations with evidence spans.
4. **Cluster derivations by structure.** A field with one dominant derivation shape is specifiable; a field with five is a candidate for splitting into sub-fields or routing to human-only.
5. **Canonicalize into a recipe** and re-execute it cheaply against the remaining labeled docs to measure coverage.
6. **Emit into the spec:** section anchors, dependency list, rule pseudocode, enumerated edge cases, and the negative cases where the recipe fails.

**Exit criteria:** every T4/T5 field has a written recipe with a measured coverage number, or an explicit `human_only` marking.

---

### STAGE 3 — Entity Spec Registry

**Goal:** every field is a versioned YAML record. This is the only surface anyone edits.

```yaml
field_id: revolving_commitment_total
version: 3
tier: T2_PRIMITIVE_AGGREGATE
archetype: table_extract
value_type: money
cardinality: one
domain: null

retrieval:
  section_anchors: ["Article II", "Schedule 1.01(a)", "Commitments"]
  strategy: section_anchor
  fallback: defined_term_trace
  window_tokens: 6000

normalization: money_usd_scale

depends_on: []
derivation: null

disambiguation:
  confusable_with: [swingline_sublimit, lc_sublimit, term_loan_principal]
  discriminator: "total of all Revolving Commitments, excluding sublimits"

validators:
  - nonneg
  - equals_sum(lender_commitments)
  - currency_matches(facility_currency)

evidence: required
few_shot_source: grounding_probe
few_shot_k: 3

confidence_policy:
  auto_accept: 0.92
  validate: 0.75
  escalate_rlm: 0.60

business_weight: high
status: active
```

**Registry rules**
- Versions are immutable. A change creates `version+1`.
- A `spec_release` pins an exact set of `(field_id, version)` plus prompt hashes, model IDs, and validator versions. Releases are signed.
- Promotion into a release requires passing the Stage 7 gate.
- Adding a field is a YAML addition plus a release. Zero code change, zero deploy.

---

### STAGE 4 — Prompt Compiler

**Goal:** deterministic `spec + archetype → prompt`. Prompts are build output, like compiled binaries.

**Six archetypes:**

| ID | Archetype | Used by |
|---|---|---|
| A1 | `span_extract` | T0 |
| A2 | `enum_classify` | T0/T1 enums |
| A3 | `table_extract` | T2 lists (lenders, commitments, pricing grids) |
| A4 | `normalize_extract` | T1 money/date/percent |
| A5 | `rule_apply` | T4 judgment |
| A6 | `crossref_resolve` | T5 amendment/defined-term chains |

**Compilation steps:**
1. Resolve archetype template from spec.
2. Inject the field definition and discriminator text.
3. **Auto-harvest few-shots from the grounding probe** — select k=3 for *diversity* (different section contexts, different surface forms, one hard case), never the first three matches.
4. **Inject the disambiguation block** built from probe span overlaps. Fields whose true spans co-occur in the same section are the ones the model confuses; naming them explicitly fixes more errors than any amount of wording polish.
5. Emit the output contract: strict JSON with `value`, `evidence_span`, `confidence`, and an explicit `abstain` path. Abstention must always be available — a forced guess is unrecoverable downstream.
6. Hash the prompt and store as `prompt_artifact` bound to the spec version.
7. **Compile-time lint:** contract present, abstain path present, no GT value leaked into few-shots for the doc being scored, token budget within window.

---

### STAGE 5 — Extraction Runtime

**Goal:** extract all active fields per document within a cost envelope that survives 20K documents.

1. **Retrieval planner.** Group active fields by section anchor into **bundles** of 8–15 fields sharing one evidence window. Bundle composition is computed at release time and cached.
   - Naive: 200 fields × 20K docs = **4M calls**
   - Bundled: ~25 bundles × 20K docs = **500K calls**
2. **ADK topology.** One `LlmAgent` per bundle archetype, instantiated by an agent factory from the spec release (question-specs-as-data, not 200 hand-written agents). `ParallelAgent` fan-out across bundles, `SequentialAgent` for the post-extraction pipeline. Default model gemini-2.5-flash.
3. **Bundle guardrail.** Cap bundle size and never mix confusable fields into the same bundle — cross-contamination between fields in one call is the dominant bundling failure mode.
4. **Emit claims, not answers.** Each output is a claim row: value, evidence span, confidence, section, route. Claim-level decomposition with provenance is what makes downstream verification and adjudication tractable.
5. **Confidence routing:**
   - `≥ auto_accept` → accepted
   - `validate .. auto_accept` → run validators; pass → accept, fail → escalate
   - `escalate_rlm .. validate` → RLM escalation over the document family
   - `< escalate_rlm` or T5 → RLM tier directly
   - RLM output still failing → HITL queue
6. **RLM escalation tier.** Runtime RLM is an exception path, not a default. Gate it behind confidence and validator failure, and measure it per-field against plain section routing — adopt only where it demonstrably wins. Recursive decomposition can hurt when the evidence already fits comfortably in a window.

---

### STAGE 6 — Derivative DAG

**Goal:** compute T3 (and the deterministic scaffolding of T4) without LLM calls.

1. Build a DAG from every spec's `depends_on`. **Detect cycles at compile time**, not at run time.
2. Topologically sort; execute rules in Python/SQL against `extraction_claim` + `derived_value`.
3. For T4, the LLM handles only the judgment atom; the surrounding conditional structure, arithmetic, and enum mapping are deterministic.
4. **Emit contradiction events.** When a derived value disagrees with a directly extracted value for the same field, that is either a broken rule or a genuine document anomaly. Either way it is a free, high-precision signal — route it to Stage 9.
5. Propagate provenance: a derived value carries the claim IDs of its inputs, so any number is traceable back to spans in the source document.

---

### STAGE 7 — Eval Harness

**Goal:** per-field measurement that makes optimization targeted instead of vibes-based.

1. **Metrics per field on the dev split:**
   - exact match, normalized-exact match
   - list precision/recall/F1 for T2
   - **evidence-span IoU** — did it cite the right place? Catches right-answer-wrong-reason, which is the failure that silently breaks on new documents.
   - abstain rate and abstain precision
2. **Never report an aggregate as the headline.** The aggregate hides the tail, and the tail is the entire job.
3. **Segment by document vintage, lender, facility type, amendment depth.** Accuracy is rarely uniform; a field at 92% overall may be at 40% on amended families.
4. **Promotion gate:** a field enters a release only if normalized accuracy ≥ target **and** evidence IoU ≥ target on dev. Confirm on held-out test only at release time.
5. **Regression suite:** every release re-runs all frozen fields. Any regression blocks the release.
6. **Audit label noise.** With 200 fields, some ground truth is wrong. A field stuck at 80% frequently has 10% bad labels. Sample 20 disagreements per stuck field and adjudicate before spending optimization budget.

---

### STAGE 8 — Optimization Loop (Ralph + GEPA)

**Goal:** close the failing tail without touching prompt text by hand.

1. **Classify the errors first.** Before optimizing anything, bucket failures:
   - wrong section → **retrieval problem**, fix anchors
   - right section, wrong span → **prompt problem**, GEPA territory
   - right span, wrong value → **normalization problem**, fix post-processing
   - genuinely ambiguous → **label problem**, adjudicate
   Running GEPA on a retrieval failure burns budget and improves nothing.
2. **Select and rank** fields below gate by `business_weight × accuracy_gap`.
3. **Mutate the spec, not the prompt.** GEPA's reflective mutation operates on section anchors, few-shot selection, disambiguation set, normalization rule, and archetype choice. The prompt recompiles from the mutated spec.
4. **K=4 candidates via ParallelAgent**, evaluated on a dev minibatch, Pareto-tracked across fields so a gain on one field can't silently regress another.
5. **Winner writes a new spec version**; prompt recompiles; full dev eval re-runs.
6. **Stop conditions:** gate met; or N rounds with no improvement → escalate the field to the RLM tier or mark `human_only`. Fields do not optimize forever.

---

### STAGE 9 — Discovery Loop (unseen insights)

**Goal:** find what the 200-field schema doesn't cover. These candidates have no ground truth by construction, so they cannot go through the eval harness — they go to human adjudication.

1. **Residual coverage mask.** Mark every span consumed by an accepted claim. Everything unmarked is residual.
2. **Salience filter.** Keep residuals with high defined-term density, monetary amounts, obligation language ("shall", "may not", "provided that"), or that sit in high-value section types (Negative Covenants, Events of Default, Mandatory Prepayments).
3. **Corpus-wide clustering.** Embed and cluster residuals across all 20K docs. Frequency-sort. A residual pattern appearing in 4,000 agreements is a missing field; one appearing in 3 is a bespoke term.
4. **Corpus-normed deviation.** Build the clause-type distribution per section type and flag outliers. In credit agreements the rare bespoke carve-out is precisely what nobody wrote a field for and precisely what carries risk.
5. **Contradiction events** from Stage 6 join the candidate pool.
6. **Score leverage** = frequency × business proximity × novelty. Emit `discovery_candidate` rows.
7. **Route to the Cluster Adjudication Board** as leverage-sorted clusters. Compile targets extend to four:
   - `new_entity_spec` → becomes a YAML spec, re-enters Stage 3
   - `validator_rule` → hardens an existing field
   - `decision_branch` → deterministic rule promotion
   - `human_only` → permanently manual
8. **Labels accumulate** from adjudication, which is how a discovered field eventually earns an eval gate of its own.

---

### STAGE 10 — Release & Operations

1. **Release artifact** = pinned spec versions + prompt hashes + model IDs + validator versions + bundle plan. Immutable and signed.
2. **Full-corpus run** is a checkpointed job over 20K docs, idempotent on `(doc_id, release_id)`, work claimed via `SELECT FOR UPDATE SKIP LOCKED`.
3. **Do not run 20K until dev gates pass.** A full run at 60% accuracy generates 20K × 200 items of rework and destroys reviewer trust.
4. **Observability per field:** accuracy over time, cost, escalation rate, abstain rate, validator failure rate, RLM tier hit rate.
5. **Drift alarms:** abstain rate or escalation rate rising on a stable field means the incoming document mix changed, not that the model got worse.

---

## 3. Milestone Sequencing

| Milestone | Window | Deliverable | Gate |
|---|---|---|---|
| M1 | Weeks 1–2 | Ingestion, sections, defined terms, GT load, grounding probe | Tier classification for all 200 fields, spot-checked |
| M2 | Weeks 3–4 | Spec schema, prompt compiler, 6 archetypes, eval harness | T0/T1 running end-to-end on dev |
| M3 | Weeks 5–6 | Bundled runtime, validators, derivative DAG | T0–T3 at gate on dev |
| M4 | Weeks 7–9 | RLM derivation miner, T4/T5 specs, escalation tier | T4/T5 recipes with measured coverage |
| M5 | Weeks 10–11 | Ralph+GEPA on the failing tail | ≥ 90% of fields at gate |
| M6 | Week 12+ | Discovery loop, adjudication board, full corpus run | First discovered field promoted to spec |

---

## 4. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Character offsets lost in parsing | Breaks probe, evidence, IoU, provenance — everything | Offset round-trip test in CI on every parser change |
| Amendment family linkage wrong | T5 fields silently wrong with high confidence | Manual audit of 50 families; alarm on unlinked amendments |
| GT label noise read as model error | Optimization budget burned on unfixable fields | Adjudicate 20 disagreements before any field enters GEPA |
| Bundle cross-contamination | Confusable fields corrupt each other in one call | Cap bundle size; never co-bundle `confusable_with` pairs |
| Runtime RLM cost creep | Cost envelope blown at 20K scale | Hard escalation-rate budget per release; alarm at threshold |
| Optimizing wording when retrieval is broken | No improvement, high spend | Mandatory error classification before Stage 8 |
| Schema growth invalidating frozen fields | Regression on already-shipped fields | Immutable spec versions + regression suite on every release |

---

## 5. The Three Decisions That Matter Most

1. **T3 fields get code, not prompts.** Roughly a quarter of the 200 will be deterministic functions of other fields. Every prompt written for one of them is a permanent, avoidable source of error.
2. **RLM belongs at design time.** Use it once per field to *author the derivation* against known answers, then compile that into a cheap deterministic path. Runtime RLM is an escalation exception with a measured cost budget.
3. **Optimize specs, not prompts.** The moment someone hand-edits a compiled prompt, the registry stops being the source of truth and the whole loop degrades into 200 unmaintainable strings.
