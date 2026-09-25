"""Offline checks for immutable operation release transport and recovery."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from law_history import operation_transport as transport


PROJECT = "sondreskarsten/norwegian-laws-history"
SOURCE = "a" * 40
PRIOR = "b" * 40


def bundle(files):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for name, content in sorted(files.items()):
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
    return output.getvalue()


class FakeGitHub:
    def __init__(self, receipt, content, *, target=SOURCE, existing=False, draft=False, assets=True):
        self.receipt, self.content = receipt, content
        self.target, self.existing, self.draft, self.assets = target, existing, draft, assets
        self.calls = []
        self.extra_assets = []
        self.compare_status = "ahead"
        self.api_error = None
        self.draft_content = content
        self.immutable = not draft

    def release(self):
        return {"tag_name": self.receipt["release_tag"], "target_commitish": self.target,
                "draft": self.draft, "prerelease": False, "immutable": self.immutable,
                "html_url": f'https://github.com/{PROJECT}/releases/tag/{self.receipt["release_tag"]}',
                "published_at": None if self.draft else "2026-09-25T12:00:00Z",
                "assets": ([{"name": "operations.tar.gz", "size": len(self.content),
                             "browser_download_url": self.receipt["bundle"]["url"]}] if self.assets else []) + self.extra_assets}

    def gh(self, repository, *args, check=True):
        self.calls.append(args)
        value, code = {}, 0
        if args[0] == "api":
            endpoint = args[1]
            if self.api_error and "/releases/tags/" in endpoint:
                code, value = 1, {"status": self.api_error, "message": "Controlled API error"}
            elif endpoint == f"repos/{PROJECT}":
                value = {"full_name": PROJECT, "private": False}
            elif "/releases/tags/" in endpoint:
                if self.existing: value = self.release()
                else: code, value = 1, {"status": "404", "message": "Not Found"}
            elif "/compare/" in endpoint:
                value = {"status": self.compare_status}
            elif endpoint.endswith("/git/ref/tags/" + self.receipt["release_tag"]):
                if self.existing and not self.draft:
                    value = {"ref": "refs/tags/" + self.receipt["release_tag"], "object": {"sha": self.target}}
                else: code, value = 1, {"status": "404", "message": "Not Found"}
            elif endpoint.endswith("/commits/" + self.receipt["release_tag"]):
                if self.existing and not self.draft: value = {"sha": self.target}
                else: code, value = 1, {"status": "422", "message": "No commit found for SHA: " + self.receipt["release_tag"]}
            elif "/commits/" in endpoint:
                value = {"sha": endpoint.rsplit("/", 1)[1]}
            else: raise AssertionError(args)
        elif args[:2] == ("release", "create"):
            assert "--target" in args and args[args.index("--target") + 1] == SOURCE
            assert "--latest=false" in args
            path = Path(args[3])
            assert path.name == "operations.tar.gz" and path.read_bytes() == self.content
            self.existing, self.assets, self.draft, self.target = True, True, False, SOURCE
        elif args[:2] == ("release", "upload"):
            assert "--clobber" not in args and Path(args[3]).read_bytes() == self.content
            self.assets = True
        elif args[:2] == ("release", "edit"):
            assert "--draft=false" in args and "--target" not in args
            self.draft = False
        elif args[:2] == ("release", "download"):
            Path(args[args.index("--output") + 1]).write_bytes(self.draft_content)
        else: raise AssertionError(args)
        response = subprocess.CompletedProcess(args, code, json.dumps(value).encode(), b"controlled error" if code else b"")
        if check and code: raise ValueError("Fake GitHub request failed")
        return response


class OperationTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="operation-transport-")
        self.repository = Path(self.temporary.name)
        self.files = {"index.jsonl.gz": b"index bytes", "acts/00000.jsonl.gz": b"exact gzip artifact bytes"}
        self.content = bundle(self.files)
        identity = "c" * 64
        tag = "operations-" + identity
        self.receipt = {"operation_product_id": identity, "release_tag": tag,
                        "artifact_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()},
                        "bundle": {"name": "operations.tar.gz", "sha256": hashlib.sha256(self.content).hexdigest(),
                                   "bytes": len(self.content), "url": f"https://github.com/{PROJECT}/releases/download/{tag}/operations.tar.gz"}}

    def tearDown(self):
        self.temporary.cleanup()

    def cache(self):
        target = self.repository / ".cache/operation-bundles" / (self.receipt["bundle"]["sha256"] + ".tar.gz")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.content)
        return target

    def download(self, content=None):
        expected = self.content if content is None else content
        def incoming(request, timeout):
            self.assertEqual(request.full_url, self.receipt["bundle"]["url"])
            self.assertNotIn("Authorization", request.headers)
            return io.BytesIO(expected)
        return patch.object(transport.urllib.request, "urlopen", side_effect=incoming)

    def test_download_cache_and_replay_validate_every_artifact(self):
        with self.download():
            path = transport.ensure_bundle(self.repository, self.receipt)
        self.assertEqual(path.read_bytes(), self.content)
        before = path.stat().st_mtime_ns
        with patch.object(transport.urllib.request, "urlopen", side_effect=AssertionError("cache replay downloaded")):
            self.assertEqual(transport.ensure_bundle(self.repository, self.receipt), path)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_corrupt_cache_and_download_fail_without_replacing_existing(self):
        path = self.cache()
        path.write_bytes(b"corrupt cache")
        with self.download(), self.assertRaises(ValueError):
            transport.ensure_bundle(self.repository, self.receipt)
        self.assertEqual(path.read_bytes(), b"corrupt cache")
        other = self.repository / "other"
        with self.download(b"corrupt remote"), self.assertRaises(ValueError):
            transport.ensure_bundle(other, self.receipt)
        self.assertFalse((other / ".cache/operation-bundles" / path.name).exists())

    def test_bundle_membership_and_artifact_hash_are_checked(self):
        for changed in ({"index.jsonl.gz": b"wrong"}, {**self.files, "receipt.json": b"must not be bundled"},
                        {**self.files, "../escape": b"unsafe"}):
            data = bundle(changed)
            receipt = deepcopy(self.receipt)
            receipt["bundle"].update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            with self.download(data), self.assertRaises(ValueError):
                transport.ensure_bundle(self.repository, receipt)

    def test_new_release_has_explicit_target_and_public_byte_readback(self):
        self.cache()
        fake = FakeGitHub(self.receipt, self.content)
        with patch.object(transport, "_gh", side_effect=fake.gh), self.download():
            result = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(result["target_commit"], SOURCE)
        self.assertEqual(result["sha256"], self.receipt["bundle"]["sha256"])
        self.assertEqual(result["status"], "published")
        self.assertEqual(len([c for c in fake.calls if c[:2] == ("release", "create")]), 1)

    def test_replay_preserves_prior_target_and_never_writes_existing_asset(self):
        self.cache()
        fake = FakeGitHub(self.receipt, self.content, target=PRIOR, existing=True)
        with patch.object(transport, "_gh", side_effect=fake.gh), self.download():
            result = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(result["target_commit"], PRIOR)
        self.assertEqual(result["status"], "already_published")
        self.assertFalse(any(c[0] == "release" for c in fake.calls))
        self.assertTrue(any(f"/compare/{PRIOR}...{SOURCE}" in c[1] for c in fake.calls))

    def test_interrupted_draft_can_add_only_missing_asset_then_publish(self):
        self.cache()
        fake = FakeGitHub(self.receipt, self.content, target=PRIOR, existing=True, draft=True, assets=False)
        with patch.object(transport, "_gh", side_effect=fake.gh), self.download():
            result = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(result["target_commit"], PRIOR)
        self.assertEqual([c[1] for c in fake.calls if c[0] == "release"], ["upload", "download", "edit"])

    def test_corrupt_existing_draft_asset_is_not_published_or_replaced(self):
        self.cache()
        fake = FakeGitHub(self.receipt, self.content, existing=True, draft=True)
        fake.draft_content = b"bad draft artifact"
        with patch.object(transport, "_gh", side_effect=fake.gh), self.download(), self.assertRaises(ValueError):
            transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertTrue(fake.draft)
        self.assertFalse(any(c[:2] in (("release", "upload"), ("release", "edit")) for c in fake.calls))

    def test_interrupted_public_release_can_add_missing_asset_without_retagging(self):
        self.cache()
        fake = FakeGitHub(self.receipt, self.content, target=PRIOR, existing=True, assets=False)
        fake.immutable = False
        with patch.object(transport, "_gh", side_effect=fake.gh), self.download():
            result = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(result["target_commit"], PRIOR)
        self.assertEqual([c[1] for c in fake.calls if c[0] == "release"], ["upload"])

    def test_cli_authentication_failure_remains_clear(self):
        failure = subprocess.CompletedProcess([], 1, b"", b"authentication required")
        with patch.object(transport, "_gh", return_value=failure), self.assertRaisesRegex(ValueError, "authentication required"):
            transport._api(self.repository, f"repos/{PROJECT}", missing=True)

    def test_wrong_remote_bytes_assets_or_unreachable_target_never_replaced(self):
        self.cache()
        for damage in ("bytes", "extra_asset", "unreachable", "api_error"):
            fake = FakeGitHub(self.receipt, self.content, target=PRIOR, existing=True)
            if damage == "extra_asset": fake.extra_assets = [{"name": "unexpected.txt", "size": 1}]
            if damage == "unreachable": fake.compare_status = "diverged"
            if damage == "api_error": fake.api_error = "403"
            with patch.object(transport, "_gh", side_effect=fake.gh), self.download(b"bad" if damage == "bytes" else None):
                with self.assertRaises(ValueError):
                    transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
            self.assertFalse(any(c[0] == "release" for c in fake.calls))

    def test_invalid_destination_is_rejected_before_cli_or_network(self):
        for url in (self.receipt["bundle"]["url"].replace("github.com", "github.example.com"),
                    self.receipt["bundle"]["url"] + "?token=private"):
            changed = deepcopy(self.receipt); changed["bundle"]["url"] = url
            with patch.object(transport, "_gh", side_effect=AssertionError("unexpected CLI")), self.assertRaises(ValueError):
                transport.publish_bundle(self.repository, changed, PROJECT, SOURCE)


if __name__ == "__main__":
    unittest.main()
