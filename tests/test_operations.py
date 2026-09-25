"""Focused preservation and binding checks; real six-case readback is recorded separately."""
import hashlib
import unittest

from law_history.operations import extract_act
from law_history.validation import canonical, value_hash


SOURCE = '''<!DOCTYPE html><html><body><header><dl>
<dd class="refid">lov/2001-04-06-11</dd><dd class="dateInForce">2001-04-01, 2001-04-06</dd>
</dl></header><main class="documentBody"><section id="part-1"><h2>I</h2>
<article class="defaultP">Del II skal lyde:</article>
<article class="legalP" id="replacement">Loven trer i kraft 1. april 2002.</article>
<article class="defaultP">§ 12 oppheves.</article>
<article class="defaultP">Någjeldende §§ 5-7 blir nye §§ 6-8.</article>
<article class="defaultP">Uavklart instruks.</article><article class="defaultP">Uavklart instruks.</article>
</section><section id="part-2"><h2>II</h2>
<article class="legalP" id="commencement">Endringen under I trer i kraft straks.</article>
</section></main></body></html>'''.encode()


def evidence(*, raw=SOURCE, operations=True, observed="2026-09-25T12:00:00+00:00", reorder=False):
    """Synthetic accepted-input boundary; no producer parser or filesystem access."""
    record = {"refid": "lov/2001-04-06-11", "filename": "source.xml", "title": "Evidence fixture",
              "short_title": "", "date_in_force": "2001-04-01, 2001-04-06", "date_published": "2001-04-06",
              "ministry": "", "changes_to": [], "misc_info": "", "journal_number": "",
              "amendments": [
                  {"change_type": "repeal", "target": "§ 12 o", "instruction": "§ 12 oppheves.",
                   "new_text": "", "target_law": "lov/1974-12-20-73"},
                  {"change_type": "unknown", "target": "§ 5-7 b", "instruction": "Någjeldende §§ 5-7 blir nye §§ 6-8.",
                   "new_text": "", "target_law": ""},
                  {"change_type": "unknown", "target": "", "instruction": "Uavklart instruks.",
                   "new_text": "", "target_law": ""},
              ] if operations else []}
    if reorder:
        record["amendments"].reverse()
    archive_sha = "a" * 64
    member_sha = hashlib.sha256(raw).hexdigest()
    occurrence = value_hash([0, archive_sha, 0, "test/source.xml", member_sha, "amendment_acts"])
    member = {"archive_ordinal": 0, "archive_sha256": archive_sha, "role": "amendment_acts",
              "member_ordinal": 0, "member_path": "test/source.xml", "member_type": "file",
              "member_size_bytes": len(raw), "member_sha256": member_sha, "parse_status": "parsed",
              "refid": record["refid"], "parsed_occurrence_ordinal": 0, "parsed_model_sha256": value_hash(record),
              "source_occurrence_id": occurrence}
    envelope = {"schema_version": "parsed-amendment-acts-v1", "source_occurrence_id": occurrence,
                "parsed_occurrence_ordinal": 0, "record": record,
                "amendment_occurrences": [{"ordinal": i, "target_status": "identified" if op["target_law"] else "unresolved",
                    "operation_status": "unresolved" if op["change_type"] == "unknown" else "identified"}
                    for i, op in enumerate(record["amendments"])],
                "legal_valid_time": {"status": "unresolved", "date": None},
                "fidelity": "lossless_relative_to_parsed_model", "source_structure_status": "not_verified"}
    archive = {"archive_ordinal": 0, "archive_sha256": archive_sha, "role": "amendment_acts",
               "raw_path": f"raw/{archive_sha}.tar.bz2", "observed_at": observed, "retrieved_at": None,
               "retrieval_time_status": "unknown", "historical_knowledge_time_status": "unknown",
               "source_last_modified": "2001-04-07", "source_url": "https://example.test/source"}
    source = canonical({"schema_version": "lovdata-source-evidence-v1", "archives": [archive],
                        "knowledge_cutoff": observed, "knowledge_cutoff_basis": "local_archive_observation",
                        "historical_knowledge_time_status": "unknown", "parser_identity": {"fixture": True},
                        "parser_runtime": {"fixture": True}}, newline=True)
    manifest = canonical({"version": 4, "evidence": {"parsed_amendments": "parsed-amendment-acts.v1.jsonl",
                         "observations": "source-observations.json"}, "artifact_hashes": {
                         "parsed-amendment-acts.v1.jsonl": hashlib.sha256(canonical(envelope, newline=True)).hexdigest(),
                         "source-observations.json": hashlib.sha256(source).hexdigest(), archive["raw_path"]: archive_sha}}, newline=True)
    receipt = {"version": 1, "contract": "lovdata-observation-release-v1", "repository": "fixture/evidence",
               "source_sha": "b" * 40, "snapshot_version": 4, "snapshot_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
               "bundle": {"name": "snapshot.tar.gz", "sha256": "c" * 64, "bytes": 100}, "member_count": 4,
               "data_attribution": {"provider": "Lovdata", "license": "NLOD 2.0", "license_url": "https://data.norge.no/nlod/no/2.0"},
               "interpretation": "Synthetic boundary fixture; no upstream authenticity claim"}
    identity = hashlib.sha256(canonical(receipt, newline=True)).hexdigest()
    receipt.update(observation_id=identity, release_tag="observation-" + identity)
    base = f'https://github.com/fixture/evidence/releases/download/{receipt["release_tag"]}/'
    receipt["bundle"]["url"] = base + "snapshot.tar.gz"
    receipt["receipt_url"] = base + "evidence.json"
    return {"envelope": envelope, "raw_xml": raw, "member": member, "receipt": receipt,
            "manifest_bytes": manifest, "source_observation_bytes": source}


class OperationTests(unittest.TestCase):
    def test_keeps_every_original_operation_without_promoting_candidates(self):
        inputs = evidence()
        output = extract_act(**inputs)
        self.assertEqual(output["act"]["producer_envelope"], inputs["envelope"])
        self.assertEqual([r["producer_record"] for r in output["operations"]], inputs["envelope"]["record"]["amendments"])
        self.assertEqual([r["operation_ordinal"] for r in output["operations"]], [0, 1, 2])
        repeal = output["operations"][0]
        self.assertEqual(repeal["producer_record"]["new_text"], "")
        self.assertEqual(repeal["target_resolution"]["candidate_expression"], "§ 12 o")
        self.assertEqual(repeal["producer_status"]["target_status"], "identified")
        self.assertEqual(repeal["target_resolution"]["status"], "unresolved")
        self.assertEqual(output["operations"][1]["producer_status"]["operation_status"], "unresolved")
        inputs["envelope"]["record"]["amendments"].clear()
        self.assertEqual(len(output["act"]["producer_envelope"]["record"]["amendments"]), 3)

    def test_zero_operations_still_has_act_claim_and_separate_clocks(self):
        output = extract_act(**evidence(operations=False), publication={
            "published_at": "2026-09-25T13:00:00+00:00", "evidence": "https://example.test/release/1"})
        self.assertEqual(output["operations"], [])
        self.assertEqual(len(output["claims"]), 1)
        claim = output["claims"][0]
        self.assertEqual(claim["subject"]["kind"], "act")
        self.assertEqual(claim["legal_valid_time"]["status"], "unresolved")
        self.assertIsNone(claim["legal_valid_time"]["from"])
        self.assertIsNone(claim["legal_valid_time"]["until"])
        self.assertEqual(claim["clocks"]["source_date_published"], "2001-04-06")
        self.assertEqual(claim["clocks"]["observed_at"], "2026-09-25T12:00:00+00:00")
        self.assertIsNone(claim["clocks"]["retrieved_at"])
        self.assertEqual(claim["clocks"]["release_publication"]["assertion"]["published_at"], "2026-09-25T13:00:00+00:00")
        self.assertEqual(claim["clocks"]["historical_knowledge_time"], {"status": "unknown", "at": None})

    def test_context_distinguishes_replacement_and_does_not_resolve_phrase_scope(self):
        output = extract_act(**evidence())
        expressions = {e["source"]["element_id"]: e for e in output["act"]["commencement_expressions"]}
        self.assertEqual(expressions["replacement"]["role"], "replacement_text_candidate")
        self.assertEqual(expressions["commencement"]["role"], "commencement_candidate")
        self.assertTrue(expressions["replacement"]["preceding_replacement_instruction"])
        self.assertEqual(expressions["commencement"]["context"]["ancestor_sections"][0]["headings"][0]["text"], "II")
        self.assertTrue(all(e["legal_scope_status"] == "unresolved" for e in expressions.values()))
        self.assertTrue(all(c["expression_scope_assignment"] == "unresolved" for c in output["claims"]))

    def test_duplicate_instruction_does_not_choose_arbitrary_source_node(self):
        output = extract_act(**evidence())
        self.assertEqual(output["operations"][0]["source_alignment"]["status"], "unique_text_match")
        duplicate = output["operations"][2]["source_alignment"]
        self.assertEqual(duplicate["status"], "unresolved")
        self.assertEqual(duplicate["reason"], "ambiguous_text_match")
        self.assertEqual(len(duplicate["candidates"]), 2)
        self.assertNotEqual(duplicate["candidates"][0]["path"], duplicate["candidates"][1]["path"])

    def test_replay_and_new_observation_preserve_occurrence_ids(self):
        first = extract_act(**evidence())
        self.assertEqual(first, extract_act(**evidence()))
        second = extract_act(**evidence(observed="2026-09-26T12:00:00+00:00"))
        self.assertEqual(first["act"]["act_id"], second["act"]["act_id"])
        self.assertEqual([r["operation_id"] for r in first["operations"]], [r["operation_id"] for r in second["operations"]])
        self.assertNotEqual(first["claims"][0]["claim_id"], second["claims"][0]["claim_id"])
        self.assertEqual(first["claims"][0]["supersedes"], [])

    def test_tampered_bindings_and_bad_original_ordinals_reject(self):
        mutations = [
            lambda v: v.update(raw_xml=v["raw_xml"] + b"changed"),
            lambda v: v.update(source_observation_bytes=v["source_observation_bytes"] + b" "),
            lambda v: v.update(manifest_bytes=v["manifest_bytes"] + b" "),
            lambda v: v["member"].update(member_path="other/source.xml"),
            lambda v: v["envelope"]["record"].update(date_in_force="2001-04-06"),
            lambda v: v["envelope"].update(parsed_occurrence_ordinal=1),
            lambda v: v["envelope"]["amendment_occurrences"][0].update(ordinal=False),
            lambda v: v["envelope"]["amendment_occurrences"][0].update(target_status="resolved"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                inputs = evidence(); mutation(inputs)
                with self.assertRaises(ValueError):
                    extract_act(**inputs)

    def test_parser_reordering_cannot_reuse_an_earlier_operation_identity(self):
        first = extract_act(**evidence())
        corrected = extract_act(**evidence(reorder=True))
        self.assertEqual(first["act"]["source_occurrence_id"], corrected["act"]["source_occurrence_id"])
        self.assertEqual(first["act"]["act_id"], corrected["act"]["act_id"])
        self.assertNotEqual(first["act"]["parsed_revision_id"], corrected["act"]["parsed_revision_id"])
        old = first["operations"][0]; new = corrected["operations"][0]
        self.assertEqual(old["operation_ordinal"], new["operation_ordinal"])
        self.assertNotEqual(old["producer_record"], new["producer_record"])
        self.assertNotEqual(old["operation_id"], new["operation_id"])
        self.assertEqual(first["claims"][1]["subject"]["id"], old["operation_id"])
        self.assertEqual(corrected["claims"][1]["subject"]["id"], new["operation_id"])
        self.assertNotEqual(first["claims"][0]["subject"]["parsed_revision_id"],
                            corrected["claims"][0]["subject"]["parsed_revision_id"])

    def test_matching_digests_do_not_hide_bad_xml_or_wrong_xml_refid(self):
        for raw in (SOURCE.replace(b"</section>", b"", 1),
                    SOURCE.replace(b"lov/2001-04-06-11", b"lov/2001-04-06-12")):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                extract_act(**evidence(raw=raw))


if __name__ == "__main__":
    unittest.main()
