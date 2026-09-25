# Materialize accepted observations with deterministic trees and checked parents

Depends on the observation adapter. Canonical law output additionally depends on the structural verifier and canonicalization contract.

Reuse only bounded mechanics from the [sorted, byte-counted Git exporter](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/git_export.py#L119-L229). Do not reuse its [synthetic 2001 baseline](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/git_export.py#L351-L397) or force-pushed history refs.

Build a local deterministic tree/materialization receipt from accepted observation IDs, a knowledge cutoff, explicit artifact inventory and per-document gate results. Use project authorship and publication times. Bind final Git commit/tree in a separate publication receipt to avoid circular hashes. The publication workflow supplies transport and remote readback; this issue supplies the checked local contract.

Acceptance:

- Same evidence and versions yield identical semantic artifact bytes/tree; replaying the same accepted receipt is idempotent.
- Only structurally passed documents enter the canonical tree. Raw-only receipts are a valid initial product.
- Unresolved/quarantined items remain inventoried, and explicit deletions represent observation membership only.
- Unsafe paths, failed Git processes and unexpected parent changes fail before accepted publication state.
- No force push, fabricated historic Git dates, Lovdata author impersonation, legacy refs or synthetic baseline import.
- A formatter migration is labeled as representation change and preserves previous materialization identity.

Validate a small temporary repository and read back its intended tree. Workflow/cloud setup remains in the publication integration work.
