"""Check public decision-readiness fixture consistency, not private receiver authorization or runtime policy."""

import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import parse_qsl
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/decision-readiness.md"
FIXTURES = ROOT / "docs/contracts/decision-readiness-v1/fixtures.json"
RETAINED_FIXTURES = ROOT / "docs/contracts/retained-workload-v1/fixtures.json"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_tuple(scope):
    return (
        scope["target"],
        scope["method"],
        scope["path"],
        scope["exact_path"],
        scope["query"],
    )


class DecisionReadinessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        cls.retained = json.loads(RETAINED_FIXTURES.read_text(encoding="utf-8"))
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.actor = cls.fixtures["actor"]
        cls.context = cls.fixtures["session_context"]
        cls.session = cls.context["session"]
        cls.player = cls.context["player"]
        cls.routes = {route["id"]: route for route in cls.fixtures["routes"]}
        cls.requests = {request["id"]: request for request in cls.fixtures["requests"]}
        cls.origins = cls.fixtures["grant_origins"]

    def test_route_inventory_matches_documented_methods_paths_and_callers(self):
        self.assertEqual(set(self.routes), {"R1", "R2"})
        self.assertEqual(len(self.routes), len(self.fixtures["routes"]))
        for identifier, route in self.routes.items():
            with self.subTest(route=identifier):
                row = next(
                    line for line in self.contract.splitlines()
                    if line.startswith(f"| `{identifier}` |")
                )
                self.assertIn(f'`{route["method"]} {route["path"]}`', row)
                self.assertEqual(route["callers"], ["moderation", "rules"])
                for caller in route["callers"]:
                    self.assertIn(f"`{caller}`", row)
                self.assertEqual(route["target"], "session")
                self.assertEqual(route["audience"], "student-id-session-service")
                self.assertEqual(route["profile"], "gateway-request+jwt")
                self.assertIsNone(route["key"])
        self.assertEqual(self.routes["R1"]["query"], ["player_id"])
        self.assertEqual(self.routes["R2"]["query"], [])
        self.assertEqual(
            self.routes["R2"]["path"],
            "/api/v1/sessions/{session_id}/cases/{case_id}/status",
        )

    def test_session_context_requires_assigned_moderator_not_session_owner(self):
        self.assertEqual(self.session["status"], "active")
        self.assertEqual(self.player["player_id"], self.actor["sub"])
        self.assertEqual(self.player["role"], "moderator")
        self.assertNotEqual(self.session["owner_id"], self.player["player_id"])
        moderators = [
            participant["player_id"]
            for participant in self.session["participants"]
            if participant["role"] == "moderator"
        ]
        self.assertEqual(moderators, [self.actor["sub"]])
        for value in (
            self.actor["sub"],
            self.session["session_id"],
            self.session["team_id"],
            self.session["owner_id"],
            self.session["rule_version"],
            self.session["university_snapshot_id"],
            self.session["current_case_id"],
        ):
            self.assertEqual(str(UUID(value)), value)

    def test_grant_origins_pin_exact_scopes_and_narrow_rules_hop_without_extension(self):
        decision = self.origins["moderation_decision_ingress"]
        policy_hop = self.origins["rules_policy_hop"]

        self.assertEqual(sha256(decision["body"]), decision["body_sha256"])
        self.assertEqual(sha256(decision["key"]), decision["idempotency_sha256"])
        decision_body = json.loads(decision["body"])
        self.assertEqual(set(decision_body), {"case_id", "action", "reason"})
        self.assertEqual(decision_body["case_id"], self.session["current_case_id"])
        self.assertEqual(
            decision["path"],
            f'/api/v1/sessions/{self.session["session_id"]}/decisions',
        )

        self.assertEqual(sha256(policy_hop["body"]), policy_hop["body_sha256"])
        self.assertEqual(sha256(policy_hop["key"]), policy_hop["idempotency_sha256"])
        self.assertNotEqual(decision["key"], policy_hop["key"])
        policy_body = json.loads(policy_hop["body"])
        api = (ROOT / "docs/contracts/api.md").read_text(encoding="utf-8")
        policy_def = re.sub(r"\{[^{}]*\}", "object", api.split("PolicyInput = {", 1)[1].split("\n```", 1)[0])
        policy_fields = set(re.findall(r"(\w+):", policy_def))
        self.assertEqual(set(policy_body), policy_fields)
        self.assertEqual(policy_body["session_id"], self.session["session_id"])
        self.assertEqual(policy_body["case_id"], self.session["current_case_id"])
        self.assertEqual(policy_body["rule_version"], self.session["rule_version"])
        self.assertEqual(policy_body["reference_at"], self.session["started_at"])

        domain = (ROOT / "docs/contracts/domain.md").read_text(encoding="utf-8")
        claims_def = domain.split("Claims = {", 1)[1].split("}", 1)[0]
        claims_fields = set(re.findall(r"(\w+):", claims_def))
        self.assertEqual(set(policy_body["claims"]), claims_fields)

        parent = decision["delegation"]
        child = policy_hop["delegation"]
        self.assertEqual(parent["typ"], "gateway-delegation+jwt")
        self.assertEqual(child["typ"], "gateway-delegation+jwt")
        self.assertEqual(parent["azp"], "moderation")
        self.assertEqual(child["azp"], "rules")
        for field in ("v", "iss", "aud", "sub", "actor_jti", "actor_exp", "is_admin"):
            self.assertEqual(parent[field], child[field])
        self.assertFalse(parent["is_admin"])
        self.assertLess(0, parent["iat"])
        self.assertLessEqual(parent["iat"], child["iat"])
        self.assertLess(child["iat"], child["exp"])
        self.assertLessEqual(child["exp"], parent["exp"])
        self.assertLessEqual(parent["exp"], parent["actor_exp"])
        self.assertLessEqual(parent["exp"] - parent["iat"], 30)
        self.assertLessEqual(child["exp"] - child["iat"], 30)

        for grant in (parent, child):
            for scope in grant["scopes"]:
                self.assertTrue(scope["exact_path"])
                self.assertIn("query", scope)
                self.assertNotIn("*", scope["path"])

        parent_scopes = {scope_tuple(scope) for scope in parent["scopes"]}
        child_scopes = {scope_tuple(scope) for scope in child["scopes"]}
        self.assertTrue(child_scopes.issubset(parent_scopes))
        expected_session_scopes = {
            (
                "session",
                "GET",
                f'/internal/v1/sessions/{self.session["session_id"]}/context',
                True,
                f'player_id={self.actor["sub"]}',
            ),
            (
                "session",
                "GET",
                f'/api/v1/sessions/{self.session["session_id"]}/cases/{self.session["current_case_id"]}/status',
                True,
                "",
            ),
        }
        self.assertEqual(child_scopes, expected_session_scopes)
        self.assertIn(
            ("rules", "POST", "/internal/v1/policy/evaluations", True, ""),
            parent_scopes,
        )

    def test_wire_requests_match_routes_assertions_and_grant_containment(self):
        pins = {
            "session_id": self.session["session_id"],
            "case_id": self.session["current_case_id"],
            "player_id": self.actor["sub"],
        }
        empty_hash = sha256("")
        seen_pairs = set()
        for identifier, request in self.requests.items():
            route = self.routes[request["route"]]
            origin = self.origins[request["origin"]]["delegation"]
            assertion = request["assertion"]
            with self.subTest(request=identifier):
                seen_pairs.add((request["route"], request["caller"]))
                self.assertIn(request["caller"], route["callers"])
                self.assertEqual(request["caller"], origin["azp"])
                self.assertEqual(request["path"], route["path"].format(**pins))
                self.assertEqual(request["body"], "")
                self.assertIsNone(request["key"])

                query = parse_qsl(request["query"], keep_blank_values=True)
                self.assertEqual([name for name, _ in query], route["query"])
                for name, value in query:
                    self.assertEqual(value, pins[name])
                    self.assertEqual(str(UUID(value)), value)

                self.assertEqual(assertion["typ"], route["profile"])
                self.assertEqual(assertion["v"], 1)
                self.assertEqual(assertion["iss"], "student-id-gateway")
                self.assertEqual(assertion["aud"], route["audience"])
                self.assertEqual(assertion["azp"], request["caller"])
                self.assertEqual(assertion["sub"], self.actor["sub"])
                self.assertEqual(assertion["actor_jti"], self.actor["actor_jti"])
                self.assertEqual(assertion["actor_exp"], self.actor["actor_exp"])
                self.assertFalse(assertion["is_admin"])
                self.assertEqual(assertion["session_id"], self.session["session_id"])
                self.assertEqual(assertion["method"], route["method"])
                self.assertEqual(assertion["path"], request["path"])
                self.assertEqual(assertion["query_sha256"], sha256(request["query"]))
                self.assertEqual(assertion["body_sha256"], empty_hash)
                self.assertEqual(assertion["idempotency_sha256"], empty_hash)

                required_scope = (
                    route["target"],
                    route["method"],
                    request["path"],
                    True,
                    request["query"],
                )
                self.assertIn(
                    required_scope,
                    {scope_tuple(scope) for scope in origin["scopes"]},
                )

        self.assertEqual(
            seen_pairs,
            {("R1", "moderation"), ("R2", "moderation"), ("R1", "rules"), ("R2", "rules")},
        )

    def test_actorless_case_owner_polls_remain_separate_session_workloads(self):
        polls = {poll["id"]: poll for poll in self.fixtures["session_workload_polls"]}
        self.assertEqual(set(polls), {"W5", "W6", "W7"})
        retained_routes = {route["id"]: route for route in self.retained["routes"]}
        retained_requests = {req["route"]: req for req in self.retained["requests"]}
        for identifier, poll in polls.items():
            with self.subTest(poll=identifier):
                self.assertEqual(poll["caller"], "session")
                self.assertEqual(poll["profile"], "gateway-workload+jwt")
                self.assertNotEqual(poll["profile"], self.routes["R2"]["profile"])
                self.assertTrue(poll["path"].startswith("/internal/v1/"))
                self.assertEqual(poll["path"], retained_requests[identifier]["path"])
                self.assertEqual(retained_routes[identifier]["callers"], ["session"])
                self.assertNotIn(poll["caller"], self.routes["R2"]["callers"])

    def test_status_responses_and_negative_cases_cover_all_required_failure_modes(self):
        responses = self.fixtures["status_responses"]
        ready = responses["ready"]["body"]
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(
            ready["ready_services"],
            ["applicant", "credential", "university_record"],
        )
        self.assertEqual(ready["case_id"], self.session["current_case_id"])
        self.assertEqual(ready["session_id"], self.session["session_id"])

        pending = responses["pending_partial"]
        self.assertEqual(pending["body"]["state"], "pending")
        self.assertLess(len(pending["body"]["ready_services"]), 3)
        self.assertEqual(pending["caller_error_status"], 409)
        self.assertEqual(pending["caller_error_code"], "CASE_NOT_READY")

        self.assertEqual(responses["ready_missing_owner"]["caller_error_status"], 503)
        self.assertEqual(responses["mismatched_case_pin"]["caller_error_status"], 503)
        self.assertEqual(responses["upstream_unavailable"]["caller_error_status"], 503)

        negatives = {case["id"]: case for case in self.fixtures["negative_cases"]}
        required_negatives = {
            "wrong-caller",
            "missing-proof",
            "expired-proof",
            "mixed-proof",
            "wrong-actor",
            "wrong-session",
            "wrong-case",
            "noncurrent-case",
            "lobby-session",
            "ended-session",
            "extra-query",
            "extra-body",
            "extra-key",
            "scope-prefix",
            "scope-wildcard",
            "callback-rescope",
            "pending-status",
            "malformed-status",
            "unavailable-status",
        }
        self.assertEqual(set(negatives), required_negatives)
        for case in negatives.values():
            self.assertEqual(case["expected"], "deny")

        self.assertNotIn(negatives["wrong-caller"]["caller"], self.routes["R2"]["callers"])
        self.assertGreater(negatives["expired-proof"]["now"], negatives["expired-proof"]["delegation_exp"])
        self.assertEqual(negatives["wrong-actor"]["sub"], self.session["owner_id"])
        self.assertEqual(negatives["wrong-actor"]["role"], "junior_moderator")
        self.assertTrue(negatives["wrong-actor"]["is_owner"])
        self.assertNotEqual(sha256(negatives["extra-query"]["query"]), sha256(""))
        self.assertNotEqual(sha256(negatives["extra-body"]["body"]), sha256(""))
        self.assertIsNotNone(negatives["extra-key"]["key"])
        self.assertFalse(negatives["scope-prefix"]["scope"]["exact_path"])
        self.assertNotIn("query", negatives["scope-wildcard"]["scope"])
        self.assertNotEqual(
            negatives["callback-rescope"]["parent_case_id"],
            negatives["callback-rescope"]["callback_case_id"],
        )

    def test_owner_cases_are_documented_without_claiming_route_activation(self):
        documented = re.findall(r"^\| `([a-z][a-z-]+)` \|", self.contract, re.MULTILINE)
        self.assertEqual(documented, self.fixtures["owner_cases"])
        self.assertIn("not route activation, container publication, or delivery evidence", self.contract)
        self.assertIn("They do not implement authorization", self.contract)
        self.assertIn("Retained workload routes `W1` through `W10` are merged and deployed.", self.contract)


if __name__ == "__main__":
    unittest.main()
