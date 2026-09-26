# Historical source availability and remaining coverage

Checked 26 September 2026. [Download the complete machine-readable inventory](evidence/source-availability-20260926.json.gz).

The inventory verifies nine accepted observation catalogs and each included prior-reader copy. It covers **40,822 source/document identities**, preserving distinct bytes, source roles, duplicate occurrences, selection and exact observation/member locations. There are **5,875 current or previously current identities**: **4,284** have a matching Lovtidend source occurrence and **1,591** do not. Across all retained identities, **39,214** have Lovtidend occurrences; these include amending acts and are not all current laws. **17 removed documents** currently have only recovered generated Markdown in this ledger. Those copies are not primary evidence.

## Reproduce or inspect one document

```text
python -m law_history source-coverage
python -m law_history source-coverage lov/1814-05-17
python -m law_history source-coverage forskrift/2022-12-21-2456 --known-at 2026-09-26T04:00:00Z
```

The cutoff is an accepted-source observation cutoff. It is not a legal date. Generated reader copies lack that knowledge-time evidence and are omitted from explicit cutoff queries. Every report carries input catalog and receipt hashes; changed accepted catalogs are rejected.

## Source classes and acquisition boundary

| Source | Retained/available evidence | Remaining qualification or acquisition |
|---|---|---|
| Current consolidated laws/regulations | Exact archived XML and observed source bodies | Proves observed content, not earlier legal validity. |
| Lovtidend 2001–2026 | Exact source occurrences in the accepted archives | Identify original enactment, amendments, commencement orders, corrections and repeals from the complete ordered source. A matching refid is only an original-text candidate. |
| Earlier enacted/amending text | Not included in the four archives currently listed by the public API | Locate and acquire older official publications; missing from this ledger does not mean globally unavailable. |
| Historical consolidated versions | Not exposed in the inspected public archive list | Lovdata describes historical versions in its Pro service; their existence does not establish public API access or a captured baseline. |
| Removed prior reader copies | Exact generated Markdown with Git provenance | Retrieve primary sources; do not treat the Markdown as an enactment or infer a repeal date. |

The [public API listing](https://api.lovdata.no/v1/publicData/list), captured in [this evidence file](evidence/lovdata-source-list-20260926.json), lists current laws, current central regulations, Lovtidend 2001–2025 and Lovtidend 2026. This limits the inspected feed, not all possible primary sources. [Lovdata's original-text explanation](https://lovdata.no/register/lover?sort=alpha&year=1980) identifies Lovtidend as the source for enacted wording. Its [historical-version documentation](https://hjelp.lovdata.no/article/120-historiske-versjoner-av-lover-og-paragrafer) describes Pro historical paragraphs from 1999 and links to older amendments. Neither substitutes for independently acquired source evidence.

## What remains before a legal-date answer

Every inventory row has separate unresolved requirements: qualification of original text and legal start; complete amendment-chain coverage; and scoped commencement/correction evidence. No baseline or legal interval is promoted by this command. Ordered replacement extraction, source acquisition outside the retained feed, and justified interpretation/replay remain active implementation work. Detailed gaps can be narrowed as primary evidence is acquired; they must not be relabelled inaccessible merely because support is unfinished.
