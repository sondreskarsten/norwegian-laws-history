# Evidence inventory

Audit source is `sondreskarsten/norwegian-laws@4f5bbf561208e436f488b086ebf34924cd435530`. The original audit used an archived copy of that Git object. Large copied source, temporary test trees and databases are deliberately excluded here.

- `issue1.json`, `pr11.json`, `pr12.json` and `history-tree.json`: fresh GitHub responses used for scope, reported delivery evidence and the README-only destination state.
- `pinned-tests.txt`: independent result, 42 passed, for loader `test_download.py`, `test_store.py`, `test_ordered_content.py` and publisher `test_ordered_paragraph_rendering.py`, using the pinned source directories on `PYTHONPATH`.
- `pinned-probes.json`: bounded order, date and display-projection results. `mixed-section-source.xml` and `mixed-section-rendered.md` retain the observed input/output. These are synthetic diagnostic fixtures, not legal source evidence.
- `reproduce-probes.py`: reruns those counterexamples against `--source-checkout PATH` pinned to that commit, creates a temporary minimal SQLite display fixture, and checks equality with the saved result. Run with Python and the pinned producer packages' test dependencies installed. The script checks the checkout commit; it does not download or mutate a repository.
- `consumer-validation.json`: independent full local v4 validation by this standard-library consumer; explicitly not a public release readback.
- `consumer-rehearsal.json`: local packaged-release ingestion, no-op replay, exact real XML retrieval and ambiguous-source rejection. The rehearsal receipt predates the committed producer extension and is not published or imported into this repository's observation ledger.
- `container-order-validation.json`: independent acceptance of the explicit container content/formatter pair from a producer v4 snapshot containing two real XML members in local subset archives. Ordering references are checked; structural fidelity and legal validity remain unverified/unresolved.
- `document-check.json`: local relative-link and pinned code-line bounds checks, not network availability or semantic review.

The archived-source tests can be repeated with `python -m pytest` and the four named files; use a unique temporary directory outside any implementation checkout. The scripts and outputs support the bounded findings only. They do not certify whole-corpus coverage, legal validity, current deployed-site state or the later v4 interface.
