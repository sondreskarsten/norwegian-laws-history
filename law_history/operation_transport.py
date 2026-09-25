"""Checked public release transport for operation artifacts kept outside Git.

The caller validates the operation receipt/source contract. This layer validates
the derived public destination, exact bundle bytes and complete artifact inventory.
It never replaces a release asset or moves a previously created release tag.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

from .ledger import _directory, _regular
from .validation import digest, file_hash, loads, require, safe_name


NAME = "operations.tar.gz"
_PROJECT = r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+"
_COMMIT = re.compile(r"[0-9a-f]{40}")


def _descriptor(receipt):
    require(isinstance(receipt, dict) and digest(receipt.get("operation_product_id")), "Invalid operation product identity")
    tag = "operations-" + receipt["operation_product_id"]
    require(receipt.get("release_tag") == tag, "Operation release tag differs from product identity")
    bundle = receipt.get("bundle")
    require(isinstance(bundle, dict) and set(bundle) == {"name", "sha256", "bytes", "url"}
            and bundle["name"] == NAME and digest(bundle["sha256"])
            and type(bundle["bytes"]) is int and bundle["bytes"] > 0, "Invalid operation bundle descriptor")
    url = bundle["url"]
    match = re.fullmatch(rf"https://github\.com/({_PROJECT})/releases/download/{tag}/operations\.tar\.gz", url) if isinstance(url, str) else None
    require(match is not None and match[1].split("/")[1] not in {".", ".."}, "Expected the exact public operation release URL")
    hashes = receipt.get("artifact_hashes")
    require(isinstance(hashes, dict) and bool(hashes), "Operation bundle has no artifact inventory")
    for name, checksum in hashes.items():
        require(safe_name(name) == name and name != "receipt.json" and digest(checksum), "Invalid operation bundle artifact")
    return match[1], tag, bundle, hashes


def _validate_bundle(path, receipt):
    _, _, bundle, hashes = _descriptor(receipt)
    _regular(path)
    require(path.stat().st_size == bundle["bytes"] and file_hash(path) == bundle["sha256"],
            "Operation bundle size or digest differs from receipt")
    seen = set()
    try:
        with tarfile.open(path, "r|gz") as archive:
            for member in archive:
                name = safe_name(member.name)
                require(member.isfile() and name in hashes and name not in seen,
                        "Operation bundle has linked, duplicate or undeclared members")
                checksum, size = hashlib.sha256(), 0
                with archive.extractfile(member) as incoming:
                    while chunk := incoming.read(1024 * 1024):
                        checksum.update(chunk); size += len(chunk)
                require(size == member.size and checksum.hexdigest() == hashes[name], "Operation bundle artifact bytes changed")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ValueError(f"Invalid operation artifact bundle: {exc}") from exc
    require(seen == set(hashes), "Operation bundle artifact inventory is incomplete")


def _download(path, receipt):
    _, _, bundle, _ = _descriptor(receipt)
    request = urllib.request.Request(bundle["url"], headers={"User-Agent": "norwegian-laws-history"})
    checksum, size = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(request, timeout=120) as incoming, path.open("xb") as output:
            while chunk := incoming.read(1024 * 1024):
                size += len(chunk)
                require(size <= bundle["bytes"], "Downloaded operation bundle exceeds declared size")
                checksum.update(chunk); output.write(chunk)
    except (OSError, EOFError) as exc:
        raise ValueError(f"Public operation bundle could not be downloaded: {exc}") from exc
    require(size == bundle["bytes"] and checksum.hexdigest() == bundle["sha256"], "Public operation bundle bytes differ from receipt")
    _validate_bundle(path, receipt)


def ensure_bundle(repository: Path, receipt: dict) -> Path:
    """Return a fully checked local cache, downloading anonymously if absent."""
    _, _, bundle, _ = _descriptor(receipt)
    cache = Path(repository).absolute() / ".cache/operation-bundles"
    _directory(cache)
    target = cache / (bundle["sha256"] + ".tar.gz")
    if target.exists():
        _validate_bundle(target, receipt)
        return target
    with tempfile.TemporaryDirectory(prefix="incoming-", dir=cache) as temporary:
        incoming = Path(temporary) / NAME
        _download(incoming, receipt)
        try:
            os.link(incoming, target)
        except FileExistsError:
            _validate_bundle(target, receipt)
    _validate_bundle(target, receipt)
    return target


def _gh(repository, *args, check=True):
    environment = os.environ.copy()
    environment["GH_HOST"] = "github.com"
    environment["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(["gh", *args], cwd=repository, env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"GitHub release command could not complete: {exc}") from exc
    if check and result.returncode:
        raise ValueError("GitHub release command failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    return result


def _api(repository, endpoint, *, missing=False):
    result = _gh(repository, "api", endpoint, "--hostname", "github.com", "--header", "Accept: application/vnd.github+json", check=False)
    try:
        value = loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        if result.returncode:
            raise ValueError("GitHub API request failed: " + result.stderr.decode("utf-8", errors="replace").strip()) from exc
        raise ValueError("GitHub API did not return valid JSON") from exc
    require(isinstance(value, dict), "GitHub API did not return an object")
    if result.returncode:
        if missing and str(value.get("status")) == "404":
            return None
        raise ValueError("GitHub API request failed: " + result.stderr.decode("utf-8", errors="replace").strip())
    return value


def _commit(repository, project, ref, *, missing=False):
    value = _api(repository, f"repos/{project}/commits/{ref}", missing=missing)
    if value is None: return None
    sha = value.get("sha")
    require(isinstance(sha, str) and _COMMIT.fullmatch(sha), "GitHub tag/commit did not resolve to a full commit")
    if _COMMIT.fullmatch(ref): require(sha == ref, "GitHub commit identity changed")
    return sha


def _release(repository, project, tag, *, missing=False):
    value = _api(repository, f"repos/{project}/releases/tags/{tag}", missing=missing)
    if value is None: return None
    require(value.get("tag_name") == tag and value.get("html_url") == f"https://github.com/{project}/releases/tag/{tag}"
            and type(value.get("draft")) is bool and isinstance(value.get("assets"), list), "Unexpected operation release identity")
    return value


def _assets(release, bundle, *, missing=False):
    assets = release["assets"]
    if not assets and missing: return False
    require(len(assets) == 1 and assets[0].get("name") == NAME, "Operation release asset inventory must contain only operations.tar.gz")
    asset = assets[0]
    require(type(asset.get("size")) is int and asset["size"] == bundle["bytes"]
            and asset.get("browser_download_url") == bundle["url"], "Operation release asset metadata differs from receipt")
    return True


def _target(repository, project, tag, release):
    target = _commit(repository, project, tag, missing=release["draft"])
    if target is None:
        # A draft created by gh may not have created its tag yet. Only an exact
        # original target SHA is safe to publish; never resolve a mutable branch.
        target = release.get("target_commitish")
        require(isinstance(target, str) and _COMMIT.fullmatch(target), "Draft operation release lacks an exact original target")
        _commit(repository, project, target)
    return target


def _reachable(repository, project, target, source_commit):
    if target != source_commit:
        comparison = _api(repository, f"repos/{project}/compare/{target}...{source_commit}")
        require(comparison.get("status") in {"ahead", "identical"}, "Original operation release target is not reachable from the supplied source commit")


def publish_bundle(repository: Path, receipt: dict, github_repository: str, source_commit: str) -> dict:
    """Publish once, or verify/recover the first release without replacing it.

    The caller supplies a committed, public source SHA. Existing release targets
    must remain ancestors of that SHA. Remote bytes are read back anonymously
    even when a locally verified cache already exists.
    """
    project, tag, bundle, _ = _descriptor(receipt)
    require(project == github_repository, "Operation release destination differs from requested GitHub repository")
    require(isinstance(source_commit, str) and _COMMIT.fullmatch(source_commit), "Expected an explicit full source commit")
    repository = Path(repository).absolute()
    local = ensure_bundle(repository, receipt)
    repo = _api(repository, f"repos/{project}")
    require(repo.get("full_name", "").lower() == project.lower() and repo.get("private") is False, "Operation artifacts require the requested public GitHub repository")
    _commit(repository, project, source_commit)
    release = _release(repository, project, tag, missing=True)
    existing = release is not None
    changed = False
    cache = repository / ".cache/operation-bundles"
    with tempfile.TemporaryDirectory(prefix="publish-", dir=cache) as temporary:
        work = Path(temporary)
        upload = work / NAME
        os.link(local, upload)
        if release is None:
            prior_tag = _commit(repository, project, tag, missing=True)
            require(prior_tag is None or prior_tag == source_commit, "Existing operation tag differs from the requested first target")
            notes = work / "notes.txt"
            notes.write_text("Preserved producer-parsed amendment acts and operations. Legal commencement and target scope remain unresolved. "
                             "This is not a reconstructed legal state.\n\n"
                             "Source: Lovdata public data, NLOD 2.0 (https://data.norge.no/nlod/no/2.0).\n"
                             f"Operation product: {receipt['operation_product_id']}\nBundle SHA-256: {bundle['sha256']}\n", encoding="utf-8")
            # gh creates a draft, uploads the asset, then publishes it. This also
            # works when the repository enforces immutable published releases.
            _gh(repository, "release", "create", tag, str(upload), "--repo", "github.com/" + project,
                "--target", source_commit, "--title", "Operation evidence " + receipt["operation_product_id"],
                "--notes-file", str(notes), "--latest=false")
            changed = True
            release = _release(repository, project, tag)
            target = _target(repository, project, tag, release)
            require(target == source_commit, "New operation release did not use the explicit source commit")
        else:
            target = _target(repository, project, tag, release)
            _reachable(repository, project, target, source_commit)
            if not _assets(release, bundle, missing=True):
                require(not release.get("immutable"), "An immutable published release is missing its required asset")
                _gh(repository, "release", "upload", tag, str(upload), "--repo", "github.com/" + project)
                changed = True
                release = _release(repository, project, tag)
        _assets(release, bundle)
        if release["draft"]:
            # Do not publish a draft's already uploaded asset until its actual
            # authenticated bytes agree. Public readback follows publication.
            draft_copy = work / "draft-readback.tar.gz"
            _gh(repository, "release", "download", tag, "--repo", "github.com/" + project,
                "--pattern", NAME, "--output", str(draft_copy))
            _validate_bundle(draft_copy, receipt)
            _gh(repository, "release", "edit", tag, "--repo", "github.com/" + project, "--draft=false", "--latest=false")
            changed = True
            release = _release(repository, project, tag)
        require(release["draft"] is False, "Operation release is not public")
        _assets(release, bundle)
        _download(work / "public-readback.tar.gz", receipt)
        final = _release(repository, project, tag)
        _assets(final, bundle)
        require(final["draft"] is False and _target(repository, project, tag, final) == target, "Operation release target changed during readback")
    return {"status": "published" if changed else "already_published", "reused_release": existing,
            "github_repository": project, "release_tag": tag, "release_url": final["html_url"],
            "target_commit": target, "target_reachable_from": source_commit,
            "name": NAME, "url": bundle["url"], "sha256": bundle["sha256"], "bytes": bundle["bytes"],
            "github_published_at": final.get("published_at"), "github_release_immutable": final.get("immutable") is True,
            "verification": "public_download_exact_bundle_and_artifact_hashes"}
