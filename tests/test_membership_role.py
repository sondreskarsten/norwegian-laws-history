"""A retained amendment occurrence must not hide an exit from current sources."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from law_history.ledger import show_document


class MembershipRoleTests(TestCase):
    def lookup(self, role, *, omitted=False, renamed=False):
        refid = "forskrift/2022-12-21-2456"
        current = {"role": "forskrifter", "original_filename": "current.tar.bz2", "prefixes": ["sf/"]}
        amendments = {"role": "amendment_acts", "original_filename": "acts.tar.bz2", "prefixes": ["lti/"]}
        scopes = [current, amendments]
        later = [amendments] if omitted else [dict(current, original_filename="other.tar.bz2") if renamed else current, amendments]
        summaries = [{"observation_id": str(i), "knowledge_cutoff": f"2026-09-2{i}T12:00:00Z", "scope": scope}
                     for i, scope in enumerate([scopes, later], 5)]
        catalogs = {"5": [{"refid": refid, "role": "forskrifter"}, {"refid": refid, "role": "amendment_acts"}],
                    "6": [{"refid": refid, "role": "amendment_acts"}]}
        with patch("law_history.ledger.list_observations", return_value=summaries), patch(
            "law_history.ledger.read_observation", side_effect=lambda repo, identity: ({}, {}, catalogs[identity])
        ):
            return show_document(Path("unused"), refid, role)

    def test_current_exit_is_visible_while_original_act_remains(self):
        result = self.lookup("forskrifter")
        self.assertEqual([r["status"] for r in result["observations"]], ["present", "not_present_in_observation"])
        self.assertEqual(result["source_role"], "forskrifter")
        self.assertEqual(result["legal_valid_time"], {"status": "unresolved", "from": None, "until": None})
        self.assertEqual([r["status"] for r in self.lookup(None)["observations"]], ["present", "present"])
        self.assertEqual([r["status"] for r in self.lookup("amendment_acts")["observations"]], ["present", "present"])

    def test_missing_or_changed_archive_scope_does_not_prove_absence(self):
        for change in ({"omitted": True}, {"renamed": True}):
            with self.subTest(change=change):
                result = self.lookup("forskrifter", **change)["observations"][-1]
                self.assertEqual(result["status"], "scope_not_comparable")
                self.assertFalse(result["scope_comparable"])

    def test_unknown_role_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown source archive role"):
            show_document(Path("unused"), "forskrift/2022-12-21-2456", "typo")
