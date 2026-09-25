"""Checked, append-only Git transport for accepted observed evidence.

Data and publication receipts are separate commits: a receipt can name the
actual data commit without making that commit's identity circular. No source
observation or legal date is used as a Git project timestamp.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from .ledger import _directory, list_observations, read_observation
from .materialize import materializations, read_materialization
from .validation import canonical, digest, file_hash, read_json, require

CONTRACT = "history-git-publication-v1"
_OBSERVATION_FILES = {"receipt.json", "observation.json", "members.jsonl", "source-observations.json"}


def _git(repository, *args, input=None, check=True):
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    # Git must use the actual project commit time, even in a caller environment
    # left over from the legacy historical exporter.
    environment.pop("GIT_AUTHOR_DATE", None)
    environment.pop("GIT_COMMITTER_DATE", None)
    try:
        result = subprocess.run(["git", "-C", str(repository), *args], input=input,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=environment, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Git {args[0]} could not complete: {exc}") from exc
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git {args[0]} failed ({result.returncode}): {detail}")
    return result


def _text(repository, *args):
    return _git(repository, *args).stdout.decode("utf-8").strip()


def _paths(data):
    return [part.decode("utf-8") for part in data.split(b"\0") if part]


def _remote_head(repository, remote, branch):
    rows = _text(repository, "ls-remote", "--refs", remote, f"refs/heads/{branch}").splitlines()
    require(len(rows) == 1, "Remote destination branch is missing or ambiguous")
    identity, name = rows[0].split("\t")
    require(name == f"refs/heads/{branch}" and re.fullmatch(r"[0-9a-f]{40,64}", identity),
            "Unexpected remote branch response")
    return identity


def _same_parent(repository, remote, branch):
    head = _text(repository, "rev-parse", "HEAD")
    require(_remote_head(repository, remote, branch) == head,
            "Remote branch differs from HEAD; reconcile the checkout before publication")
    return head


def _readback(repository, remote, branch, expected):
    _git(repository, "fetch", "--no-tags", remote, f"refs/heads/{branch}")
    fetched = _text(repository, "rev-parse", "FETCH_HEAD")
    require(_remote_head(repository, remote, branch) == fetched,
            "Remote branch changed during publication readback; retry from its current checkout")
    require(_git(repository, "merge-base", "--is-ancestor", expected, fetched, check=False).returncode == 0,
            "Published commit is not reachable from the fetched remote branch")
    return fetched


def _checked_files(repository):
    files = set()
    observations = {r["observation_id"]: r for r in list_observations(repository)}
    for identity in observations:
        read_observation(repository, identity)
        root = repository / "observations" / identity
        require({p.name for p in root.iterdir()} == _OBSERVATION_FILES,
                "Unexpected accepted-observation artifact")
        files.update(f"observations/{identity}/{name}" for name in _OBSERVATION_FILES)
    products = materializations(repository)
    for item in products:
        identity = item["materialization_id"]
        receipt = read_materialization(repository, identity)
        require(receipt["observation_id"] in observations,
                "Materialization references an unaccepted observation")
        files.update(f"materializations/{identity}/{name}"
                     for name in (*receipt["artifact_hashes"], "receipt.json"))
    return files, products


def _check_changes(repository, allowed):
    # HEAD comparison includes both staged and unstaged changes. Only new files
    # belonging to the verified inventories may enter a publication commit.
    changes = _paths(_git(repository, "diff", "--name-status", "--no-renames", "-z", "HEAD").stdout)
    require(len(changes) % 2 == 0, "Unexpected Git change inventory")
    for status, path in zip(changes[::2], changes[1::2]):
        require(status == "A" and path in allowed,
                f"Publication rejects tracked modifications or unrelated staged changes: {path}")


def _creation_receipt(repository, item, github_repository, branch):
    identity = item["materialization_id"]
    subtree = f"materializations/{identity}"
    path = subtree + "/receipt.json"
    commits = _text(repository, "log", "--format=%H", "--diff-filter=A", "HEAD", "--", path).splitlines()
    require(len(commits) == 1, "Materialization has no unique creation commit")
    commit = commits[0]
    values = _text(repository, "show", "-s", "--format=%H%n%T%n%P%n%aI%n%cI", commit).splitlines()
    require(len(values) == 5 and len(values[2].split()) == 1,
            "Materialization creation must have one checked Git parent")
    parent = values[2]
    require(_git(repository, "cat-file", "-e", f"{parent}:{subtree}", check=False).returncode != 0,
            "Materialization directory existed before its receipt creation")
    tree = _text(repository, "rev-parse", f"{commit}:{subtree}")
    require(tree == _text(repository, "rev-parse", f"HEAD:{subtree}"),
            "Committed materialization was changed after its creation")
    # Compare every committed blob, not just the receipt or checkout's hashes.
    names = _paths(_git(repository, "ls-tree", "-r", "--name-only", "-z", commit, "--", subtree).stdout)
    require(set(names) == {subtree + "/" + name for name in (*item["artifact_hashes"], "receipt.json")},
            "Creation commit has a different materialization inventory")
    for name in names:
        require(_git(repository, "show", f"{commit}:{name}").stdout == (repository / name).read_bytes(),
                "Committed materialization bytes differ from the validated product")
    return {"contract": CONTRACT, "materialization_id": identity,
            "materialization_receipt_sha256": file_hash(repository / path),
            "observation_id": item["observation_id"], "github_repository": github_repository,
            "branch": branch, "creation_commit": commit, "creation_tree": values[1],
            "materialization_tree": tree, "expected_git_parent": parent,
            "project_author_date": values[3], "project_committer_date": values[4],
            "git_date_basis": "actual_project_commit_dates_not_legal_or_source_observation_dates",
            "remote_verification": "creation_commit_reachable_from_fetched_destination_branch",
            "creation_commit_url": f"https://github.com/{github_repository}/commit/{commit}",
            "materialization_url": f"https://github.com/{github_repository}/tree/{commit}/{subtree}"}


def _existing_publications(repository, products, github_repository, branch):
    directory = repository / "publications"
    if not directory.exists():
        return set()
    require(directory.is_dir() and not directory.is_symlink()
            and not getattr(directory, "is_junction", lambda: False)(), "Linked publication directory")
    items = {item["materialization_id"]: item for item in products}
    paths = set()
    for path in directory.iterdir():
        require(path.is_file() and not path.is_symlink() and path.suffix == ".json"
                and digest(path.stem) and path.stem in items, "Unexpected publication receipt")
        expected = _creation_receipt(repository, items[path.stem], github_repository, branch)
        require(read_json(path) == expected and path.read_bytes() == canonical(expected, newline=True),
                "Publication receipt changed or has incompatible provenance")
        paths.add(path.relative_to(repository).as_posix())
    return paths


def _commit(repository, paths, parent, message):
    require(_text(repository, "rev-parse", "HEAD") == parent, "Local Git parent changed")
    _git(repository, "add", "--pathspec-from-file=-", "--pathspec-file-nul",
         input=b"\0".join(path.encode("utf-8") for path in sorted(paths)) + b"\0")
    staged = set(_paths(_git(repository, "diff", "--cached", "--name-only", "-z").stdout))
    require(staged == set(paths), "Staged publication inventory changed")
    for path in paths:
        require(_git(repository, "show", ":" + path).stdout == (repository / path).read_bytes(),
                "Git attributes or filters changed accepted artifact bytes")
    _git(repository, "commit", "-m", message)
    commit = _text(repository, "rev-parse", "HEAD")
    require(_text(repository, "show", "-s", "--format=%P", commit) == parent,
            "Publication commit has an unexpected parent")
    changes = _paths(_git(repository, "diff", "--name-status", "--no-renames", "-z", parent, commit).stdout)
    require(set(changes[1::2]) == set(paths) and all(s == "A" for s in changes[::2]),
            "Publication commit is not the expected append-only addition")
    for path in paths:
        require(_git(repository, "show", f"{commit}:{path}").stdout == (repository / path).read_bytes(),
                "Committed artifact bytes changed")
    return commit


def _push(repository, remote, branch, commit):
    _git(repository, "push", "--no-force", "--no-follow-tags", remote, f"{commit}:refs/heads/{branch}")
    return _readback(repository, remote, branch, commit)


def _destination(repository, url, github_repository):
    # Local remotes support offline verification. Network publication is limited
    # to the named public GitHub project; receipts must not name another repo.
    if Path(url).is_absolute() or (repository / url).is_dir():
        require(Path(url).is_dir() if Path(url).is_absolute() else (repository / url).is_dir(),
                "Local Git destination is missing")
        return
    if url.startswith("git@github.com:"):
        project = url[len("git@github.com:"):]
    else:
        parsed = urlsplit(url)
        require(parsed.scheme in ("https", "ssh") and parsed.hostname == "github.com"
                and not parsed.query and not parsed.fragment, "Expected a public GitHub destination")
        project = parsed.path.lstrip("/")
    require(project.removesuffix(".git").rstrip("/").lower() == github_repository.lower(),
            "Git remote does not match the publication's GitHub repository identity")


def _write_receipt(repository, path, receipt):
    _directory(path.parent)
    cache = repository / ".cache"
    _directory(cache)
    with tempfile.TemporaryDirectory(prefix="publication-", dir=cache) as temporary:
        staged = Path(temporary) / "receipt.json"
        staged.write_bytes(canonical(receipt, newline=True))
        # Exclusive atomic installation: interruption cannot leave partial JSON,
        # and a concurrent publisher cannot overwrite an existing receipt.
        try:
            os.link(staged, path)
        except FileExistsError:
            require(path.read_bytes() == staged.read_bytes(), "Concurrent publication receipt conflict")


def publish(repository: Path, remote="origin", branch="main",
            github_repository="sondreskarsten/norwegian-laws-history") -> dict:
    """Publish validated additions and separate immutable creation receipts.

    Requires a full-history checkout whose HEAD equals the existing destination
    branch. Failures preserve local commits/files for inspection. A fresh checkout
    after a pushed data commit safely completes missing publication receipts.
    """
    repository = Path(repository).absolute()
    for path in (repository, *repository.parents):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(),
                "Linked publication checkout")
    require(Path(_text(repository, "rev-parse", "--show-toplevel")).resolve() == repository.resolve(),
            "Publication requires the repository root")
    require(_text(repository, "rev-parse", "--is-shallow-repository") == "false", "Full Git history is required")
    require(isinstance(remote, str) and remote in _text(repository, "remote").splitlines(), "Unknown Git remote")
    require(isinstance(branch, str) and _git(repository, "check-ref-format", f"refs/heads/{branch}", check=False).returncode == 0,
            "Invalid destination branch")
    require(isinstance(github_repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository),
            "Invalid GitHub repository identity")
    fetch_urls = _text(repository, "remote", "get-url", "--all", remote).splitlines()
    push_urls = _text(repository, "remote", "get-url", "--push", "--all", remote).splitlines()
    require(len(fetch_urls) == len(push_urls) == 1 and fetch_urls == push_urls,
            "Publication requires one identical fetch/push destination")
    _destination(repository, push_urls[0], github_repository)
    mirror = _git(repository, "config", "--bool", "--get", f"remote.{remote}.mirror", check=False)
    require(mirror.stdout.strip() != b"true", "Mirror remotes are not supported")
    data_files, products = _checked_files(repository)
    publication_files = _existing_publications(repository, products, github_repository, branch)
    _check_changes(repository, data_files | publication_files)
    head = _same_parent(repository, remote, branch)
    tracked = set(_paths(_git(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD").stdout))
    additions = data_files - tracked
    data_commit = publication_commit = None
    if additions:
        data_commit = _commit(repository, additions, head, "Publish accepted observations and materializations")
        head = _push(repository, remote, branch, data_commit)
    else:
        head = _readback(repository, remote, branch, head)
    # This second phase is independently recoverable after the data push.
    receipts = []
    for item in products:
        receipt = _creation_receipt(repository, item, github_repository, branch)
        receipts.append(receipt)
        path = repository / "publications" / (item["materialization_id"] + ".json")
        if not path.exists():
            _write_receipt(repository, path, receipt)
        publication_files.add(path.relative_to(repository).as_posix())
    _check_changes(repository, publication_files)
    tracked = set(_paths(_git(repository, "ls-tree", "-r", "--name-only", "-z", "HEAD").stdout))
    additions = publication_files - tracked
    if additions:
        parent = _same_parent(repository, remote, branch)
        publication_commit = _commit(repository, additions, parent, "Record verified materialization Git publication")
        head = _push(repository, remote, branch, publication_commit)
    return {"status": "published" if data_commit or publication_commit else "already_published",
            "remote": remote, "branch": branch, "remote_head": head,
            "data_commit": data_commit, "publication_commit": publication_commit,
            "publication_count": len(receipts), "publications": receipts}
