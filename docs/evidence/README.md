# Evidence inventory

## Public source delivery

[`public-consumer-readback.json`](public-consumer-readback.json) records independent unauthenticated retrieval of the real public observation `ccdbf3e45098076118bf9362b60d31b7a80dc1aab1dcc2e226a4aee58c92b596`, produced by `norwegian-laws@2d90a466a8ca3954494f82041409b39242c5c1f5`. A fresh non-editable installation of consumer commit `810d60b4174fe3feda7bea37ad4310b237cd404e` verified the 191,396,694-byte bundle, accepted its 4 archives and 45,114 members, replayed without changing ledger bytes or modification times, and retrieved exact Regnskapsloven and regulation XML. Both retrieved files matched their original archive members independently. Machine-specific paths are omitted; filenames identify local outputs, not files bundled into this repository.

The [public intake run](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36169832648) committed the observation as [`611153d`](https://github.com/sondreskarsten/norwegian-laws-history/commit/611153d93419437ba74a07ab07ce5067afabbbef). All four committed ledger files match the independent ingestion byte for byte. The completed [production replay job](https://github.com/sondreskarsten/norwegian-laws-history/actions/runs/36170157045/job/108187452240) reported `already_present`, found no new observations to commit, and made no commit.

The later ordered-container consumer support is merged at `99943ec03e1d9f4c5b73e7946f6af7bf09cb9f34`; its bounded local evidence is `container-order-validation.json`. The public fresh-install report remains pinned to `810d60b` and does not claim a full-corpus structural gate for the new contract. Canonical structure is still `not_verified`; legal validity is `unresolved`.

## Earlier audit and local rehearsals

`prior-reader-backfill.json` records 105 exact prior generated reader copies
(61 laws and 44 regulations), recovered from a pinned ordinary-main deletion.
Every staged copy matches both its original Git blob and SHA-256 identity;
metadata keeps unknown source observations and legal dates explicit. These are
derived Markdown copies, separate from qualified observed bodies and raw XML.

The bounded body qualification, deterministic materialization and checked Git
publication checks exercise rejection, replay, parent changes and interrupted
publication in disposable repositories. Public product delivery and real-source
reproduction are recorded separately; passing these checks alone does not
certify corpus-wide structure or historical legal correctness.

Audit source is `sondreskarsten/norwegian-laws@4f5bbf561208e436f488b086ebf34924cd435530`. The original audit used an archived copy of that Git object. Large copied source, temporary test trees and databases are deliberately excluded here.

- `issue1.json`, `pr11.json`, `pr12.json` and `history-tree.json`: fresh GitHub responses used for scope, reported delivery evidence and the README-only destination state.
- `pinned-tests.txt`: independent result, 42 passed, for loader `test_download.py`, `test_store.py`, `test_ordered_content.py` and publisher `test_ordered_paragraph_rendering.py`, using the pinned source directories on `PYTHONPATH`.
- `pinned-probes.json`: bounded order, date and display-projection results. `mixed-section-source.xml` and `mixed-section-rendered.md` retain the observed input/output. These are synthetic diagnostic fixtures, not legal source evidence.
- `reproduce-probes.py`: reruns those counterexamples against `--source-checkout PATH` pinned to that commit, creates a temporary minimal SQLite display fixture, and checks equality with the saved result. Run with Python and the pinned producer packages' test dependencies installed. The script checks the checkout commit; it does not download or mutate a repository.
- `consumer-validation.json`: independent full local v4 validation by this standard-library consumer; explicitly not a public release readback.
- `consumer-rehearsal.json`: local packaged-release ingestion, no-op replay, exact real XML retrieval and ambiguous-source rejection. The rehearsal receipt predates the committed producer extension and is not published or imported into this repository's observation ledger.
- `container-order-validation.json`: independent acceptance of the explicit container content/formatter pair from a producer v4 snapshot containing two real XML members in local subset archives. Ordering references are checked; structural fidelity and legal validity remain unverified/unresolved.
- `document-check.json`: local relative-link and pinned code-line bounds checks, not network availability or semantic review.

The archived-source tests can be repeated with `python -m pytest` and the four named files; use a unique temporary directory outside any implementation checkout. Those earlier scripts and outputs support their bounded findings only. They do not certify whole-corpus coverage, legal validity, current deployed-site state or the later v4 interface; public v4 ingestion and retrieval are covered separately above.
