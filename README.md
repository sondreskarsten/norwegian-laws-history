# Norwegian laws: observed source history

**Delivery resumed, 26 September 2026:** [delivered functionality, unfinished work and pending runs](docs/DELIVERY-STATUS.md).

This repository independently verifies published Lovdata evidence releases and records which source bytes were observed. It can show a document's observations and retrieve its exact archived XML. It does not reconstruct past legal states or infer commencement or repeal dates.

The Python consumer uses only the standard library (Python 3.11+). From this checkout:

```text
python -m pip install .
python -m law_history ingest https://github.com/sondreskarsten/norwegian-laws/releases/download/observation-ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596/evidence.json
python -m law_history list
python -m law_history show lov/1998-07-17-56
python -m law_history show forskrift/2022-12-21-2456 --role forskrifter
python -m law_history raw lov/1998-07-17-56 --observation ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596 --occurrence 8abce8ef66dc6bc48ebedd3bfa3b397f92b8222eeb1179e343dbf83be86509be --output regnskapsloven.xml
```

This example uses a real public receipt and a 191 MB source bundle. The observation is already accepted in this repository, so replay reports `already_present`; use `--repository PATH` before `ingest` for a separate ledger. The installed `law-history` command is equivalent to `python -m law_history`. For local ingestion, `snapshot.tar.gz` may sit beside `evidence.json`, or be supplied using `--bundle`. `raw --output` creates a new file and never overwrites one. For another document, obtain its observation and source occurrence IDs from `show`.

## Historical source availability

Use `python -m law_history source-coverage [REFID]` to inventory retained source versions and their exact observation/member locations. Add `--known-at TIMESTAMP` to exclude later observations. [The complete coverage report](docs/SOURCE-COVERAGE.md) separates source availability from unqualified baselines and unresolved legal intervals.

## Delivered public observation

On 25 September 2026, the [first public intake](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36169832648) accepted 4 archives and 45,114 source members in commit [`611153d`](https://github.com/sondreskarsten/norwegian-laws-history/commit/611153d93419437ba74a07ab07ce5067afabbbef). A fresh isolated consumer installation independently accepted the same public bundle, replayed it without changing ledger files, and retrieved Regnskapsloven and `forskrift/2026-09-18-1871` XML byte for byte from their original archive members. All four committed ledger files match that independent ingestion.

The [production replay](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36170157045) also returned `already_present` and created no commit. [Read the portable evidence report](docs/evidence/public-consumer-readback.json) for the pinned consumer/producer identities, source hashes, and verification scope. These results establish source delivery and retrieval, not historical legal correctness.

## Verification and limits

Before accepting anything, the consumer independently checks the release's derived identity and URLs, bundle size/digest, safe regular bundle members, exact snapshot-v4/v5 artifact hashes and counts, every retained raw archive/member, selected document bindings, complete parsed amendment occurrences and SQLite consistency. It never imports the producer or publisher at runtime. Unsupported contracts or mismatches fail before an accepted observation is written.

Snapshot v5 additionally preserves an ordered `source_body` in every selected current document. The consumer independently compares its text, element order, attributes and inherited context with the exact raw XML using a separate XML reader. This is a capture-fidelity check, not a legal-state claim or permission to render unsupported structures. Existing v4 observations and derived products retain their original contracts and bytes. See [the source-body contract](docs/CONTRACT.md#source-body-snapshot-compatibility).

The current consumer also accepts the explicit ordered-document-container contract, merged in [`99943ec`](https://github.com/sondreskarsten/norwegian-laws-history/commit/99943ec03e1d9f4c5b73e7946f6af7bf09cb9f34). Its [bounded local verification](docs/evidence/container-order-validation.json) is separate from the public observation readback above; neither promotes canonical legal text.

Accepted observations are immutable directories under `observations/<release-observation-id>/`. They contain the release receipt, original source-observation metadata, a member/refid catalog and an observation summary. Replaying an identical receipt is a no-op. A later observation adds a directory; it never erases earlier sources. `show` reports `not_present_in_observation` only for comparable selections. Changed selections report `scope_not_comparable`; neither makes a repeal claim.

Use `show --role laws`, `--role forskrifter` or `--role amendment_acts` to inspect membership in one archive role. A regulation can leave the current corpus while its original act remains in the amendment archive; an unrestricted lookup correctly still finds that source. The role-specific lookup exposes the current-corpus exit. A missing archive or changed selection is explicitly incomparable. The [public-ledger example](docs/evidence/current-source-exit-public.json) records six current-corpus observations followed by three observed absences, with legal validity still unresolved.

Git preserves ledger bytes exactly, including line endings. A fresh Windows
checkout with automatic CRLF conversion enabled was verified with `list` and
the recorded hashes. If an older checkout reports `Stored observation payload
changed`, use a fresh clone to restore the published bytes; do not rewrite the
accepted receipt or its hashes to match converted files.

Large source bundles are retained in the ignored `.cache/bundles/` directory by digest. The public release URL remains in the ledger. If a bundle is absent from the cache, `raw` retrieves it from that URL and checks its digest again. A local-only rehearsal cannot be recovered from a nonexistent public URL; keep its bundle. A corrupted cache entry fails closed and can be removed before retrying. SHA-256 proves consistency with a receipt, not a source signature or permanent storage availability.

Every accepted observation reports canonical structure as `not_verified` and legal validity as `unresolved`. Observation timestamps are collector knowledge times. Qualified document-body products are separate, scoped projections; they never certify the whole observation or establish legal dates. There is no amendment engine, synthetic historical baseline, imported legacy history graph, or mandatory cloud/PAT credential. Public ingestion is read-only and unauthenticated; workflow publication is separate.

## Qualified observed document bodies

The `materialize` command generates a bounded selection from an accepted public
observation. It independently compares ordered source, model and rendered-body
structure using `strict-document-body-v1`. Unknown forms stay unqualified, with
source-accounting and rejection reasons. Exact XML remains available independently.

```text
python -m law_history materialize --observation ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596
python -m law_history materializations
```

Each `materializations/<identity>/` directory contains a browseable README,
inventory, per-document qualifications and, only for passed documents, readable
HTML and ordered body JSON. Download the HTML and open it in a browser. The
default seven-document selection includes complex cases that are deliberately
reported as unsupported, alongside three qualified candidate documents.

Use repeated `--refid` arguments with an explicit observation for another
selection of at most 20 documents. `--expected-parent none` requires an empty
product chain; a full materialization ID requires that current chain tip.
Replaying the same observation, selection and generator is otherwise a no-op.
An explicit stale parent is rejected even on replay. Later representations append
new products and preserve earlier identities; changed source text is an observed
change, never automatically a legal amendment.

An exclusive local writer lock prevents two concurrent materializers from forking
the parent chain. A crashed process can leave `.cache/materialization-writer.lock`;
confirm that its recorded process is no longer running before removing that exact
lock file and retrying. Accepted products are never removed as recovery.

The generator identity includes exact source hashes and Python runtime version.
The same evidence, selection, generator/runtime and parent reproduce the same
product identity. Semantic body identity excludes observation timestamps; a
runtime or renderer change can produce a new representation receipt without
changing that semantic body. Published-product and independent readback evidence
are recorded separately from the availability of these commands.

To reproduce a published product, run the manual [reproduction workflow](.github/workflows/reproduce.yml)
with its full materialization ID. It selects the receipt's exact Python version,
checks the current generator source against the recorded hashes and validates the
product's actual Git creation receipt. It fetches the source bundle, creates a
separate ledger with only preceding products, denies network access, and regenerates
the requested product. Success requires the exact receipt and every artifact to
match; the requested output is never copied into the fresh ledger. A different
generator requires checking out its recorded implementation before reproduction.
This read-only workflow is separate from a clean-fork publication rehearsal.

The equivalent local command, using the matching Python version and generator, is
`python -m law_history.reproduce MATERIALIZATION_ID --report reproduction.json`.

## Complete observed-body products

For accepted snapshot-v5 evidence, `qualify-bodies` accounts for every selected
law and regulation. Each document either has a qualified ordered body with
standalone HTML, or an explicit rejection with its original XML still available.
The grammar supports declared links, notes, simple column-spanning tables,
source-labelled nested lists and additional article headings; unsupported structures remain rejected. A complete inventory does not
mean every document qualifies.

```text
python -m law_history qualify-bodies
python -m law_history body-products
python -m law_history body lov/1687-04-15 --product BODY_PRODUCT_ID --output observed-body.html
```

Replace `BODY_PRODUCT_ID` with an exact ID from `body-products`. The ordinary
lookup verifies the pinned receipt and exact artifact bytes. Use
`body-products --verify` to independently requalify all products against their
retained raw sources. Only qualified documents can be saved as HTML; an output
file must not already exist.
Requalification requires the recorded renderer contract. When that contract
changes, use its pinned implementation to audit an older product; ordinary
receipt-bound retrieval continues to serve its original bytes.

The [full local rehearsal](docs/evidence/source-body-full-corpus-local.json)
accounted for all 5,874 selected documents: 1,219 qualified and 4,655 were
explicitly rejected. It includes independently retrieved examples and browser
checks of links, footnotes and tables. This local rehearsal is not a public
body-product publication. The subsequent [v3 full rehearsal](docs/evidence/source-body-v3-full-corpus-local.json) qualified 3,203 bodies and rejected 2,671, preserving the exact text, structure, HTML and styling of all 1,219 prior qualified bodies. Its expanded coverage is local until separately published.

Each `body-products/<identity>/receipt.json` points to a separate immutable
`bodies-<identity>` GitHub release. Large artifacts stay outside Git. The
publisher downloads the public bundle before committing a separate creation
receipt under `body-publications/`. Routine catch-up reuses already accepted
representations; explicit regeneration appends a new identity. Earlier products
and rejected/missing observations remain preserved. These bodies describe
observed sources and do not establish what law applied on a historical date.

Use the [complete-body reproduction workflow](.github/workflows/reproduce-bodies.yml)
with a published body product ID to reproduce the exact receipt, compressed
bundle and every artifact. It keeps the current full-history ledger and checks
out the code recorded before product creation separately. Before fetching
sources, it requires the exact Python and zlib versions and all five generator
module hashes. Regeneration runs in a fresh directory with networking denied;
only preceding receipts and the required comparison bundle are retained.
The requested receipt and artifact tree must be generated afresh. Earlier
product receipts remain unchanged. The equivalent local command, with the
matching generator and runtime, is:

```text
python -m law_history.reproduce_bodies BODY_PRODUCT_ID --report body-reproduction.json
```

This verifies a published representation; it does not establish legal validity
or replace a clean-fork publication rehearsal.

The observation workflow preserves existing representations during routine
catch-up. To apply an updated renderer to a retained observation, run it manually
with `regenerate_body_observation` set to that complete observation ID. It appends
a new representation and publishes it through the same checked path; previous
receipts and release bundles remain unchanged.

## Exporting the observed-history reader

```text
python -m law_history.reader_export --repository . --output reader-export
```

The destination must not exist. Export checks committed product receipts and
their actual Git publication proofs, pins the checkout, verifies artifact and
payload bytes, and emits a compact index with all retained versions. Qualified
HTML is copied exactly; rejected versions contain reasons and source links.
The current-law publisher uses this export for its observed-version reader.
Export neither changes the ledger nor requalifies older products with a newer
renderer. Its dates describe observations, not legal effective dates.

## Proposed later interpretations

`propose-claim request.json` appends a proposal bound to an exact act or
operation revision and verified evidence locations. `claim-history target.json`
returns the original unresolved claim and every later proposal for that subject.
Supersession preserves prior bytes. Repeating a request returns its first
recording, including its original recording time.

Every proposal remains ineligible for legal reconstruction: no interpretive
evidence method is registered yet. A supplied knowledge cutoff is a bounded
assertion, not proof that an interpretation was known historically. Publication
records actual Git creation separately. See [the claim contract](docs/CONTRACT.md#later-interpretation-proposals)
for request and storage details.

## Prior reader copies

The [prior reader archive](reader-archive/README.md) preserves 105 exact generated
Markdown copies recovered from ordinary source-repository Git history, including
[Viltloven](reader-archive/viltloven.md). Their original source observations and
legal dates are unknown. They are useful retained reader copies, kept outside the
raw-observation and qualified-text evidence paths.

## Complete parsed amendment evidence

The operation export preserves every producer-parsed act occurrence and operation,
including unknown targets, unknown operation types, zero-operation acts and empty
replacement text. It retains original fields and order, exact source/model
identities, source locations and raw commencement candidates. It does not assign
legal dates or apply amendments. Every initial temporal claim has unresolved status
and null legal bounds; the producer's normalized publication-date fallback is not
used as legal evidence.

```text
python -m law_history extract-operations --observation OBSERVATION_ID
python -m law_history operation-products
python -m law_history operations lov/2001-01-19-6 --product OPERATION_PRODUCT_ID
```

Use an accepted observation ID from `list`. Omitting `--observation` catches up
all accepted observations. For a fork, pass `--github-repository OWNER/REPOSITORY`
when extracting; the workflow uses its own repository automatically. The initial
full-corpus rehearsal preserved 39,208 acts and 99,964 operations. This is complete
relative to the producer's parsed inventory, not proof that its parser understood
every source instruction. Replacement structure and legal interpretation remain
separate work.

Git stores only `operation-products/<identity>/receipt.json`. Deterministic
compressed shards, their index and exact input-manifest/source-catalog proofs
are packaged in `operations.tar.gz`, published at the receipt's GitHub Release
URL. Receipts bind the full artifact inventory, source observation, generator
and runtime, parent product and bundle digest. Retrieving a product repopulates
ignored `.cache/operation-bundles/` and `.cache/operation-artifacts/` as needed,
then verifies all records against the accepted source inventory. Prior receipts
and release assets are never replaced. A new extraction identity can result from
a representation/runtime change without a legal change.

`publish` uploads and anonymously reads back each complete operation bundle before
committing its receipt. A separate `operation-publications/<identity>.json` binds
the product to its real Git creation commit and verified release download.
Publication requires the GitHub CLI and ordinary repository write credentials;
read-only retrieval requires neither. A failed publication can leave a draft or
published release for safe replay, without overwriting existing assets. Local
extraction alone is not public delivery.

An exclusive `.cache/operation-writer.lock` protects the extraction chain. After
a crash, confirm that the prior writer has stopped before removing that exact
lock. The accepted product directories are immutable and must not be edited to
repair a failed verification.

## Workflows

The [observation workflow](.github/workflows/observe.yml) runs daily at 04:30 UTC, on relevant changes to `main`, or manually. It enumerates all published producer observation releases so missed runs can catch up, accepts verified observations, and generates the bounded document-body and complete parsed-operation products. Set repository variable `SOURCE_REPOSITORY` to another public producer if needed; the default is `sondreskarsten/norwegian-laws`.

Publication uses this repository's ordinary `GITHUB_TOKEN`. It validates accepted observations and products, checks the expected remote parent, commits only verified additions, pushes normally, and reads back the remote Git objects. A separate `publications/<materialization-id>.json` receipt binds each product to its actual creation commit, tree, subtree and project commit dates. It does not supply legal dates. Replaying publication verifies existing receipts; a fresh checkout can complete missing receipts after an interrupted publication.

The equivalent local command is `python -m law_history publish --github-repository OWNER/REPOSITORY --report publication-readback.json`, from a full checkout of that repository's `main` with ordinary Git write access. The destination must match the remote. Concurrent changes cause a normal refusal; no force push or automatic rebase occurs. An unsuccessful local push preserves its commit for inspection. The next workflow run starts from a fresh checkout and can replay safely. Read both workflow artifacts and the committed receipts before calling a product delivered.

The [verification workflow](.github/workflows/verify.yml) runs the focused checks. Public delivery is evidenced by the committed products and independent readback, not by local checks alone.

Read the [reuse audit](docs/REUSE-AUDIT.md), [migration contract](docs/CONTRACT.md), and [verification evidence](docs/evidence/README.md). The audit pins the assessed producer source and distinguishes tests from legal claims. Run the focused failure/replay tests with:

```text
python -m unittest discover -s tests -v
```
