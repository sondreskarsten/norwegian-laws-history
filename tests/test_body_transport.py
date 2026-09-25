"""The separate body-release namespace must retain immutable publication behavior."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from law_history import body_transport as transport
from test_operation_transport import FakeGitHub, bundle, PROJECT, SOURCE, PRIOR


class BodyGitHub(FakeGitHub):
    def release(self):
        release = super().release()
        if self.assets:
            release["assets"][0]["name"] = "bodies.tar.gz"
        return release

    def gh(self, repository, *args, check=True):
        if args[:2] != ("release", "create"):
            return super().gh(repository, *args, check=check)
        self.calls.append(args)
        assert args[args.index("--target") + 1] == SOURCE and "--latest=false" in args
        assert Path(args[3]).name == "bodies.tar.gz" and Path(args[3]).read_bytes() == self.content
        self.existing, self.assets, self.draft, self.target = True, True, False, SOURCE
        return subprocess.CompletedProcess(args, 0, b"{}", b"")


class BodyTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="body-transport-")
        self.repository = Path(self.temp.name)
        files = {"inventory.jsonl.gz": b"complete inventory", "documents/00000.jsonl.gz": b"qualified body payloads"}
        self.content = bundle(files)
        identity = "c" * 64; tag = "bodies-" + identity
        self.receipt = {"body_product_id": identity, "release_tag": tag,
            "artifact_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "bundle": {"name": "bodies.tar.gz", "sha256": hashlib.sha256(self.content).hexdigest(),
                "bytes": len(self.content), "url": f"https://github.com/{PROJECT}/releases/download/{tag}/bodies.tar.gz"}}
        cache = self.repository / ".cache/body-bundles" / (self.receipt["bundle"]["sha256"] + ".tar.gz")
        cache.parent.mkdir(parents=True); cache.write_bytes(self.content)

    def tearDown(self):
        self.temp.cleanup()

    def readback(self, request, timeout):
        self.assertEqual(request.full_url, self.receipt["bundle"]["url"])
        self.assertNotIn("Authorization", request.headers)
        return io.BytesIO(self.content)

    def test_publish_then_replay_preserves_original_release_target_and_bytes(self):
        github = BodyGitHub(self.receipt, self.content)
        with patch.object(transport, "_gh", github.gh), patch.object(transport.urllib.request, "urlopen", self.readback):
            first = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
            second = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(first["status"], "published")
        self.assertEqual(second["status"], "already_published")
        self.assertEqual(first["target_commit"], second["target_commit"])
        self.assertEqual(first["sha256"], self.receipt["bundle"]["sha256"])
        self.assertEqual(sum(call[:2] == ("release", "create") for call in github.calls), 1)
        self.assertFalse(any("--clobber" in call or call[:2] == ("release", "delete") for call in github.calls))

    def test_draft_recovery_validates_bytes_and_never_moves_old_target(self):
        github = BodyGitHub(self.receipt, self.content, target=PRIOR, existing=True, draft=True)
        with patch.object(transport, "_gh", github.gh), patch.object(transport.urllib.request, "urlopen", self.readback):
            result = transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertEqual(result["target_commit"], PRIOR)
        self.assertFalse(any("--target" in call for call in github.calls))
        self.assertTrue(any(call[:2] == ("release", "download") for call in github.calls))
        damaged = BodyGitHub(self.receipt, self.content, existing=True, draft=True)
        damaged.draft_content = b"changed artifact"
        with patch.object(transport, "_gh", damaged.gh), self.assertRaises(ValueError):
            transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)
        self.assertFalse(any(call[:2] == ("release", "edit") for call in damaged.calls))

    def test_wrong_namespace_destination_and_public_readback_fail(self):
        for key, value in (("release_tag", "operations-" + "c" * 64), ("body_product_id", "d" * 64)):
            receipt = deepcopy(self.receipt); receipt[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                transport.ensure_bundle(self.repository, receipt)
        github = BodyGitHub(self.receipt, self.content, existing=True)
        with patch.object(transport, "_gh", github.gh), self.assertRaises(ValueError):
            transport.publish_bundle(self.repository, self.receipt, "fixture/wrong", SOURCE)
        with patch.object(transport, "_gh", github.gh), \
                patch.object(transport.urllib.request, "urlopen", return_value=io.BytesIO(b"changed")), \
                self.assertRaises(ValueError):
            transport.publish_bundle(self.repository, self.receipt, PROJECT, SOURCE)


if __name__ == "__main__":
    unittest.main()
