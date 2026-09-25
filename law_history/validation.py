"""Validate the release/evidence contracts independently using the standard library.

Integrity means the objects agree with their receipt. It is not an upstream
signature, a parser-fidelity proof, or verification of legal commencement.
"""
from __future__ import annotations

from contextlib import closing, ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tarfile

ROLES = ("laws", "forskrifter", "amendment_acts")
EVIDENCE_FILES = {"observations": "source-observations.json", "members": "source-members.jsonl",
                  "parsed_amendments": "parsed-amendment-acts.v1.jsonl"}
ACT_FIELDS = {"refid", "filename", "title", "short_title", "date_in_force", "date_published",
              "ministry", "changes_to", "amendments", "misc_info", "journal_number"}
AMENDMENT_FIELDS = {"change_type", "target", "instruction", "new_text", "target_law"}
CONTENT_CONTRACTS = {
    ("legacy-paragraphs-v1", "law-markdown-v1"),
    ("ordered-paragraph-blocks-v1", "law-markdown-ordered-html-v1"),
    ("ordered-law-containers-v1", "law-markdown-ordered-containers-v1"),
}


def require(condition, message: str):
    if not condition:
        raise ValueError(message)


def canonical(value, *, newline=False) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + ("\n" if newline else "")).encode("utf-8")


def value_hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def count(value):
    return type(value) is int and value >= 0


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(data):
    return json.loads(data, object_pairs_hook=_object,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"Invalid JSON {token}")))


def read_json(path: Path):
    return loads(path.read_bytes())


def jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = loads(line)
            require(isinstance(row, dict), f"Expected JSON object in {path.name}")
            yield row


def safe_name(name: str) -> str:
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            f"Unsafe artifact path: {name!r}")
    parts = PurePosixPath(name).parts
    require(not name.startswith("/") and name == "/".join(parts), f"Noncanonical artifact path: {name}")
    for part in parts:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) is not None
                and not part.endswith(".") and part.split(".")[0].upper() not in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))},
                f"Unsafe artifact component: {part}")
    return name


def timestamp(value):
    require(isinstance(value, str), "Missing observation timestamp")
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() is not None, "Observation timestamp must include timezone")
    return parsed


def validate_receipt(receipt: dict) -> dict:
    require(isinstance(receipt, dict) and set(receipt) == {
        "version", "contract", "repository", "source_sha", "snapshot_version",
        "snapshot_manifest_sha256", "bundle", "member_count", "data_attribution", "interpretation",
        "observation_id", "release_tag", "receipt_url"}, "Unsupported release receipt fields")
    require(type(receipt["version"]) is int and receipt["version"] == 1
            and receipt["contract"] == "lovdata-observation-release-v1"
            and type(receipt["snapshot_version"]) is int and receipt["snapshot_version"] == 4,
            "Unsupported release/snapshot version")
    require(isinstance(receipt["repository"], str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", receipt["repository"]), "Invalid repository")
    require(isinstance(receipt["source_sha"], str) and re.fullmatch(r"[0-9a-f]{40}", receipt["source_sha"]), "Invalid source commit")
    require(digest(receipt["snapshot_manifest_sha256"]) and digest(receipt["observation_id"])
            and count(receipt["member_count"]) and receipt["member_count"] > 0, "Invalid release digest/count")
    bundle = receipt["bundle"]
    require(isinstance(bundle, dict) and set(bundle) == {"name", "sha256", "bytes", "url"}
            and bundle["name"] == "snapshot.tar.gz" and digest(bundle["sha256"])
            and count(bundle["bytes"]) and bundle["bytes"] > 0, "Invalid bundle descriptor")
    require(receipt["data_attribution"] == {"provider": "Lovdata", "license": "NLOD 2.0",
            "license_url": "https://data.norge.no/nlod/no/2.0"}
            and isinstance(receipt["interpretation"], str), "Unsupported source attribution")
    identity = {key: value for key, value in receipt.items() if key not in {"observation_id", "release_tag", "receipt_url"}}
    identity["bundle"] = {key: value for key, value in bundle.items() if key != "url"}
    require(hashlib.sha256(canonical(identity, newline=True)).hexdigest() == receipt["observation_id"], "Release observation identity mismatch")
    tag = "observation-" + receipt["observation_id"]
    base = f'https://github.com/{receipt["repository"]}/releases/download/{tag}/'
    require(receipt["release_tag"] == tag and receipt["receipt_url"] == base + "evidence.json"
            and bundle["url"] == base + "snapshot.tar.gz", "Release derived fields mismatch")
    return receipt


def unpack_bundle(bundle: Path, destination: Path, receipt: dict) -> set[str]:
    require(bundle.stat().st_size == receipt["bundle"]["bytes"]
            and file_hash(bundle) == receipt["bundle"]["sha256"], "Bundle size/digest mismatch")
    names, folded = set(), set()
    total = 0
    with tarfile.open(bundle, "r:gz") as archive:
        for member in archive:
            name = safe_name(member.name)
            require(member.isfile() and not member.issparse(), f"Bundle member is not a regular file: {name}")
            require(name not in names and name.casefold() not in folded, f"Duplicate bundle path: {name}")
            names.add(name); folded.add(name.casefold())
            total += member.size
            require(len(names) <= receipt["member_count"] and total <= 20 * 1024**3,
                    "Bundle exceeds declared member count or supported size")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
    require(len(names) == receipt["member_count"], "Bundle member count mismatch")
    require("manifest.json" in names and file_hash(destination / "manifest.json") == receipt["snapshot_manifest_sha256"], "Snapshot manifest digest mismatch")
    return names


def _database(root, manifest, selected):
    with closing(sqlite3.connect((root / "amendments.db").resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        conn.execute("PRAGMA trusted_schema=OFF")
        require(conn.execute("PRAGMA quick_check").fetchall() == [("ok",)], "SQLite integrity failure")
        for table, field in (("amendment_acts", "amendment_act_count"), ("amendments", "amendment_count")):
            kind = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
            require(kind == ("table",), f"Missing concrete SQLite table: {table}")
            require(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == manifest[field], f"SQLite {field} mismatch")
        require({r[0] for r in conn.execute("SELECT refid FROM amendment_acts")} == selected,
                "SQLite selected act membership mismatch")
        require(not conn.execute("SELECT 1 FROM amendments a LEFT JOIN amendment_acts p ON a.act_refid=p.refid WHERE p.refid IS NULL LIMIT 1").fetchone(), "Orphan SQLite amendment")
        require(not conn.execute("SELECT 1 FROM amendment_acts p LEFT JOIN amendments a ON p.refid=a.act_refid GROUP BY p.refid,p.amendment_count HAVING p.amendment_count IS NULL OR p.amendment_count != count(a.id) LIMIT 1").fetchone(), "SQLite parent amendment count mismatch")


def validate_content_order(model: dict, content_version: str) -> None:
    """Check reference coverage, not source fidelity or legal interpretation.

    Arrays remain the only content owners. A populated content_order is a
    permutation referencing every owned item once; missing/empty retains the
    previous grouping. Only the explicit container contract permits that field
    to change rendering order, including in nested sections.
    """
    root_fields = {"paragraph": "top_level_paragraphs", "remainder": "remainders",
                   "section": "sections", "article": "top_level_articles"}
    section_fields = {"preamble": "preamble", "article": "articles", "section": "subsections",
                      "footnote": "footnotes", "remainder": "remainders"}

    def container(node, fields):
        require(isinstance(node, dict), "Document/section container must be an object")
        require(all(isinstance(node.get(field, []), list) for field in fields.values()),
                "Container content fields must be arrays")
        refs = node.get("content_order", [])
        require(isinstance(refs, list), "Container content_order must be an array")
        if refs:
            require(content_version == "ordered-law-containers-v1",
                    "Populated content_order requires the container content contract")
            seen = set()
            for ref in refs:
                require(isinstance(ref, dict) and set(ref) == {"kind", "index"}
                        and isinstance(ref["kind"], str) and ref["kind"] in fields
                        and type(ref["index"]) is int, "Invalid container order reference")
                kind, index = ref["kind"], ref["index"]
                require(0 <= index < len(node.get(fields[kind], [])), "Container order index out of range")
                require((kind, index) not in seen, "Duplicate container order reference")
                seen.add((kind, index))
            expected = {(kind, i) for kind, field in fields.items() for i in range(len(node.get(field, [])))}
            require(seen == expected, "Container order must reference every item exactly once")
        for section in node.get(fields["section"], []):
            container(section, section_fields)

    container(model, root_fields)


def validate_snapshot(root: Path, names: set[str]) -> tuple[dict, dict, list[dict]]:
    try:
        with ExitStack() as streams:
            return _validate_snapshot(root, names, streams)
    except (KeyError, TypeError, AttributeError, sqlite3.Error, tarfile.TarError, UnicodeError) as exc:
        raise ValueError(f"Malformed snapshot evidence: {exc}") from exc


def _validate_snapshot(root: Path, names: set[str], streams) -> tuple[dict, dict, list[dict]]:
    manifest = read_json(root / "manifest.json")
    require(type(manifest.get("version")) is int and manifest["version"] == 4, "Only snapshot v4 is accepted")
    require((manifest.get("content_version"), manifest.get("formatter_version")) in CONTENT_CONTRACTS,
            "Unknown content/formatter contract")
    for field in ("law_count", "forskrift_count", "amendment_act_count", "amendment_count"):
        require(count(manifest.get(field)), f"Invalid {field}")
    hashes = manifest.get("artifact_hashes")
    require(isinstance(hashes, dict) and set(hashes) == names - {"manifest.json"}
            and all(digest(value) for value in hashes.values()), "Snapshot exact artifact inventory mismatch")
    for name, expected in hashes.items():
        require(file_hash(root / safe_name(name)) == expected, f"Artifact digest mismatch: {name}")
    descriptor = manifest.get("evidence")
    require(isinstance(descriptor, dict) and descriptor.get("version") == "lovdata-source-evidence-v1"
            and all(descriptor.get(key) == value for key, value in EVIDENCE_FILES.items()), "Unsupported evidence descriptor")
    for field in ("archive_count", "member_count", "parsed_amendment_count", "unresolved_member_count"):
        require(count(descriptor.get(field)), f"Invalid evidence {field}")
    parsed_counts = descriptor.get("parsed_occurrence_counts")
    duplicates = manifest.get("duplicate_counts")
    require(isinstance(parsed_counts, dict) and set(parsed_counts) == set(ROLES)
            and all(count(value) for value in parsed_counts.values()), "Invalid parsed occurrence counts")
    require(manifest.get("duplicate_policy") == "last-occurrence-wins" and isinstance(duplicates, dict)
            and set(duplicates) == set(ROLES) and all(count(value) for value in duplicates.values()), "Invalid duplicate policy/counts")
    observation = read_json(root / EVIDENCE_FILES["observations"])
    require(observation.get("schema_version") == "lovdata-source-evidence-v1"
            and observation.get("knowledge_cutoff_basis") == "local_archive_observation"
            and observation.get("historical_knowledge_time_status") == "unknown"
            and observation.get("structural_coverage_status") == "not_verified", "Unknown observation/time/structure semantics")
    parser = observation.get("parser_identity", {})
    files = parser.get("source_files")
    require(isinstance(parser.get("package_version"), str) and isinstance(files, dict)
            and set(files) == {"parser.py", "models.py", "evidence.py"}
            and all(digest(value) for value in files.values()) and parser.get("sha256") == value_hash(files), "Parser source identity mismatch")
    runtime = observation.get("parser_runtime", {})
    deps = runtime.get("dependencies")
    require(runtime.get("html_backend") == "html.parser"
            and all(isinstance(runtime.get(field), str) and runtime[field] for field in ("python_implementation", "python_version"))
            and isinstance(deps, dict) and set(deps) == {"beautifulsoup4", "soupsieve", "lxml"}
            and all(value is None or isinstance(value, str) and value for value in deps.values())
            and "unknown_dependency_version" in runtime and runtime["unknown_dependency_version"] is None, "Parser runtime identity missing")
    archives = observation.get("archives")
    require(isinstance(archives, list) and len(archives) == descriptor["archive_count"], "Archive count mismatch")
    rows = streams.enter_context(closing(jsonl(root / EVIDENCE_FILES["members"])))
    parsed = {kind: [] for kind in ROLES}
    all_members, raw_paths = [], set()
    for ordinal, archive in enumerate(archives):
        sha = archive.get("archive_sha256")
        require(archive.get("archive_ordinal") == ordinal and digest(sha)
                and archive.get("raw_path") == f"raw/{sha}.tar.bz2" and archive.get("role") in ROLES,
                "Archive identity/role mismatch")
        raw_path, role = archive["raw_path"], archive["role"]
        raw_paths.add(raw_path)
        require(hashes.get(raw_path) == sha and count(archive.get("size_bytes"))
                and (root / raw_path).stat().st_size == archive["size_bytes"], "Raw archive size/hash mismatch")
        timestamp(archive.get("observed_at"))
        require(archive.get("historical_knowledge_time_status") == "unknown", "Unknown historical knowledge-time status")
        if archive.get("retrieved_at") is None:
            require(archive.get("retrieval_time_status") == "unknown", "Invented retrieval time")
        else:
            timestamp(archive["retrieved_at"])
            require(archive.get("retrieval_time_status") == "recorded", "Retrieval-time status mismatch")
        prefixes = archive.get("prefixes")
        require(isinstance(prefixes, list) and (prefixes == [] if role != "amendment_acts" else
                bool(prefixes) and len(set(prefixes)) == len(prefixes) and all(p in ("nl-", "sf-") for p in prefixes)), "Invalid archive scope")
        archive_rows, member_count = [], 0
        with tarfile.open(root / raw_path, "r:bz2") as raw:
            for member_ordinal, member in enumerate(raw):
                row = next(rows, None)
                require(row is not None, "Missing member inventory row")
                checksum = None
                if member.isfile():
                    with raw.extractfile(member) as stream:
                        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                expected = {"archive_ordinal": ordinal, "archive_sha256": sha, "role": role,
                            "member_ordinal": member_ordinal, "member_path": member.name,
                            "member_type": "file" if member.isfile() else "directory" if member.isdir() else "other",
                            "member_size_bytes": member.size, "member_sha256": checksum}
                require(all(row.get(key) == value for key, value in expected.items()), "Raw member identity/order/hash mismatch")
                all_members.append(row); member_count += 1
                eligible = member.name.endswith(".xml") and (role != "amendment_acts" or PurePosixPath(member.name).name.startswith(tuple(prefixes)))
                status = row.get("parse_status")
                if eligible:
                    require(member.isfile() and status in {"parsed", "unresolved_missing_refid"}, "Invalid XML member disposition")
                else:
                    require(status == ("excluded_non_xml" if not member.name.endswith(".xml") else "excluded_prefix"), "Invalid excluded member disposition")
                if status == "parsed":
                    refid = row.get("refid")
                    require(isinstance(refid, str) and re.fullmatch(r"(?:lov|forskrift)/[A-Za-z0-9][A-Za-z0-9._-]*", refid)
                            and digest(row.get("parsed_model_sha256")), "Invalid parsed identity")
                    require(row.get("source_occurrence_id") == value_hash([ordinal, sha, member_ordinal, member.name, checksum, role]), "Source occurrence identity mismatch")
                    archive_rows.append(row)
                else:
                    require(all(row.get(field) is None for field in ("refid", "parsed_occurrence_ordinal", "parsed_model_sha256", "source_occurrence_id", "selected_output_path", "selected_output_sha256")) and row.get("selected") is False, "Unparsed member has output binding")
        require(member_count == archive.get("member_count") and len(archive_rows) == archive.get("parsed_occurrence_count"), "Archive member/parsed counts mismatch")
        if role == "amendment_acts":
            archive_rows.sort(key=lambda row: next(i for i, prefix in enumerate(prefixes) if PurePosixPath(row["member_path"]).name.startswith(prefix)))
        parsed[role].extend(archive_rows)
    require(next(rows, None) is None and len(all_members) == descriptor["member_count"], "Member inventory count mismatch")
    require(sum(row["parse_status"] == "unresolved_missing_refid" for row in all_members) == descriptor["unresolved_member_count"], "Unresolved member count mismatch")
    require(observation.get("knowledge_cutoff") == max((a["observed_at"] for a in archives), default=None), "Knowledge cutoff mismatch")
    if archives:
        cutoff = timestamp(observation["knowledge_cutoff"])
        require(all(timestamp(a["observed_at"]) <= cutoff for a in archives), "Knowledge cutoff precedes observation")
    allowed = {"amendments.db", *EVIDENCE_FILES.values(), *raw_paths}
    if "source-manifest.json" in hashes:
        sources = read_json(root / "source-manifest.json")
        require(isinstance(sources, list) and sources, "Invalid selected source manifest")
        source_names = []
        for source in sources:
            require(isinstance(source, dict) and set(source) == {"filename", "lastModified", "sizeBytes"}
                    and isinstance(source["filename"], str) and re.fullmatch(r"[A-Za-z0-9_.-]+", source["filename"])
                    and isinstance(source["lastModified"], str) and bool(source["lastModified"].strip())
                    and count(source["sizeBytes"]) and source["sizeBytes"] > 0, "Invalid selected source entry")
            source_names.append(source["filename"])
        require(source_names == sorted(set(source_names)), "Selected sources are not unique/sorted")
        allowed.add("source-manifest.json")
    selected_by_role = {}
    for role in ROLES:
        role_rows = parsed[role]
        last = {row["refid"]: i for i, row in enumerate(role_rows)}
        selected_by_role[role] = set(last)
        field = {"laws": "law_count", "forskrifter": "forskrift_count", "amendment_acts": "amendment_act_count"}[role]
        require(len(role_rows) == parsed_counts[role] and len(last) == manifest[field]
                and len(role_rows) - len(last) == duplicates[role], f"{role} selection counts mismatch")
        for i, row in enumerate(role_rows):
            chosen = i == last[row["refid"]]
            require(type(row.get("parsed_occurrence_ordinal")) is int and row["parsed_occurrence_ordinal"] == i
                    and type(row.get("selected")) is bool and row["selected"] == chosen, "Parsed ordering/selection mismatch")
            if chosen:
                name = "amendments.db" if role == "amendment_acts" else f"{role}/{row['refid'].replace('/', '-')}.json"
                require(row.get("selected_output_path") == name and row.get("selected_output_sha256") == hashes.get(name), "Selected output binding mismatch")
                if role != "amendment_acts":
                    model = read_json(root / name)
                    require(model.get("refid") == row["refid"] and row["refid"].startswith("lov/" if role == "laws" else "forskrift/")
                            and isinstance(model.get("title"), str) and model["title"].strip()
                            and value_hash(model) == row["parsed_model_sha256"], "Selected parsed document mismatch")
                    validate_content_order(model, manifest["content_version"])
                    allowed.add(name)
            else:
                require(row.get("selected_output_path") is None and row.get("selected_output_sha256") is None, "Unselected output binding")
    require(set(hashes) == allowed, "Unexpected/missing snapshot artifacts")
    _database(root, manifest, selected_by_role["amendment_acts"])
    acts = streams.enter_context(closing(jsonl(root / EVIDENCE_FILES["parsed_amendments"])))
    amendment_count = 0
    for member in parsed["amendment_acts"]:
        row = next(acts, None)
        require(row is not None and row.get("schema_version") == "parsed-amendment-acts-v1"
                and row.get("source_occurrence_id") == member["source_occurrence_id"]
                and row.get("parsed_occurrence_ordinal") == member["parsed_occurrence_ordinal"], "Parsed act occurrence mismatch")
        record = row.get("record")
        require(isinstance(record, dict) and set(record) == ACT_FIELDS and record.get("refid") == member["refid"]
                and value_hash(record) == member["parsed_model_sha256"], "Complete parsed act/model digest mismatch")
        require(all(isinstance(record[field], str) for field in ACT_FIELDS - {"changes_to", "amendments"})
                and isinstance(record["changes_to"], list) and all(isinstance(r, str) for r in record["changes_to"])
                and isinstance(record["amendments"], list), "Parsed act fields malformed")
        expected = []
        for i, amendment in enumerate(record["amendments"]):
            require(isinstance(amendment, dict) and set(amendment) == AMENDMENT_FIELDS
                    and all(isinstance(v, str) for v in amendment.values()), "Incomplete parsed amendment")
            expected.append({"ordinal": i, "target_status": "identified" if amendment["target_law"] else "unresolved",
                             "operation_status": "unresolved" if amendment["change_type"] == "unknown" else "identified"})
        require(row.get("amendment_occurrences") == expected
                and row.get("legal_valid_time") == {"status": "unresolved", "date": None}
                and row.get("fidelity") == "lossless_relative_to_parsed_model"
                and row.get("source_structure_status") == "not_verified", "Parsed act statuses/time mismatch")
        amendment_count += len(record["amendments"])
    require(next(acts, None) is None and amendment_count == descriptor["parsed_amendment_count"], "Parsed amendment inventory/count mismatch")
    return manifest, observation, all_members
