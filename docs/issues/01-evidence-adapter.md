# Accept immutable producer observations without importing legacy history

Depends on the producer's merged, verified snapshot-v4 evidence schema and [CONTRACT.md](../CONTRACT.md#producer-handoff).

The [pinned v2/v3 snapshot writer](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/store.py#L186-L288) hashes generated products but does not provide complete archive/member provenance. Add a small standard-library history consumer for the finalized v4 artifacts. It must not import the publisher, SQLite projections or legacy history code.

Scope: read a local immutable evidence package; verify manifest version, all declared artifact bytes, safe relative paths, raw archives and every member/parsed-occurrence binding; write an immutable `history-observation-v1` receipt. Preserve duplicate paths/refids and unresolved/excluded dispositions. Use the independently recomputed release-receipt hash as observation identity; retain the producer source-observation artifact hash separately. Keep local observation time, retrieval time and historical knowledge-time uncertainty separate. No source acquisition, Git push, canonical law export or amendment application belongs here.

Acceptance:

- A real v4 package can be accepted and independently read back by digest; replay is idempotent.
- A missing, changed, extra-unaccounted or wrongly bound evidence artifact/member fails before an accepted receipt is created.
- Unknown versions and unsafe paths fail closed. A forged count does not replace reconciliation.
- Every parsed amendment occurrence, including unresolved targets and empty repeal text, remains addressable in original order.
- `structural_coverage_status = not_verified` permits raw observation acceptance only; no verified-text claim is emitted.
- Public-source verification works without custom credentials. No synthetic `law-history` input is accepted.

Use a small real-source package and a few targeted corruption probes; do not broaden this issue into whole-corpus parser repair.
