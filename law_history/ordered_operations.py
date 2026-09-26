"""Ordered raw amendment evidence layered over immutable v1 operation products.

Source trees are evidence, never executable HTML or resolved legal operations.
Every element/attribute/text run is retained in order; operation associations
remain candidates unless an exact raw instruction has a unique source match.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

from .operations import XML_PATH_VERSION, _xml_index, _is_block, _text, _classes
from .validation import canonical, require

VERSION = "history-ordered-amendment-evidence-v2"
_REPLACEMENT_FORMS = {"futureLegalArticle", "futureLegalP", "futureDefaultP", "futureNumberedLegalP"}


def ordered_evidence(record: dict, raw: bytes) -> dict:
    """Enrich a caller-verified v1 record using its exact retained XML member."""
    act = record["act"]
    require(record["contract"] == "history-operation-evidence-v1", "Expected verified v1 operation evidence")
    require(hashlib.sha256(raw).hexdigest() == act["source_member"]["member_sha256"],
            "Ordered amendment source digest mismatch")
    nodes, paths, parents = _xml_index(raw)
    mains = [n for n in nodes if n.tag == "main" and "documentBody" in _classes(n)]
    require(len(mains) == 1, "Exactly one ordered amendment body required")
    main = mains[0]
    body_nodes = set(main.iter())

    def tree(node):
        content = [node.text] if node.text else []
        for child in node:
            content.append(tree(child))
            if child.tail: content.append(child.tail)
        return {"tag": node.tag, "attributes": dict(node.attrib), "path": paths[node], "children": content}

    body = tree(main)
    by_path = {paths[n]: n for n in body_nodes}
    matched = set()
    operations = []
    for operation in record["operations"]:
        candidates = []
        for pointer in operation["source_alignment"]["candidates"]:
            require(pointer["member_sha256"] == act["source_member"]["member_sha256"]
                    and pointer["source_occurrence_id"] == act["source_occurrence_id"]
                    and pointer["path_version"] == XML_PATH_VERSION,
                    "Instruction pointer differs from retained member")
            node = by_path.get(pointer["path"])
            # Metadata matches outside main remain unresolved, not discarded.
            if node is None: continue
            matched.add(paths[node])
            siblings = list(parents[node]) if node in parents else []
            following = []
            for sibling in siblings[siblings.index(node) + 1:] if siblings else []:
                if not (_classes(sibling) & _REPLACEMENT_FORMS): break
                following.append(tree(sibling))
            candidates.append({"source": deepcopy(pointer), "instruction_tree": tree(node),
                               "following_replacement_trees": following,
                               "replacement_scope": "source_tagged_adjacent_candidates_not_resolved"})
        operations.append({"operation_id": operation["operation_id"],
                           "operation_ordinal": operation["operation_ordinal"],
                           "producer_record": deepcopy(operation["producer_record"]),
                           "source_alignment": deepcopy(operation["source_alignment"]),
                           "target_resolution": deepcopy(operation["target_resolution"]),
                           "instruction_candidates": candidates,
                           "legal_eligibility": False})
    # All source blocks remain available, including unmatched instructions and
    # acts for which the producer emitted no operations. No keyword filter.
    units = [{"path": paths[n], "tag": n.tag, "attributes": dict(n.attrib),
              "text": _text(n), "matched_by_parsed_operation": paths[n] in matched}
             for n in nodes if n in body_nodes and _is_block(n)]
    result = {"contract": VERSION, "act_id": act["act_id"], "refid": act["refid"],
              "source_occurrence_id": act["source_occurrence_id"],
              "member_sha256": act["source_member"]["member_sha256"],
              "observation_id": act["context"]["observation_id"],
              "path_version": XML_PATH_VERSION, "clocks": deepcopy(act["clocks"]),
              "body_tree": body, "source_units": units, "operations": operations,
              "coverage": {"body": "all_xml_elements_attributes_and_character_data_in_source_order",
                           "parsed_operations": len(operations), "source_units": len(units),
                           "unmatched_source_units": sum(not u["matched_by_parsed_operation"] for u in units),
                           "semantic_operation_completeness": "unresolved"}}
    result["evidence_id"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def show_ordered_operations(repository, refid, product_id=None):
    from .operation_products import show_operations
    from .ledger import raw_member
    original = show_operations(repository, refid, product_id)
    results = []
    for record in original["occurrences"]:
        raw = raw_member(repository, original["observation_id"], refid,
                         record["act"]["source_occurrence_id"])
        results.append(ordered_evidence(record, raw))
    return {**original, "contract": VERSION, "occurrences": results}
