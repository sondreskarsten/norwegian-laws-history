# Observation contract v1 and reconstruction migration requirements

Status: implemented observation-consumer boundary and later migration requirements for [history issue #1](https://github.com/sondreskarsten/norwegian-laws-history/issues/1). The consumer implements release receipt version 1 and producer evidence snapshots v4/v5. Snapshot v5 adds independently checked source-body capture; broader canonical rendering and legal reconstruction remain separate requirements. Local integration is not proof of a published release; ingestion must name an explicit receipt. No general parser-fidelity or legal-baseline claim follows from receipt acceptance.

## Product and scope

The initial product records **observed consolidated source versions** and complete parsed amendment evidence. A statement such as “observed on 25 September 2026” concerns this collector's knowledge. It does not mean the text entered into force on that date or that its past legal validity has been reconstructed.

The history repository begins from its own current README-only commit. No synthetic baseline, generated legal text, `law-history` commit graph or yearly tag is imported. Legacy outputs may be linked as explicitly unverified prior work; they are never an input authority.

The baseline producer assessed by the reuse audit is pinned to [`4f5bbf561208e436f488b086ebf34924cd435530`](https://github.com/sondreskarsten/norwegian-laws/tree/4f5bbf561208e436f488b086ebf34924cd435530). Its shipped [v2/v3 contracts](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/models.py#L198-L225) validate generated artifacts; they do not provide the complete historical evidence boundary required here.

## Version registry

| Identifier | Status | Meaning |
|---|---|---|
| Producer snapshot v2 | Shipped | Generated-artifact hashes/counts, legacy paragraph representation. Not enough raw provenance for history ingestion. |
| Producer snapshot v3 | Shipped | Requires `ordered-paragraph-blocks-v1` and `law-markdown-ordered-html-v1` for affected snapshots. Repairs tested paragraph ordering; does not certify whole-document structural coverage. |
| Producer snapshot v4 and `parsed-amendment-acts.v1.jsonl` | Implemented producer/consumer interface; public delivery verified separately | Immutable raw/member evidence and full parsed act occurrences under `lovdata-source-evidence-v1`. |
| `ordered-law-containers-v1` / `law-markdown-ordered-containers-v1` | Explicitly supported content/formatter pair within snapshot v4 | Optional root/section ordering references preserve interleaving of existing arrays. Reference validation is not independent source-fidelity verification. |
| `history-observation-v1` | Implemented consumer receipt/catalog | Source occurrence identity, observed/knowledge times, immutable evidence closure and attribution. |
| `history-canonical-v1` | Proposed here | A declared structural grammar, normalization rules, formatter identity and an independent ordered round-trip gate. |
| `history-materialization-v1` | Proposed here | Product tree, observation cutoff, explicit evidence status, code identity and append-only Git publication. |

Unknown versions fail before any state update. Producers never silently reinterpret an old version. A breaking schema, ordering, normalization or rendering change gets a new version and a migration report. Version 1 here is not a promise that all source documents can be represented.

## Producer handoff

The supported snapshot-v4 interface uses evidence descriptor version `lovdata-source-evidence-v1`. Receipt validation additionally requires release contract `lovdata-observation-release-v1`. Descriptor keys are `observations`, `members` and `parsed_amendments`, pointing to the paths below.

| Producer path | Required information | Consumer rule |
|---|---|---|
| `raw/<archive_sha256>.tar.bz2` | Exact observed archive bytes, SHA-256 and byte length | Verify bytes before reading members. Deduplicate storage by digest without deduplicating observation events. Raw bytes must remain retrievable. |
| `source-observations.json` | Archive origin, `observed_at`, upstream selected-list identity, archive hash/size and parser source-file hashes | Keep upstream `lastModified` as an assertion. Do not substitute it for collector observation or legal time. Record missing original download time as unknown, especially for a revalidated cache. |
| `source-members.jsonl` | Every tar entry's full path, zero-based tar-member ordinal, type and, for byte-bearing members, hash/size; parsed/excluded/unresolved status; refid/occurrence and selected-output binding | Every entry receives a disposition. Duplicate paths, language variants and duplicate refids remain distinct occurrences. No silent skip becomes a successful parse. |
| `parsed-amendment-acts.v1.jsonl` | Every parsed act occurrence before deduplication/SQLite; original `asdict(AmendmentActData)` fields and ordered amendment array; explicit ordinals, target/operation status and unresolved legal-valid-time status | Preserve all strings and array order without display truncation. It is complete relative to the parser result, not proof of complete source semantics. |
| Snapshot manifest | Exact artifact inventory, hashes and counts including the evidence paths | Require closure between raw bytes, member records, parsed occurrences and chosen current-product outputs. Selected-output policy must not erase alternatives from evidence. |

The observation artifact records `parser_identity` with `package_version`, SHA-256 values in `source_files` for `parser.py`, `models.py` and `evidence.py`, and an aggregate `sha256`. It declares `knowledge_cutoff` from the maximum local `observed_at`, basis `local_archive_observation`, and `historical_knowledge_time_status = unknown`. Archive records retain ordinal, digest/size, raw path, original name, role, prefix scope, observation/retrieval times, source URL/last-modified assertion and retrieval-time status. This does not supply historical knowledge times for older source publications. The concrete serialized field names are `archive_ordinal`, `archive_sha256`, `size_bytes`, `raw_path`, `original_filename`, `role`, `prefixes`, `observed_at`, `retrieved_at`, `source_url`, `source_last_modified` and `retrieval_time_status`.

Parsed-act envelopes declare `schema_version = parsed-amendment-acts-v1`, source identity and occurrence ordinal; `record` holds the exact parsed model, and `amendment_occurrences` preserves original ordinals and target/operation statuses. Its fidelity claim is `lossless_relative_to_parsed_model`; legal validity remains unresolved with null bounds.

The interface must report structural coverage as `not_verified` until the independent gate below has actually passed. The publication workflow supplies durable publication and digest readback. The history consumer downloads only explicitly selected published evidence bundles; it does not acquire directly from Lovdata.

### Container-order compatibility

For snapshot v4, the consumer accepts three exact content/formatter pairs: `legacy-paragraphs-v1` / `law-markdown-v1`, `ordered-paragraph-blocks-v1` / `law-markdown-ordered-html-v1`, and `ordered-law-containers-v1` / `law-markdown-ordered-containers-v1`. Snapshot v5 has its own pair below. Unknown or mismatched pairs fail before observation acceptance.

For the container pair, `content_order` is an optional array on the document root and each section. Missing or empty means the earlier grouping order. Each populated entry has exactly `kind` and `index`; the index is a nonnegative integer (not a boolean) within its owning array. Every item in every mapped array must appear exactly once. Repeated, missing, unknown or out-of-range references fail. The arrays remain the sole content owners.

| Container | Reference kind → owning field |
|---|---|
| Document | `paragraph` → `top_level_paragraphs`; `remainder` → `remainders`; `section` → `sections`; `article` → `top_level_articles` |
| Section, recursively | `preamble` → `preamble`; `article` → `articles`; `section` → `subsections`; `footnote` → `footnotes`; `remainder` → `remainders` |

A populated `content_order` under either older content pair is rejected, including in nested sections. Empty optional fields remain compatible with older pairs. These checks establish an internally complete ordering declaration; they do not show that XML order or all source semantics were captured. Accepted observations continue to declare canonical status `not_verified` and legal validity `unresolved`.

### Source-body snapshot compatibility

Snapshot v5 requires exactly `ordered-source-document-body-v1` /
`law-markdown-convenience-with-source-body-v1`. Every selected law/regulation
retains `source_body`; older contracts reject that field. The existing typed
arrays and container ordering remain the current reader's convenience projection.
They do not acquire a fidelity claim from the additional body evidence.

The capture envelope binds the raw member digest, exact ordered mixed-content
tree, and html/head/body attribute maps, language, base URL and refid. Tree and
context have independent canonical hashes. An Expat event reader checks each
selected body against its retained XML independently of the producer's
ElementTree capture. The archive and member identities, selected model hash,
output path, refid and receipt/snapshot version must all agree. Processing keeps
one selected raw body at a time with a 16 MiB raw limit. Unselected duplicate
occurrences retain exact raw members and catalog/model identities; this contract
does not add persisted body models for those unselected occurrences.

The parser identity has exactly four source files for v5: `parser.py`, `models.py`,
`evidence.py` and `source_body.py`. V4 keeps its original three-file identity.
The independent `source_body_gate.py` has no producer imports and is vendored
from the producer's standalone gate; its implementation identity must be pinned
by any later derived product that uses it.

Capture acceptance is distinct from renderer qualification. Unknown body forms
or captured inherited attributes may be retained exactly while the closed render
grammar rejects them. The initial grammar supports selected headings, provisions,
HTTP(S) links, source footnote navigation and regular tables with column spans.
Lists, numbered margins, row spans, images, formulas and unsupported contexts
remain explicit rejections. The gate returns HTML only after raw/model comparison,
grammar checks and reversal of the rendered result back to source events.
This compatibility release does not change already published body products or
claim that richer body products have been published. Legal validity remains
unresolved and whole-document completeness remains unassessed.

Routine operation catch-up preserves the latest accepted representation for an
observation and destination across consumer upgrades. It reports `already_present`
with the original generator identity. Explicit `extract-operations --observation`
still performs generator-specific extraction and can append an intentional new
representation. Neither path rewrites an older product or treats a code upgrade
as new source knowledge.

## Observation identity and clocks

History records must preserve, or unambiguously adapt from the finalized producer schema:

| Field | Rule |
|---|---|
| `observation_id` | Release identity: SHA-256 of canonical release-receipt JSON with a final newline, before adding `observation_id`, `release_tag`, `receipt_url` and `bundle.url`. The consumer recomputes this and every derived URL/tag. Replaying the same accepted receipt is idempotent. |
| `source_observation_sha256` | Separate producer observation-artifact identity from `manifest.artifact_hashes[manifest.evidence.observations]`. It is not the release observation ID. A later locally recorded observation changes this source artifact even if source bytes are unchanged. |
| Archive `archive_sha256`, `size_bytes`, `source_url` | Exact archive identity and recorded acquisition origin. Digest identity is not proof of upstream authenticity. |
| `source_occurrence_id` | Producer SHA-256 of canonical JSON `[archive_ordinal, archive_sha256, member_ordinal, member_path, member_sha256, role]` for parsed occurrences. The raw-byte member identity remains `(archive_sha256, member_ordinal)` plus exact path/type and digest. Refid and basename are not occurrence keys. |
| `observed_at` | Time the collector inspected the local archive bytes for this parse, with an explicit UTC offset. This is not necessarily the byte-retrieval or upstream-publication time, and is never synthesized from legal or Git dates. |
| `retrieved_at` | Optional actual byte-retrieval time when recorded; otherwise null. A cache hit must not invent it. |
| Archive `source_last_modified`; parsed act `date_published`, `date_in_force` | Verbatim source assertions preserved in the evidence bundle, kept separately from interpreted dates. |
| `knowledge_cutoff` | The explicit cutoff and included observation IDs used to build a product. Every included observation must be at or before the cutoff. Later observations cannot silently repair an earlier cutoff view. |
| Producer identity | Receipt `source_sha`, observation `parser_identity` and `parser_runtime`, snapshot content/formatter versions and selection policy. Runtime dependency versions may be explicitly unknown; a dependency lock is not currently supplied. |
| `data_attribution` | Lovdata source attribution, recorded license designation/link (NLOD 2.0 for these inputs), origin and retrieval evidence. Preserve separately any code-license notices. |

Preserve producer artifact digests byte-for-byte. For new history-specific claim/content identities, use SHA-256 with an explicit domain prefix and canonical UTF-8 identity JSON: sorted object keys, no insignificant spaces, no ASCII-only escaping, no implicit Unicode normalization and no floating-point identity values. The identity schema specifies which fields participate. Store that schema/version with the resulting digest. Content identity excludes run timestamps; observation identity includes the recorded observation. A materialization receipt binds both, avoiding nondeterministic content hashes.

Duplicate refids are not silently collapsed in the historical evidence model. In particular, both Constitution language-source occurrences remain addressable. A chosen display variant must cite its exact occurrence and a versioned policy; a filename-derived language guess is labeled an inference, not source metadata.

## Complete parsed amendment evidence

Preserve the original [act and amendment fields](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/models.py#L172-L194) in full. The envelope adds immutable source occurrence identity and ordinal; it does not rewrite source strings. Keep unknown target, unknown operation, empty replacement, and unresolved commencement records. A repeal may legitimately have no replacement text; emptiness must not filter it out.

An operation identity is scoped to its source act occurrence, parsed model digest and zero-based operation ordinal. A corrected or reordered parse therefore cannot reuse a previous operation identity. Include the target expression as observed, the candidate document identity, a target-resolution status and evidence pointers. Future target resolution adds a separately versioned claim instead of overwriting the raw parse.

Do not consume current display `amendments.jsonl` as the complete interface: it [filters unresolved targets and caps instruction/replacement text](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/manifests.py#L117-L153). Do not use normalized SQLite `date_in_force_resolved` as legal evidence.

## Legal valid time is a separate claim

Initial observations have `legal_valid_time.status = unresolved`, with null bounds, raw source expressions and a reason. Useful future statuses are `explicit`, `conditional`, `partial`, `conflicting` and `unresolved`; they describe the evidence analysis, not a guessed date. Unknown end time is null, not an invented repeal boundary.

Any claim of a legal interval must identify its document or operation scope, exact evidence occurrences and source locations, interpretation method/version, and the observation cutoff at which that evidence was available. Different provisions of one act may have different commencement. A later commencement order or correction is a new evidence-backed claim; it does not erase what was known earlier.

Publication time, first observation, disappearance from a consolidated archive, amendment-act order and Git timestamps are not substitutes. The current parser's [publication fallback](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/parser.py#L85-L120) is retained only as legacy diagnostic data if imported at all. The first pilot does not reconstruct legal intervals or apply amendments.

## Canonical content and the fail-closed structural gate

The archival authority is the immutable raw source. Canonical content is a declared projection, with its exact parser, grammar, normalization policy and renderer recorded. “Lossless” must always name that declared projection; storing XML bytes and rendering readable text are different claims.

For the initial supported grammar, compare three independently traversed ordered event streams:

1. Source bytes → normalized source events, preserving source node path/ordinal, meaningful text, legal hierarchy, markers, mixed child order and referenced structure.
2. Parsed model → normalized model events with source coverage bindings.
3. Canonical output → reverse-parsed events in the same declared grammar.

Promotion requires exact sequence and structural equality, matching digests, one-to-one accounting of meaningful source occurrences, and zero unclassified remainder. Define any ignored chrome or whitespace normalization in a versioned whitelist with source-accounting records. Do not blanket-ignore a `footer` that contains a legal footnote. Punctuation, marker values, nested boundaries, tables, links and other meaningful constructs cannot be dropped as “formatting.” An unsupported construct blocks that document's derived-text promotion until its grammar is supported or an explicit, reviewable narrower projection is chosen.

The verifier must reject dropped text, reordered siblings, merged or duplicated clauses, changed markers, moved nesting, hidden remainder and injected extra output. A 100% token multiset score does not pass this gate. The pinned source already demonstrates that failure mode in [pinned-probes.json](evidence/pinned-probes.json). Model JSON serialization round-trip alone also does not prove source fidelity.

Gate outcomes are `passed`, `failed` or `not_verified`, with verifier version, artifact hashes and reasons. Only `passed` may promote canonical derived text. `failed`/`not_verified` still allow immutable raw receipt publication, clearly labeled; they do not allow an unverified text to enter the canonical materialized law tree. Aggregate thresholds must not hide a failed document.

## Materialization and Git contract

Each accepted `history-materialization-v1` receipt records:

- Materialization kind: `observed_document_body_projection`, not “law in force as of year X.”
- Knowledge cutoff, included observation IDs, exact source member identities and any explicitly selected variant.
- Content/formatter/verifier versions, code/runtime identity and the per-document gate result.
- Complete product artifact hashes, parent materialization ID and the final Git tree/commit identity in a separate publication receipt.
- Unresolved or quarantined members and reasons; full inventory counts reconcile with source observations.

Avoid circular hashes: the commit contains a materialization identity and expected artifact tree; a subsequent publication receipt binds that identity to the observed commit/tree. Hashes do not include their own digest field. Git author/committer identity names the producing project, not Lovdata; Git dates record repository publication/observation policy, not inferred legal effect.

Identical evidence and canonicalizer produce identical semantic artifact bytes/tree. Reprocessing an identical accepted receipt is idempotent. A later observation of unchanged content adds new observation evidence. The initial observation consumer stored no canonical text tree; the bounded materializer below adds only independently qualified document-body projections. A parser/formatter migration is explicitly labeled `representation_change` and includes old/new versions and deltas; it is never reported as a new legal amendment.

Publication is append-only with an expected parent. A rejected push triggers regeneration against the new parent or a controlled retry of the same intended commit; never rebase already-generated evidence or force-push history. Existing observation/materialization identities and release assets must not be overwritten. Read back the committed receipt and required raw evidence by digest before recording delivery success.

## Forkable core and durable evidence

Core execution uses public source reads and the fork's ordinary `GITHUB_TOKEN` for same-repository writes. It must not require a PAT, a cloud account, parent-repository write access, or optional external storage. Grant only the job permissions needed for the chosen repository publication path; untrusted pull requests run verification without publishing credentials.

The publication workflow must retain raw bytes at a durable locator accessible with the fork's core setup. Git is suitable for bounded fixtures; content-addressed GitHub Release assets are an available token-only option for large archive bytes. Final storage/retention mechanics are an implementation decision of that workstream, but expired Actions artifacts or a mutable download URL are not a complete durable source record. Missing raw evidence or failed digest readback blocks a delivered-history claim. An optional GCS mirror can add durability; it cannot be a prerequisite for core ingestion, verification or repository materialization.

No secret-bearing workspace files enter products. Publish an explicit file inventory derived from the intended commit, not the whole runtime working directory. The receipt gate validates source identity and product identity independently of a workflow's green status.

## Bounded first pilot and acceptance

Candidate scope is one small law source and one small regulation from an actually observed archive: `lov/1687-04-15` and `forskrift/2026-09-18-1871` are available sample candidates, not pre-certified parser successes. Regnskapsloven §6-2, the mixed-section counterexample and duplicate Constitution language occurrences are stress/rejection fixtures. If neither candidate passes the structural gate, publish only raw observation receipts; do not broaden claims to get a green pilot.

The pilot accepts two real acquisition observations with recorded UTC times. It preserves archive/member bytes and identities, records full parsed acts relevant to the selection without filtering unresolved operations, and produces canonical documents only where the structural gate passes. The second observation may have identical content; that is a valid no-change outcome. An archive membership disappearance is labeled `not_present_in_observation`, never assigned a repeal date.

Before accepting the pilot, independently retrieve the product receipt and cited raw evidence, recompute hashes, regenerate the selected tree offline, confirm no synthetic legacy inputs, and verify that unresolved time/operation claims remain visible. The fork run must succeed without custom secrets. The publication workflow provides live execution and remote readback; the six issue drafts divide component work without creating another orchestration path.

## Implemented observation ledger

`observations/<release-observation-id>/` contains `receipt.json`, `source-observations.json`, `members.jsonl` and `observation.json`. Acceptance validates all release/snapshot/raw/member bindings before atomically promoting a new directory. Prior directories are never edited. The catalog preserves each member occurrence and duplicate refids. Replaying a matching receipt does not rewrite files; conflicting receipt identity or payload fails. The local `.cache/bundles/<sha256>.tar.gz` is ignored by Git and can be repopulated from the receipt URL. Raw XML retrieval verifies the bundle, archive and chosen member hash and requires an explicit occurrence when ambiguous. Outer bundles contain only unique safe regular paths; raw archives are inventoried, never extracted wholesale.

The summary always declares `canonical_status = not_verified` and unresolved legal bounds. `show` retains earlier presence when a later compatible-scope observation lacks a document, labeling absence only as `not_present_in_observation`. Incompatible selections report `scope_not_comparable`, never observed absence. The separate bounded materializer below qualifies declared document-body projections; no command computes legal states.

## Bounded document-body materialization

`strict-document-body-v1` declares a narrow ordered projection: document-body
title, section/article hierarchy, legal paragraphs and explicitly marked ordered
lists. The qualification report versions normalization, source attributes and
exclusions. Source metadata outside the body stays in retained XML. Unknown
inline semantics, tables, footnotes or unnamed/unrepresented forms prevent
promotion until supported. The complete corpus is not certified by a subset.

`history-materialization-v1` binds one accepted observation, an explicit selection
of at most 20 refids, its parent product, source/model occurrence identities,
producer/parser and generator/runtime identities, all artifact hashes and each
qualification result. Only passed documents have body JSON/HTML; failed and
missing selections remain inventoried. The receipt's own ID is SHA-256 over its
canonical payload excluding that ID. Semantic body bytes omit observation and
publication timestamps. The same inputs, versions and parent give the same
receipt and artifacts; different runtime versions are different generator
identities and must not be claimed cross-runtime byte-identical receipts.

The append-only product chain is independent of legal chronology. A new source
observation may contain unchanged bodies. A changed body with the same original
XML digest is a representation change; a changed source/body is an observed text
change without an inferred legal date. Global observation canonical status stays
`not_verified`, and legal bounds stay null/unresolved. Product publication binds
the actual Git commit/tree in a subsequent separate receipt.

## Migration gates

The implemented `history-operation-product-v1` exports the entire accepted parsed
act inventory as compressed, canonical JSONL shards. Each
`history-operation-evidence-v1` record preserves the original envelope, every
operation and initial `history-unresolved-legal-time-v1` claims. Commencement
expressions have source paths, text and candidate roles; their applicability is
unresolved. No candidate text, publication date, resolved legacy date or Git date
sets a legal bound. Source instruction alignment is explicitly either uniquely
matched or unresolved; matching text alone does not establish legal effect.

The product includes exact input-manifest and source-member catalog proofs. The
consumer binds them to the accepted observation, reconciles every parsed
occurrence/model/ordinal and operation count, verifies shard/index hashes, and
checks the preserved producer records and unresolved claims. It cannot certify
instructions omitted by the producer parser or the structure flattened by it.
Ordered replacement subtrees and scoped legal-time interpretation remain
unfinished. Append-only later proposals are implemented separately below and
remain ineligible for reconstruction.

`operation-products/<identity>/receipt.json` is the only product file in Git.
Its content-derived release contains the complete artifact bundle; the receipt
hash excludes its own ID and the tag/URL derived from that ID. Bundle size/hash,
all member hashes, generator/runtime and parent are included. Publication checks
the Git parent, uploads without replacing assets, independently downloads the
public bytes, and subsequently records the real creation commit in
`operation-publications/<identity>.json`. Interrupted publication is replayable;
previous accepted products and first release targets remain unchanged.

| Gate | Required evidence | Failure behavior |
|---|---|---|
| A — Producer interface frozen | Merged producer commit, exact v4/parsed-act schemas, artifact/member reconciliation and complete failure tests | Reject unsupported versions; retain input evidence for diagnosis; no history state update. |
| B — Observation acceptance | Complete raw-byte hashes, immutable occurrence IDs, timestamps, attribution and durable retrieval | No accepted observation receipt if evidence closure is incomplete. |
| C — Canonical structural qualification | Independent ordered round-trip equality and zero unclassified remainder for each promoted document | Raw receipt only; quarantine the derived document. |
| D — Git materialization | Deterministic product tree, knowledge cutoff, expected parent, versioned rendering and explicit unresolved claims | No overwrite/force-push; keep prior accepted state. |
| E — Delivered pilot | Token-only fork execution, remote product/raw readback, repeat observation and offline reproduction | Report generated/uploaded/read-back states separately; do not claim delivered history. |
| Later — Legal-state reconstruction | Explicit prior-state basis, scoped operation resolution, commencement evidence and independent consistency checks | Outside this observation-pilot contract; separately included in the full product plan. No synthetic baseline or date fallback. |

## Complete source-body products

`history-source-body-product-v1` inventories every selected law/regulation in
an accepted snapshot-v5 observation, in catalog order. Qualification independently
compares raw XML, the captured ordered model and reverse-parsed rendered output.
Only passed documents have payloads; rejected documents retain explicit reasons
and raw-source bindings. Exact styles and labelled keyboard-scroll table regions
are part of the renderer version. The earlier bounded materializer and its
published products remain unchanged.

The receipt binds source/generator/runtime identities, selected/passed/rejected
counts, every compressed artifact digest and an exact release bundle. Only the
receipt enters `body-products/<id>/` in Git. Source-body JSON, standalone HTML,
styles and the complete inventory reside in compressed release artifacts.
`body-publications/<id>.json` subsequently records checked Git creation after
anonymous release readback.

The append parent and comparison baseline are distinct. Comparison chooses the
latest applicable representation among earlier products whose source observation
does not exceed the target observation. Cumulative last-qualified entries retain
earlier bodies across rejection or absence. Reprocessing an older observation
cannot use future evidence; reprocessing a later one may use that improved
earlier representation. Changes remain observed-body or representation changes,
never inferred legal changes. Every legal-time bound stays unresolved.

## Later interpretation proposals

`history-later-claim-request-v1` requires an exact target (operation-product ID,
act refid/source occurrence, subject ID, parsed revision and parsed-model hash),
one current `supersedes` claim ID, `manual-proposal-v1`, an assertion, a
knowledge cutoff and typed evidence references returned by `claim-history`.
Assertions retain text, proposed scope and proposed legal bounds. Evidence
locations must resolve exactly in fully verified products, including cross-product
citations. Stored bindings include the cited value, record, bundle and receipt
hashes. A cutoff cannot precede cited evidence or its predecessor, or exceed the
proposal's actual recording time.

All accepted records use `history-later-claim-v1`, status `proposed` and
`reconstruction_eligibility.eligible=false`. No registered method establishes
legal truth. Cutoffs are submitted assertions bounded by retained evidence, not
proof of historical knowledge. `eligible_reconstruction_inputs` remains empty.

Records are installed exclusively under
`later-claims/<two-hex-subject-bucket>/<claim-id>.json`. Full subject identity
is retained and hashed in each record; buckets only shorten Windows paths.
Subject chains are linear and append-only, beginning with the exported unresolved
claim. Request replay preserves the original recording time, including after
later supersession. Bucket-scoped writer locks prevent concurrent conflicting
heads; no prior record is overwritten.

`claim-publications/<claim-id>.json` binds canonical proposal bytes to their
unique Git creation commit, checked parent and current committed bytes. An exact
already committed publication proof permits routine replay without downloading
old cited releases again. New claims still require full evidence verification.
Explicit `claim-history` performs the full evidence audit. Git and recording
timestamps remain separate from proposed legal bounds.
