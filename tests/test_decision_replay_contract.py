"""Check synthetic result-lookup examples, not production authorization or persistence."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs/contracts"


class DecisionReplayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = json.loads((CONTRACTS / "decision-replay-v1/fixtures.json").read_text())
        cls.base = json.loads((CONTRACTS / cls.examples["base_fixture"]).read_text())
        cls.ingress = cls.base["grant_origins"][cls.examples["request_origin"]]

    def test_context_only_scope_is_exact_existing_actor_context(self):
        grant = self.examples["context_only_delegation"]
        self.assertEqual(grant["scopes"], self.ingress["delegation"]["scopes"][:1])
        scope = grant["scopes"][0]
        self.assertEqual(scope["method"], "GET")
        self.assertTrue(scope["exact_path"])
        self.assertEqual(scope["query"], "player_id=" + grant["sub"])
        self.assertNotIn("session_id", grant)
        self.assertNotIn("*", scope["path"])

    def test_result_grant_preserves_actor_and_existing_lifetime(self):
        grant = self.examples["context_only_delegation"]
        parent = self.ingress["delegation"]
        for name in ["typ", "v", "iss", "aud", "azp", "sub", "actor_jti", "actor_exp", "is_admin"]:
            self.assertEqual(grant[name], parent[name])
        self.assertFalse(grant["is_admin"])
        self.assertGreater(grant["exp"], grant["iat"])
        self.assertLessEqual(grant["exp"] - grant["iat"], 30)
        self.assertLessEqual(grant["exp"], min(parent["exp"], grant["actor_exp"]))

    def test_fresh_decision_dependencies_remain_distinct(self):
        original = self.ingress["delegation"]["scopes"]
        limited = self.examples["context_only_delegation"]["scopes"]
        self.assertEqual(len(original), 6)
        self.assertEqual(len(limited), 1)
        self.assertEqual({scope["target"] for scope in limited}, {"session"})
        self.assertTrue(any(scope["path"].endswith("/status") for scope in original))
        self.assertTrue(any(scope["path"].endswith("/policy/evaluations") for scope in original))
        self.assertFalse(any(scope["path"].endswith(("/status", "/policy/evaluations")) for scope in limited))

    def test_only_owner_matching_result_examples_return_original_status(self):
        owner = self.examples["owner_lookup"]
        self.assertEqual(owner["owner"], "moderation")
        self.assertEqual(set(owner["match_fields"]), {"caller", "key", "endpoint", "request_fingerprint"})
        self.assertFalse(owner["gateway_knows_result_exists"])
        self.assertFalse(owner["new_key_on_retry"])
        for name in ["maximum_policy_requests_on_result_lookup", "maximum_new_decision_rows", "maximum_new_outbox_rows"]:
            self.assertEqual(owner[name], 0)
        examples = self.examples["result_examples"]
        self.assertEqual({value["id"] for value in examples}, {"scored-current-cleared", "later-case-current", "ended-matching-result"})
        for value in examples:
            self.assertEqual(value["stored_result"], "match")
            self.assertTrue(value["same_key"] and value["same_body"])
            self.assertEqual(value["owner_http"], 201)
            self.assertNotEqual(value["current_case"], "same")

    def test_denial_matrix_does_not_treat_context_as_write_authority(self):
        cases = {value["id"]: value for value in self.examples["denials"]}
        expected = {"changed-body", "noncurrent-new-key", "lobby-new-key", "ending-new-key", "ended-new-key",
                    "wrong-actor", "expired-player", "expired-context-grant", "cross-session-context",
                    "context-to-readiness-escalation", "context-to-policy-escalation", "context-to-evidence-escalation",
                    "context-to-snapshot-escalation"}
        self.assertEqual(set(cases), expected)
        for value in cases.values():
            self.assertIn(value["http"], {401, 403, 409})
            self.assertIn(value["stage"], {"owner", "gateway_ingress", "gateway_exchange"})
        self.assertEqual(cases["changed-body"]["http"], 409)
        self.assertTrue(cases["changed-body"]["same_key"])
        self.assertFalse(cases["changed-body"]["same_body"])
        for name in ["noncurrent-new-key", "lobby-new-key", "ending-new-key", "ended-new-key"]:
            self.assertEqual(cases[name]["stored_result"], "missing")
            self.assertFalse(cases[name]["same_key"])


if __name__ == "__main__":
    unittest.main()
