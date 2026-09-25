# Preserve unresolved legal time and operation evidence explicitly

Depends on the complete parsed-act evidence interface and accepted observation receipts.

The [current date resolver](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-loader/src/lovdata_loader/parser.py#L85-L120) substitutes publication for unknown or deferred commencement. The [display feed](https://github.com/sondreskarsten/norwegian-laws/blob/4f5bbf561208e436f488b086ebf34924cd435530/lovdata-publisher/src/lovdata_publisher/manifests.py#L117-L153) filters and truncates amendments. Neither is a legal-state authority.

Implement the minimal temporal/operation claim model from [CONTRACT.md](../CONTRACT.md#legal-valid-time-is-a-separate-claim). Preserve original act fields, operation order, target expressions and source identities. Initial legal validity is unresolved with null bounds and a reason. Keep publication, local observation, retrieval, historical knowledge uncertainty and legal-valid-time assertions distinct.

Acceptance:

- `Kongen bestemmer`, unknown text and multiple scoped commencement expressions survive without fabricated legal dates.
- Empty replacement text does not erase a repeal operation; unresolved targets remain visible.
- Every operation is keyed by act occurrence and original ordinal, with evidence pointers and explicit resolution status.
- Later interpretations append versioned claims at a recorded knowledge cutoff instead of overwriting raw evidence.
- Source disappearance is `not_present_in_observation`, not proof of repeal.
- No initial implementation applies amendments, creates legal intervals or seeds a historical baseline.

Future commencement resolution and reconstruction require separate evidence-backed issues. This issue establishes honest uncertainty and durable interfaces only.
