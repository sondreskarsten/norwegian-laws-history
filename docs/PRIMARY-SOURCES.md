# Supplemental primary-source evidence

Older evidence is obtainable beyond the four Lovdata API archives. [The acquisition report](evidence/older-primary-sources/REPORT.md) records 200 National Library volume links through UiO, 49 government PDF links, and actual retained samples. Missing ingestion/segmentation is implementation work, not a source-access limitation. Missing index links are not proof that a volume is unavailable.

The producer's `publish_primary_sources.py` packages the exact acquired files and retrieval manifest, then uses the existing append-only GitHub evidence transport. Its separate `primary-source-acquisition-release-v1` contract and `primary-source-…` tags keep these files distinct from parsed Lovdata observations. Existing assets are never overwritten; public assets are read back after publication. No blanket NLOD license is assigned to external sources.

The independent consumer command is:

```text
python -m law_history verify-primary RECEIPT_URL
python -m law_history verify-primary evidence.json --bundle snapshot.tar.gz
```

It verifies the content-addressed receipt, exact bundle, every source hash/size, retrieval clocks and complete artifact membership. It returns acquired evidence, not legally qualified text. Scans, OCR and later source-hosted printouts retain their separate provenance. This interface does not yet register these sources into document-level baseline/interval coverage.

The locally prepared first bundle contains 20 files plus its manifest, with two failed attempts preserved. Source-text qualification, whole-volume acquisition, segmentation and legal-time interpretation remain open. A real 1983 amendment/header versus commencement-order conflict is retained explicitly. The [public acquisition release](https://github.com/sondreskarsten/norwegian-laws/releases/tag/primary-source-066a4a3e8cfc83754c9295875841d010d550ff3978f60e9746fdcfe8cc0bb0c5) was independently downloaded and verified by a fresh Windows installation; see [readback evidence](evidence/primary-source-public-readback.json).
