"""Checked Git inventories for proposed claims; no legal interpretation is added."""
from pathlib import Path
import re

from .later_claims import (CONTRACT, REQUEST, METHOD, ELIGIBILITY, CUTOFF_BASIS,
                           _Evidence, _identity, _keys, _path, _request)
from .ledger import _regular
from .validation import canonical, digest, file_hash, read_json, require, timestamp


def _record(repository, path):
    """Validate immutable record/chain fields without loading exported evidence."""
    _regular(path)
    require(path.suffix == ".json" and digest(path.stem), "Unexpected claim artifact")
    record = read_json(path)
    _keys(record, ("contract", "claim_id", "request_id", "request", "target_binding", "evidence_bindings",
                   "recorded_at", "status", "reconstruction_eligibility", "knowledge_cutoff_basis"), "stored claim")
    core = {key: value for key, value in record.items() if key != "claim_id"}
    require(record["contract"] == CONTRACT and record["claim_id"] == path.stem == _identity(CONTRACT, core)
            and path.read_bytes() == canonical(record, newline=True), "Claim identity or canonical bytes changed")
    request = record["request"]
    _keys(request, ("contract", "target", "knowledge_cutoff", "supersedes", "method", "assertion", "evidence"), "claim request")
    require(request["contract"] == REQUEST and request["method"] == METHOD
            and record["request_id"] == _identity(REQUEST, request), "Changed proposal request identity or method")
    require(_path(repository, request["target"]) == path.parent, "Claim bucket differs from target")
    require(isinstance(request["supersedes"], list) and len(request["supersedes"]) == 1
            and digest(request["supersedes"][0]), "Proposal must supersede one exact claim")
    require(record["status"] == "proposed" and record["reconstruction_eligibility"] == ELIGIBILITY
            and record["knowledge_cutoff_basis"] == CUTOFF_BASIS, "Proposed claim cannot become eligible")
    require(timestamp(record["recorded_at"]) >= timestamp(request["knowledge_cutoff"]),
            "Claim cutoff is after actual recorded time")
    return record


def _committed_publication(repository, item):
    """Only exact committed creation/publication proofs permit source replay."""
    from .publication import _git
    path = repository / "claim-publications" / (item["claim_id"] + ".json")
    for part in (path.parent, *path.parent.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(), "Linked claim publication directory")
    if not path.exists(): return False
    _regular(path)
    receipt = read_json(path)
    expected = creation_receipt(repository, item, receipt["github_repository"], receipt["branch"])
    content = path.read_bytes()
    require(content == canonical(expected, newline=True), "Claim publication provenance changed")
    name = path.relative_to(repository).as_posix()
    committed = _git(repository, "cat-file", "blob", "HEAD:" + name, check=False)
    if committed.returncode: return False  # Interrupted receipt publication must still recheck source.
    require(committed.stdout == content, "Claim publication provenance changed after commit")
    return True


def _chain(records, binding, initial):
    entries = {record["claim_id"]: record for record in records}
    require(len(entries) == len(records) and len({r["request_id"] for r in records}) == len(records),
            "Repeated claim or proposal request identity")
    require(all(record["target_binding"] == binding for record in records), "Claim target binding changes within subject")
    ordered, parent = [], initial
    cutoff, recorded = timestamp(binding["knowledge_cutoff"]), None
    while len(ordered) < len(entries):
        children = [record for record in entries.values() if record["request"]["supersedes"] == [parent]]
        require(len(children) == 1, "Claim supersedes chain is disconnected, forked, or belongs to another subject")
        record = children[0]
        require(record not in ordered and timestamp(record["request"]["knowledge_cutoff"]) >= cutoff,
                "Claim cutoff regresses or chain is cyclic")
        require(recorded is None or timestamp(record["recorded_at"]) >= recorded, "Actual claim recording time regresses")
        ordered.append(record); parent = record["claim_id"]
        cutoff, recorded = timestamp(record["request"]["knowledge_cutoff"]), timestamp(record["recorded_at"])
    return ordered


def _retained_inventory(repository, files):
    """A missing committed prefix must not become a new apparent chain root."""
    from .publication import _git
    result = _git(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", "later-claims", check=False)
    if result.returncode:
        # A not-yet-published proposal store can be inspected outside Git;
        # committed publication proofs above independently require Git.
        return
    tracked = {path.decode("utf-8") for path in result.stdout.split(b"\0") if path}
    require(tracked <= files, "Committed claim inventory is missing retained records")


def checked_claims(repository: Path) -> tuple[set[str], list[dict]]:
    """Check published Git proofs cheaply; fully validate only new claim evidence.

    This publication replay path does not weaken the explicit claim-history
    audit, which continues to validate every cited source product.
    """
    root = repository / "later-claims"
    if not root.exists():
        _retained_inventory(repository, set())
        return set(), []
    require(root.is_dir() and not root.is_symlink()
            and not getattr(root, "is_junction", lambda: False)(), "Linked claim inventory")
    evidence = _Evidence(repository)
    files, items, identities = set(), [], set()
    for bucket in sorted(root.iterdir()):
        require(bucket.is_dir() and re.fullmatch(r"[0-9a-f]{2}", bucket.name) and not bucket.is_symlink()
                and not getattr(bucket, "is_junction", lambda: False)(), "Unexpected claim bucket directory")
        paths = sorted(bucket.iterdir())
        require(bool(paths), "Empty claim bucket inventory")
        targets = {}
        for path in paths:
            record = _record(repository, path)
            targets.setdefault(canonical(record["request"]["target"]), []).append(record)
        expected = set()
        for records in targets.values():
            binding, initial = None, None
            for record in records:
                item = {"claim_id": record["claim_id"], "path": (bucket / (record["claim_id"] + ".json")).relative_to(repository).as_posix(),
                        "record": record}
                if _committed_publication(repository, item): continue
                verified, first, references = _request(evidence, record["request"])
                require(verified == record["target_binding"] and references == record["evidence_bindings"],
                        "Stored claim subject/source/evidence binding changed")
                require(binding is None or binding == verified, "New claim target bindings disagree")
                require(initial is None or initial == first["claim_id"], "New claims belong to different initial subjects")
                binding, initial = verified, first["claim_id"]
            if binding is None:
                # Every record was already fully validated and published. Its
                # original source-derived root is retained in those exact Git
                # bytes; no old release has to remain online for a routine run.
                binding = records[0]["target_binding"]
                identities_in_chain = {record["claim_id"] for record in records}
                roots = [record["request"]["supersedes"][0] for record in records
                         if record["request"]["supersedes"][0] not in identities_in_chain]
                require(len(roots) == 1, "Published claim chain has no unique retained initial subject")
                initial = roots[0]
            history = _chain(records, binding, initial)
            expected.update(bucket / (record["claim_id"] + ".json") for record in history)
            for record in history:
                identity = record["claim_id"]
                require(identity not in identities, "Duplicate claim identity across subjects")
                identities.add(identity)
                path = bucket / (identity + ".json")
                name = path.relative_to(repository).as_posix()
                files.add(name)
                items.append({"claim_id": identity, "path": name, "record": record})
        require(set(paths) == expected, "Claim bucket inventory differs from verified histories")
    _retained_inventory(repository, files)
    return files, items


def creation_receipt(repository: Path, item: dict, github_repository: str, branch: str) -> dict:
    # Import here so the main publisher may call this boundary without a module cycle.
    from .publication import _git, _text
    path, record = item["path"], item["record"]
    commits = _text(repository, "log", "--format=%H", "--diff-filter=A", "HEAD", "--", path).splitlines()
    require(len(commits) == 1, "Claim has no unique Git creation commit")
    commit = commits[0]
    values = _text(repository, "show", "-s", "--format=%H%n%T%n%P%n%aI%n%cI", commit).splitlines()
    require(len(values) == 5 and len(values[2].split()) == 1, "Claim creation must have one checked Git parent")
    parent = values[2]
    require(_git(repository, "cat-file", "-e", f"{parent}:{path}", check=False).returncode != 0,
            "Claim existed before its creation commit")
    content = (repository / path).read_bytes()
    require(content == canonical(record, newline=True)
            and _git(repository, "cat-file", "blob", f"{commit}:{path}").stdout == content
            and _git(repository, "cat-file", "blob", f"HEAD:{path}").stdout == content,
            "Committed claim differs from its verified original bytes")
    return {"contract": "history-proposed-claim-git-publication-v1", "claim_id": record["claim_id"],
            "claim_path": path, "claim_sha256": file_hash(repository / path),
            "target": record["request"]["target"], "claim_status": "proposed",
            "reconstruction_eligibility": record["reconstruction_eligibility"],
            "knowledge_cutoff": record["request"]["knowledge_cutoff"], "recorded_at": record["recorded_at"],
            "github_repository": github_repository, "branch": branch,
            "creation_commit": commit, "creation_tree": values[1], "expected_git_parent": parent,
            "project_author_date": values[3], "project_committer_date": values[4],
            "git_date_basis": "actual_project_commit_dates_not_legal_or_source_observation_dates",
            "remote_verification": "creation_commit_reachable_from_fetched_destination_branch",
            "creation_commit_url": f"https://github.com/{github_repository}/commit/{commit}",
            "claim_url": f"https://github.com/{github_repository}/blob/{commit}/{path}"}


def existing_publications(repository: Path, claims: list[dict], github_repository: str, branch: str) -> set[str]:
    root = repository / "claim-publications"
    if not root.exists():
        return set()
    require(root.is_dir() and not root.is_symlink()
            and not getattr(root, "is_junction", lambda: False)(), "Linked claim publication directory")
    items = {item["claim_id"]: item for item in claims}
    paths = set()
    for path in root.iterdir():
        _regular(path)
        require(path.suffix == ".json" and path.stem in items, "Unexpected claim publication receipt")
        expected = creation_receipt(repository, items[path.stem], github_repository, branch)
        require(path.read_bytes() == canonical(expected, newline=True), "Claim publication provenance changed")
        paths.add(path.relative_to(repository).as_posix())
    return paths
