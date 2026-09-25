"""Real local Git transport tests; no GitHub writes or source downloads."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from law_history.ledger import ingest
from law_history.materialize import materialize
from law_history import publication
from law_history.validation import file_hash, read_json
from test_consumer import fixture


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="history-publication-test-")
        self.root = Path(self.temporary.name)
        self.repository = self.root / "checkout"
        self.remote = self.root / "remote.git"
        self.repository.mkdir()
        self.git("init", "--bare", str(self.remote))
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Publication test")
        self.git("config", "user.email", "publication-test@example.invalid")
        self.git("config", "core.autocrlf", "true")
        self.git("config", "commit.gpgsign", "false")
        (self.repository / "README.md").write_text("Local publication test\n", encoding="utf-8")
        (self.repository / ".gitignore").write_text(".cache/\n", encoding="utf-8")
        (self.repository / ".gitattributes").write_text(
            "observations/** -text\nmaterializations/** -text\npublications/** -text\n"
            "operation-products/** -text\noperation-publications/** -text\n"
            "body-products/** -text\nbody-publications/** -text\n"
            "later-claims/** -text\nclaim-publications/** -text\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "Initialize test repository")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "HEAD:refs/heads/main")
        self.initial = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repository), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.decode("utf-8")

    def accepted(self, label="first", observed="2026-09-25T12:00:00+00:00"):
        source, receipt, _ = fixture(self.root / label, observed=observed)
        ingest(str(source), self.repository)
        product = materialize(self.repository, receipt["observation_id"], ["lov/2024-01-01-1"])
        return receipt, product

    def publish(self):
        return publication.publish(self.repository, github_repository="fixture/history")

    def remote_head(self):
        return self.git("rev-parse", "refs/heads/main", cwd=self.remote).strip()

    def test_new_publication_and_replay_bind_actual_commits_and_exact_bytes(self):
        _, product = self.accepted()
        (self.repository / "private-untracked.txt").write_bytes(b"Must stay local")
        before = {p.relative_to(self.repository).as_posix(): p.read_bytes()
                  for root in ("observations", "materializations")
                  for p in (self.repository / root).rglob("*") if p.is_file()}
        with patch.dict(os.environ, {"GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z",
                                     "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"}):
            result = self.publish()
        self.assertEqual(result["status"], "published")
        self.assertEqual(self.remote_head(), result["publication_commit"])
        self.assertEqual(self.git("rev-parse", "HEAD^").strip(), result["data_commit"])
        receipt = read_json(self.repository / "publications" / (product["materialization_id"] + ".json"))
        self.assertEqual(receipt["expected_git_parent"], self.initial)
        self.assertEqual(receipt["creation_commit"], result["data_commit"])
        self.assertEqual(receipt["creation_tree"], self.git("rev-parse", result["data_commit"] + "^{tree}").strip())
        self.assertFalse(receipt["project_committer_date"].startswith("2001-"))
        self.assertEqual(receipt["materialization_receipt_sha256"],
                         file_hash(self.repository / "materializations" / product["materialization_id"] / "receipt.json"))
        for name, content in before.items():
            actual = subprocess.run(["git", "-C", str(self.remote), "show", f'refs/heads/main:{name}'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
            self.assertEqual(actual, content)
        replay = self.publish()
        self.assertEqual(replay["status"], "already_published")
        self.assertEqual(replay["publications"], result["publications"])
        self.assertEqual(replay["remote_head"], result["remote_head"])
        self.assertNotIn("private-untracked.txt", self.git("ls-tree", "-r", "--name-only", "HEAD"))

    def test_second_observation_is_append_only_and_preserves_first_receipt(self):
        _, first = self.accepted()
        self.publish()
        first_path = self.repository / "publications" / (first["materialization_id"] + ".json")
        original = first_path.read_bytes()
        parent = self.remote_head()
        self.accepted("second", "2026-09-26T12:00:00+00:00")
        result = self.publish()
        self.assertEqual(result["publication_count"], 2)
        self.assertEqual(first_path.read_bytes(), original)
        second = result["publications"][-1]
        self.assertEqual(second["expected_git_parent"], parent)
        names = self.git("diff", "--name-status", "--no-renames", parent, "HEAD").splitlines()
        self.assertTrue(names)
        self.assertTrue(all(name.startswith("A\t") for name in names))

    def test_operation_product_publication_preserves_body_receipt_contract(self):
        from law_history.operation_products import extract_operations
        accepted, _ = self.accepted()
        first = self.publish()
        body_receipt = first["publications"][0]
        operation = extract_operations(self.repository, accepted["observation_id"], github_repository="fixture/history")
        with patch.object(publication, "publish_bundle", side_effect=ValueError("Public release verification failed")):
            with self.assertRaisesRegex(ValueError, "Public release verification failed"):
                self.publish()
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), first["remote_head"])
        self.assertEqual(self.remote_head(), first["remote_head"])
        self.assertFalse((self.repository / "operation-publications").exists())
        with patch.object(publication, "publish_bundle", return_value={"verification": "offline_fixture"}) as transport, \
                patch.object(publication, "read_operation_product", wraps=publication.read_operation_product) as verify:
            delivered = self.publish()
        verify.assert_called_once_with(self.repository, operation["operation_product_id"])
        transport.assert_called_once_with(self.repository, unittest.mock.ANY, "fixture/history", first["remote_head"])
        self.assertEqual(delivered["publications"], [body_receipt])
        self.assertEqual(delivered["operation_publication_count"], 1)
        receipt = delivered["operation_publications"][0]
        self.assertEqual(receipt["contract"], "history-operation-git-publication-v1")
        self.assertEqual(receipt["operation_product_id"], operation["operation_product_id"])
        self.assertEqual(receipt["expected_git_parent"], first["remote_head"])
        self.assertEqual(receipt["creation_commit"], delivered["data_commit"])
        self.assertEqual(receipt["operation_tree"], self.git("rev-parse", receipt["creation_commit"] +
            ":operation-products/" + operation["operation_product_id"]).strip())
        self.assertEqual(receipt["bundle"], operation["bundle"])
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", "HEAD", "--", "operation-products").splitlines(),
                         ["operation-products/" + operation["operation_product_id"] + "/receipt.json"])
        before = {path: path.read_bytes() for name in ("publications", "operation-publications")
                  for path in (self.repository / name).glob("*.json")}
        with patch.object(publication, "publish_bundle", side_effect=AssertionError("Fetched delivered release")) as transport, \
                patch.object(publication, "read_operation_product", side_effect=AssertionError("Rechecked delivered artifacts")) as verify:
            replay = self.publish()
        transport.assert_not_called(); verify.assert_not_called()
        self.assertEqual(replay["status"], "already_published")
        self.assertEqual(replay["operation_publications"], delivered["operation_publications"])
        self.assertEqual(replay["operation_releases"], [])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_uncommitted_operation_publication_receipt_requires_full_reverification(self):
        from law_history.operation_products import extract_operations
        accepted, _ = self.accepted()
        operation = extract_operations(self.repository, accepted["observation_id"], github_repository="fixture/history")
        original_commit = publication._commit

        def interrupted(repository, paths, parent, message):
            if any(path.startswith("operation-publications/") for path in paths):
                raise ValueError("Interrupted before publication receipt commit")
            return original_commit(repository, paths, parent, message)

        with patch.object(publication, "publish_bundle", return_value={"verification": "offline_fixture"}), \
                patch.object(publication, "_commit", side_effect=interrupted):
            with self.assertRaisesRegex(ValueError, "Interrupted before publication"):
                self.publish()
        data_commit = self.remote_head()
        path = "operation-publications/" + operation["operation_product_id"] + ".json"
        self.assertTrue((self.repository / path).is_file())
        self.assertNotIn(path, self.git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
        with patch.object(publication, "publish_bundle", return_value={"verification": "offline_fixture"}) as transport, \
                patch.object(publication, "read_operation_product", wraps=publication.read_operation_product) as verify:
            result = self.publish()
        verify.assert_called_once_with(self.repository, operation["operation_product_id"])
        transport.assert_called_once_with(self.repository, unittest.mock.ANY, "fixture/history", data_commit)
        self.assertIsNone(result["data_commit"])
        self.assertEqual(result["operation_publications"][0]["creation_commit"], data_commit)

    def test_remote_parent_mismatch_fails_before_local_commit(self):
        self.accepted()
        other = self.root / "other"
        self.git("clone", "--branch", "main", str(self.remote), str(other))
        self.git("config", "user.name", "Concurrent test", cwd=other)
        self.git("config", "user.email", "concurrent@example.invalid", cwd=other)
        self.git("config", "commit.gpgsign", "false", cwd=other)
        (other / "concurrent.txt").write_text("Concurrent addition", encoding="utf-8")
        self.git("add", "concurrent.txt", cwd=other)
        self.git("commit", "-m", "Concurrent remote addition", cwd=other)
        self.git("push", "origin", "main", cwd=other)
        remote = self.remote_head()
        with self.assertRaisesRegex(ValueError, "Remote branch differs from HEAD"):
            self.publish()
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.initial)
        self.assertEqual(self.remote_head(), remote)
        self.assertFalse((self.repository / "publications").exists())

    def test_remote_race_after_parent_check_rejects_normal_push(self):
        self.accepted()
        other = self.root / "race"
        self.git("clone", "--branch", "main", str(self.remote), str(other))
        self.git("config", "user.name", "Concurrent test", cwd=other)
        self.git("config", "user.email", "concurrent@example.invalid", cwd=other)
        self.git("config", "commit.gpgsign", "false", cwd=other)
        original_commit = publication._commit

        def competing_commit(repository, paths, parent, message):
            result = original_commit(repository, paths, parent, message)
            (other / "race.txt").write_bytes(b"Remote moved after the publisher checked its parent")
            self.git("add", "race.txt", cwd=other)
            self.git("commit", "-m", "Concurrent update", cwd=other)
            self.git("push", "origin", "main", cwd=other)
            return result

        with patch.object(publication, "_commit", side_effect=competing_commit):
            with self.assertRaisesRegex(ValueError, "Git push failed"):
                self.publish()
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD", cwd=other).strip())
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), self.remote_head())
        self.assertFalse((self.repository / "publications").exists())

    def test_network_remote_must_match_receipt_repository_without_network_access(self):
        self.git("remote", "set-url", "origin", "https://github.com/fixture/wrong.git")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.publish()
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.initial)

    def test_pushed_data_without_publication_receipt_recovers(self):
        _, product = self.accepted()
        original_commit = publication._commit

        def interrupted(repository, paths, parent, message):
            if any(path.startswith("publications/") for path in paths):
                raise ValueError("Simulated interruption after data push")
            return original_commit(repository, paths, parent, message)

        with patch.object(publication, "_commit", side_effect=interrupted):
            with self.assertRaisesRegex(ValueError, "Simulated interruption"):
                self.publish()
        data_commit = self.remote_head()
        self.assertNotEqual(data_commit, self.initial)
        # Use a fresh checkout: recovery must not depend on an untracked receipt.
        fresh = self.root / "fresh"
        self.git("clone", "--branch", "main", str(self.remote), str(fresh))
        self.git("config", "user.name", "Recovery test", cwd=fresh)
        self.git("config", "user.email", "recovery@example.invalid", cwd=fresh)
        self.git("config", "commit.gpgsign", "false", cwd=fresh)
        result = publication.publish(fresh, github_repository="fixture/history")
        self.assertIsNone(result["data_commit"])
        self.assertEqual(result["publications"][0]["creation_commit"], data_commit)
        self.assertEqual(result["publications"][0]["materialization_id"], product["materialization_id"])
        self.assertEqual(self.remote_head(), result["publication_commit"])

    def test_tracked_modification_and_unrelated_staged_addition_are_rejected(self):
        self.accepted()
        readme = self.repository / "README.md"
        original = readme.read_bytes()
        readme.write_bytes(b"Unrelated tracked edit\n")
        with self.assertRaisesRegex(ValueError, "tracked modifications"):
            self.publish()
        readme.write_bytes(original)
        (self.repository / "unrelated.txt").write_text("Do not publish", encoding="utf-8")
        self.git("add", "unrelated.txt")
        with self.assertRaisesRegex(ValueError, "unrelated staged"):
            self.publish()
        self.assertEqual(self.remote_head(), self.initial)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.initial)

    def test_corrupt_product_and_extra_observation_file_are_rejected(self):
        observation, product = self.accepted()
        extra = self.repository / "observations" / observation["observation_id"] / "unverified.txt"
        extra.write_bytes(b"Not accepted evidence")
        with self.assertRaisesRegex(ValueError, "Unexpected accepted-observation artifact"):
            self.publish()
        extra.unlink()
        inventory = self.repository / "materializations" / product["materialization_id"] / "inventory.json"
        inventory.write_bytes(b"{}\n")
        with self.assertRaisesRegex(ValueError, "product bytes changed"):
            self.publish()
        self.assertEqual(self.remote_head(), self.initial)

    def test_tampered_publication_receipt_is_rejected_without_remote_change(self):
        _, product = self.accepted()
        self.publish()
        parent = self.remote_head()
        path = self.repository / "publications" / (product["materialization_id"] + ".json")
        path.write_bytes(path.read_bytes().replace(b'"branch":"main"', b'"branch":"other"'))
        with self.assertRaisesRegex(ValueError, "Publication receipt changed"):
            self.publish()
        self.assertEqual(self.remote_head(), parent)


if __name__ == "__main__":
    unittest.main()
