# Norwegian laws: observed source history

This repository independently verifies immutable Lovdata evidence releases and records which source bytes were observed. It can show a document's observations and retrieve its exact archived XML. It does not reconstruct past legal states or infer commencement or repeal dates.

The Python consumer uses only the standard library (Python 3.11+). From this checkout:

```text
python -m law_history ingest /path/to/evidence.json
python -m law_history ingest https://github.com/OWNER/REPOSITORY/releases/download/observation-ID/evidence.json
python -m law_history list
python -m law_history show lov/1998-07-17-56
python -m law_history raw lov/1998-07-17-56 --observation ID --occurrence SOURCE_OCCURRENCE_ID --output regnskapsloven.xml
```

The URL example is a template; replace it with an actual public producer receipt. For local ingestion, `snapshot.tar.gz` may sit beside `evidence.json`, or be supplied using `--bundle`. Use `--repository PATH` before the command to select another ledger directory. `raw --output` creates a new file and never overwrites one. If a refid has multiple source occurrences, pass `--occurrence SOURCE_OCCURRENCE_ID` from `show` to choose explicitly.

Before accepting anything, the consumer independently checks the release's derived identity and URLs, bundle size/digest, safe regular bundle members, exact snapshot-v4 artifact hashes and counts, every retained raw archive/member, selected document bindings, complete parsed amendment occurrences and SQLite consistency. It never imports the producer or publisher at runtime. Unsupported contracts or mismatches fail before an accepted observation is written.

Accepted observations are immutable directories under `observations/<release-observation-id>/`. They contain the release receipt, original source-observation metadata, a member/refid catalog and an observation summary. Replaying an identical receipt is a no-op. A later observation adds a directory; it never erases earlier sources. `show` reports `not_present_in_observation` only for comparable selections. Changed selections report `scope_not_comparable`; neither makes a repeal claim.

Large source bundles are retained in the ignored `.cache/bundles/` directory by digest. The public release URL remains in the ledger. If a bundle is absent from the cache, `raw` retrieves it from that URL and checks its digest again. A local-only rehearsal cannot be recovered from a nonexistent public URL; keep its bundle. A corrupted cache entry fails closed and can be removed before retrying. SHA-256 proves consistency with a receipt, not a source signature or permanent storage availability.

Every accepted observation currently reports canonical structure as `not_verified` and legal validity as `unresolved`. Parsing/rendering remain potentially lossy; observation timestamps are collector knowledge times. There is no amendment engine, canonical-law promotion, synthetic historical baseline, imported legacy history graph, or mandatory cloud/PAT credential. Public ingestion is read-only and unauthenticated; workflow publication is separate.

The [observation workflow](.github/workflows/observe.yml) runs daily at 04:30 UTC, on relevant changes to `main`, or manually. It enumerates all published producer observation releases so missed runs can catch up, accepts verified observations, and commits only new ledger files using this repository's ordinary `GITHUB_TOKEN`. Set repository variable `SOURCE_REPOSITORY` to another public producer if needed; the default is `sondreskarsten/norwegian-laws`. A concurrent Git change causes a normal push refusal, with replay on the next run. The [verification workflow](.github/workflows/verify.yml) runs the focused tests. A green local rehearsal does not claim either workflow has delivered a public observation.

Read the [reuse audit](docs/REUSE-AUDIT.md), [migration contract](docs/CONTRACT.md), and [verification evidence](docs/evidence/README.md). The audit pins the assessed producer source and distinguishes tests from legal claims. Run the focused failure/replay tests with:

```text
python -m unittest discover -s tests -v
```
