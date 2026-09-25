# Freeze a bounded ordered canonical content format

Depends on accepted evidence and coordinates with the structural verifier.

The current [ordered paragraph renderer](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/formatter.py#L43-L120) repairs paragraph interleaving, but [section/document grouping](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/formatter.py#L146-L221) still loses mixed order. Define `history-canonical-v1` for the initial pilot grammar before reusing rendering code.

Scope: specify ordered node/event structure, source bindings, accepted elements, meaningful whitespace/Unicode policy, markers, deterministic serialization and renderer identity. Preserve exact raw source separately. Keep duplicate language occurrences distinct; a selected display variant names its source occurrence and policy. Exclude run timestamps from canonical content identity.

Acceptance:

- Repeating the same evidence with the same implementation produces byte-identical canonical products and digests.
- The output is reverse-readable by the independent structural verifier, including hierarchy and sibling order.
- Unsupported source shape produces a quarantine record rather than silently flattened output.
- Exact producer/parser/canonicalizer versions and source evidence are recorded for every product.
- A format change requires a new contract version and an explicit `representation_change` report; it is not presented as a legal amendment.
- The tested Regnskapsloven paragraph case is preserved, and the mixed-section counterexample either passes under the new ordered model or is rejected.

Do not import generated legacy Markdown as canonical input or claim the new grammar covers the whole corpus.
