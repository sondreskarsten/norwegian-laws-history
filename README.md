# Norwegian laws: observed source history

This repository independently verifies published Lovdata evidence releases and records which source bytes were observed. It can show a document's observations and retrieve its exact archived XML. It does not reconstruct past legal states or infer commencement or repeal dates.

The Python consumer uses only the standard library (Python 3.11+). From this checkout:

```text
python -m pip install .
python -m law_history ingest https://github.com/sondreskarsten/norwegian-laws/releases/download/observation-ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596/evidence.json
python -m law_history list
python -m law_history show lov/1998-07-17-56
python -m law_history raw lov/1998-07-17-56 --observation ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596 --occurrence 8abce8ef66dc6bc48ebedd3bfa3b397f92b8222eeb1179e343dbf83be86509be --output regnskapsloven.xml
```

This example uses a real public receipt and a 191 MB source bundle. The observation is already accepted in this repository, so replay reports `already_present`; use `--repository PATH` before `ingest` for a separate ledger. The installed `law-history` command is equivalent to `python -m law_history`. For local ingestion, `snapshot.tar.gz` may sit beside `evidence.json`, or be supplied using `--bundle`. `raw --output` creates a new file and never overwrites one. For another document, obtain its observation and source occurrence IDs from `show`.

## Delivered public observation

On 25 September 2026, the [first public intake](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36169832648) accepted 4 archives and 45,114 source members in commit [`611153d`](https://github.com/sondreskarsten/norwegian-laws-history/commit/611153d93419437ba74a07ab07ce5067afabbbef). A fresh isolated consumer installation independently accepted the same public bundle, replayed it without changing ledger files, and retrieved Regnskapsloven and `forskrift/2026-09-18-1871` XML byte for byte from their original archive members. All four committed ledger files match that independent ingestion.

The [production replay](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36170157045) also returned `already_present` and created no commit. [Read the portable evidence report](docs/evidence/public-consumer-readback.json) for the pinned consumer/producer identities, source hashes, and verification scope. These results establish source delivery and retrieval, not historical legal correctness.

## Verification and limits

Before accepting anything, the consumer independently checks the release's derived identity and URLs, bundle size/digest, safe regular bundle members, exact snapshot-v4 artifact hashes and counts, every retained raw archive/member, selected document bindings, complete parsed amendment occurrences and SQLite consistency. It never imports the producer or publisher at runtime. Unsupported contracts or mismatches fail before an accepted observation is written.

The current consumer also accepts the explicit ordered-document-container contract, merged in [`99943ec`](https://github.com/sondreskarsten/norwegian-laws-history/commit/99943ec03e1d9f4c5b73e7946f6af7bf09cb9f34). Its [bounded local verification](docs/evidence/container-order-validation.json) is separate from the public observation readback above; neither promotes canonical legal text.

Accepted observations are immutable directories under `observations/<release-observation-id>/`. They contain the release receipt, original source-observation metadata, a member/refid catalog and an observation summary. Replaying an identical receipt is a no-op. A later observation adds a directory; it never erases earlier sources. `show` reports `not_present_in_observation` only for comparable selections. Changed selections report `scope_not_comparable`; neither makes a repeal claim.

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

## Prior reader copies

The [prior reader archive](reader-archive/README.md) preserves 105 exact generated
Markdown copies recovered from ordinary source-repository Git history, including
[Viltloven](reader-archive/viltloven.md). Their original source observations and
legal dates are unknown. They are useful retained reader copies, kept outside the
raw-observation and qualified-text evidence paths.

## Workflows

The [observation workflow](.github/workflows/observe.yml) runs daily at 04:30 UTC, on relevant changes to `main`, or manually. It enumerates all published producer observation releases so missed runs can catch up, accepts verified observations, and generates the bounded document-body products. Set repository variable `SOURCE_REPOSITORY` to another public producer if needed; the default is `sondreskarsten/norwegian-laws`.

Publication uses this repository's ordinary `GITHUB_TOKEN`. It validates accepted observations and products, checks the expected remote parent, commits only verified additions, pushes normally, and reads back the remote Git objects. A separate `publications/<materialization-id>.json` receipt binds each product to its actual creation commit, tree, subtree and project commit dates. It does not supply legal dates. Replaying publication verifies existing receipts; a fresh checkout can complete missing receipts after an interrupted publication.

The equivalent local command is `python -m law_history publish --github-repository OWNER/REPOSITORY --report publication-readback.json`, from a full checkout of that repository's `main` with ordinary Git write access. The destination must match the remote. Concurrent changes cause a normal refusal; no force push or automatic rebase occurs. An unsuccessful local push preserves its commit for inspection. The next workflow run starts from a fresh checkout and can replay safely. Read both workflow artifacts and the committed receipts before calling a product delivered.

The [verification workflow](.github/workflows/verify.yml) runs the focused checks. Public delivery is evidenced by the committed products and independent readback, not by local checks alone.

Read the [reuse audit](docs/REUSE-AUDIT.md), [migration contract](docs/CONTRACT.md), and [verification evidence](docs/evidence/README.md). The audit pins the assessed producer source and distinguishes tests from legal claims. Run the focused failure/replay tests with:

```text
python -m unittest discover -s tests -v
```
