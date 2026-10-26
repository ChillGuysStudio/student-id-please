"""Check public fixture consistency, not private receiver authorization or runtime policy."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import parse_qsl
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/retained-workload.md"
FIXTURES = ROOT / "docs/contracts/retained-workload-v1/fixtures.json"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RetainedWorkloadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(FIXTURES.read_text())
        cls.contract = CONTRACT.read_text()
        cls.acceptance = cls.fixtures["acceptance"]
        cls.routes = {route["id"]: route for route in cls.fixtures["routes"]}
        cls.requests = {request["route"]: request for request in cls.fixtures["requests"]}

    def test_route_inventory_matches_documented_methods_paths_and_callers(self):
        self.assertEqual(set(self.routes), {f"W{index}" for index in range(1, 11)})
        self.assertEqual(set(self.routes), set(self.requests))
        self.assertEqual(len(self.routes), len(self.fixtures["routes"]))
        self.assertEqual(len(self.requests), len(self.fixtures["requests"]))
        for identifier, route in self.routes.items():
            with self.subTest(route=identifier):
                row = next(line for line in self.contract.splitlines()
                           if line.startswith(f"| `{identifier}` |"))
                self.assertIn(f'`{route["method"]} {route["path"]}`', row)
                for caller in route["callers"]:
                    self.assertIn(f"`{caller}`", row)
                self.assertTrue(route["path"].startswith("/internal/v1/"))

    def test_wire_examples_have_exact_context_and_distinct_hop_keys(self):
        pins = dict(self.acceptance, subject_id=self.fixtures["binding"]["subject_id"])
        for identifier, request in self.requests.items():
            route = self.routes[identifier]
            with self.subTest(route=identifier):
                self.assertIn(request["caller"], route["callers"])
                self.assertEqual(request["path"], route["path"].format(**pins))
                query = parse_qsl(request["query"], keep_blank_values=True)
                self.assertEqual([name for name, _ in query], route["query"])
                for name, value in query:
                    self.assertEqual(value, pins[name])
                    self.assertEqual(str(UUID(value)), value)
                if route["method"] == "GET":
                    self.assertEqual(request["body"], "")
                    self.assertIsNone(request["key"])
                else:
                    body = json.loads(request["body"])
                    self.assertEqual(request["key"], body[route["key"]])
                    self.assertNotEqual(request["key"], self.acceptance["idempotency_key"])
                    for name in ("session_id", "attempt_id", "case_id"):
                        self.assertEqual(body[name], pins[name])
        self.assertEqual(self.routes["W10"]["query"], ["session_id", "attempt_id"])
        self.assertNotIn("session", self.routes["W10"]["callers"])
        self.assertEqual(self.routes["W9"]["query"], ["case_id", "session_id", "attempt_id"])

    def test_command_and_reservation_objects_match_the_shared_api(self):
        for identifier in ("W2", "W3", "W4"):
            body = json.loads(self.requests[identifier]["body"])
            self.assertEqual(set(body), {"session_id", "attempt_id", "case_id", "scenario"})
            self.assertEqual(body["scenario"], "random")
        reservation = json.loads(self.requests["W8"]["body"])
        fields = {"session_id", "attempt_id", "case_id", "subject_id", "first_name", "last_name",
                  "role", "university_status", "major", "admission_year"}
        self.assertEqual(set(reservation), fields)
        api = (ROOT / "docs/contracts/api.md").read_text()
        definition = api.split("IdentityReservationInput = {", 1)[1].split("}", 1)[0]
        self.assertEqual(set(re.findall(r"(\w+):", definition)), fields)
        self.assertEqual(reservation["subject_id"], self.fixtures["binding"]["subject_id"])

    def test_original_player_hash_is_not_a_transport_or_downstream_digest(self):
        normalized = json.dumps({"entry_service": self.acceptance["entry_service"]},
                                sort_keys=True, separators=(",", ":"))
        self.assertEqual(sha256(normalized), self.acceptance["normalized_body_sha256"])
        for identifier in ("W2", "W8"):
            request = self.requests[identifier]
            self.assertNotEqual(sha256(request["body"]), sha256(normalized))
            self.assertNotEqual(sha256(request["key"]), sha256(normalized))
        self.assertEqual(len({self.acceptance["idempotency_key"], self.requests["W2"]["key"],
                              self.requests["W8"]["key"]}), 3)

    def test_snapshot_and_real_binding_match_acceptance_despite_null_session_reservation(self):
        for name in ("snapshot_id", "session_id", "reference_at"):
            self.assertEqual(self.fixtures["snapshot"][name], self.acceptance[name])
        for name, value in self.fixtures["binding"].items():
            if name not in {"subject_id", "effect"}:
                self.assertEqual(value, self.acceptance[name])
        self.assertEqual(self.fixtures["binding"]["effect"], "subject_reserve")
        self.assertIsNone(self.fixtures["lifecycle"]["reservation"])
        checked_at = datetime.fromisoformat(self.fixtures["lifecycle"]["checked_at"])
        accepted_at = datetime.fromisoformat(self.acceptance["accepted_at"])
        self.assertLess(accepted_at.timestamp(), self.acceptance["actor_expires_at"])
        self.assertGreater(checked_at.timestamp(), self.acceptance["actor_expires_at"])

    def test_query_variants_preserve_the_documented_negative_conditions(self):
        variants = {case["id"]: case for case in self.fixtures["wire_variants"]}
        pairs = {name: parse_qsl(case["query"], keep_blank_values=True)
                 for name, case in variants.items()}
        self.assertEqual([name for name, _ in pairs["missing-context"]], ["session_id"])
        self.assertEqual([name for name, _ in pairs["duplicate-context"]].count("attempt_id"), 2)
        self.assertIn("case_id", dict(pairs["unknown-query"]))
        self.assertNotEqual(dict(pairs["cross-session"])["session_id"], self.acceptance["session_id"])
        original = self.requests["W10"]["query"]
        for case in variants.values():
            self.assertEqual(case["expected"], "deny")
            self.assertNotEqual(sha256(case["query"]), sha256(original))
        reordered = "&".join(reversed(original.split("&")))
        self.assertEqual(dict(parse_qsl(reordered)), dict(parse_qsl(original)))
        self.assertNotEqual(sha256(original), sha256(reordered))

    def test_owner_acceptance_cases_are_documented_without_runtime_claims(self):
        documented = re.findall(r"^\| `([a-z][a-z-]+)` \|", self.contract, re.MULTILINE)
        self.assertEqual(documented, self.fixtures["owner_cases"])
        self.assertIn("They do not implement authorization", self.contract)
        self.assertIn("not route activation or runtime readiness", self.contract)
        self.assertIn("Until compatible receivers are deployed", self.contract)


if __name__ == "__main__":
    unittest.main()
