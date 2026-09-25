# Gate canonical promotion with independent ordered source coverage

Depends on the evidence adapter and a declared pilot grammar from [CONTRACT.md](../CONTRACT.md#canonical-content-and-the-fail-closed-structural-gate).

The [existing coverage score](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/coverage.py#L18-L100) is insensitive to order. The saved [mixed-section probe](../evidence/pinned-probes.json) changes `ALPHA, BRAVO, CHARLIE` into `ALPHA, CHARLIE, BRAVO` while scoring 1.0. This blocks canonical history promotion.

Implement three independent traversals for a deliberately small supported grammar: immutable source → normalized ordered events, model → events, and canonical output → reverse-parsed events. Retain source paths/ordinals, legal hierarchy, markers and mixed child order. Account for every meaningful source occurrence; any explicitly ignored source chrome must use a versioned whitelist and remain visible in the report.

Acceptance:

- Exact event sequence/structure equality and zero unclassified remainder are required per document.
- The mixed-section reorder, dropped or duplicated clause, changed marker and unknown meaningful element fail closed with source locations.
- Supported real-source documents pass with artifact hashes, verifier version and explicit grammar recorded.
- Unsupported lists, tables, footnotes or other structures are quarantined until supported; a corpus threshold cannot hide them.
- Outcomes are `passed`, `failed` or `not_verified`; only `passed` permits canonical text promotion. Raw evidence remains available independently.

Do not infer legal commencement or add a general amendment engine. Retain token coverage as a diagnostic only.
