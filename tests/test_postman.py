"""Guard the read-only default and private operator-only HTTP checks collection."""

import json
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "postman/http-checks.postman_collection.json"
ENVIRONMENT = ROOT / "postman/http-checks.postman_environment.json"


class HttpChecksCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection = json.loads(COLLECTION.read_text())
        cls.environment = json.loads(ENVIRONMENT.read_text())

    def test_safe_public_folder_contains_only_anonymous_gets(self):
        folders = {folder["name"]: folder["item"] for folder in self.collection["item"]}
        self.assertEqual(set(folders), {"Safe public smoke", "Private operator reads"})
        public = folders["Safe public smoke"]
        self.assertEqual(len(public), 4)
        for item in public:
            request = item["request"]
            self.assertEqual(request["method"], "GET")
            self.assertTrue(request["url"].startswith("{{gateway_url}}/"))
            self.assertNotIn("header", request)
            self.assertNotIn("body", request)
        self.assertEqual(
            {item["request"]["url"] for item in public},
            {"{{gateway_url}}/healthz", "{{gateway_url}}/internal/v1/status", "{{gateway_url}}/internal/v1/discovery/instances", "{{gateway_url}}/api/v1/players/me"},
        )

    def test_private_folder_has_only_operator_gets_and_no_mutations(self):
        private = self.collection["item"][1]["item"]
        self.assertEqual(len(private), 3)
        for item in private:
            request = item["request"]
            self.assertEqual(request["method"], "GET")
            self.assertTrue(request["url"].startswith("{{discovery_url}}/internal/v1/"))
            self.assertNotIn("body", request)
            self.assertEqual(
                {header["key"]: header["value"] for header in request["header"]},
                {"X-Control-Name": "{{control_name}}", "X-Control-Token": "{{control_token}}"},
            )
            self.assertIn("pm.test(", "\n".join(item["event"][0]["script"]["exec"]))
        values = {entry["key"]: entry for entry in self.environment["values"]}
        self.assertEqual(values["control_name"]["value"], "operator")
        self.assertEqual(values["control_token"]["value"], "REPLACE_IN_PRIVATE_COPY")
        self.assertEqual(values["control_token"]["type"], "secret")


GUIDED = ROOT / "postman/guided-demo.postman_collection.json"
GUIDED_ROUTES = {
    ("POST", "/api/v1/players"), ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"), ("GET", "/.well-known/jwks.json"), ("GET", "/api/v1/players/me"),
    ("PATCH", "/api/v1/players/me"), ("GET", "/api/v1/players/{id}"), ("GET", "/api/v1/friendships"),
    ("POST", "/api/v1/friendships"), ("PUT", "/api/v1/friendships/{id}/acceptance"),
    ("DELETE", "/api/v1/friendships/{id}"), ("POST", "/api/v1/teams"), ("GET", "/api/v1/teams/{id}"),
    ("DELETE", "/api/v1/teams/{id}"), ("POST", "/api/v1/teams/{id}/members"),
    ("DELETE", "/api/v1/teams/{id}/members/{id}"), ("GET", "/api/v1/sessions"), ("POST", "/api/v1/sessions"),
    ("GET", "/api/v1/sessions/{id}"), ("DELETE", "/api/v1/sessions/{id}"),
    ("POST", "/api/v1/sessions/{id}/participants"), ("PUT", "/api/v1/sessions/{id}/roles"),
    ("POST", "/api/v1/sessions/{id}/start"), ("POST", "/api/v1/sessions/{id}/cases"),
    ("GET", "/api/v1/sessions/{id}/cases/{id}/status"), ("POST", "/api/v1/sessions/{id}/end"),
}


class GuidedDemoCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = [item for folder in json.loads(GUIDED.read_text())["item"] for item in folder["item"]]

    def test_requests_are_numbered_in_order(self):
        self.assertEqual([item["name"][:2] for item in self.items], [f"{n:02d}" for n in range(1, len(self.items) + 1)])
        self.assertTrue(self.items[27]["name"].startswith("28 ") and self.items[28]["name"].startswith("29 "))

    def test_mutations_carry_idempotency_keys_and_every_request_asserts(self):
        for item in self.items:
            with self.subTest(request=item["name"]):
                request = item["request"]
                headers = {header["key"]: header["value"] for header in request["header"]}
                if request["method"] != "GET":
                    self.assertEqual(headers.get("Idempotency-Key"), "{{request_key}}")
                tests = "\n".join("\n".join(e["script"]["exec"]) for e in item["event"] if e["listen"] == "test")
                self.assertIn("pm.test(", tests)

    def test_player_and_session_public_routes_are_covered(self):
        covered = set()
        for item in self.items:
            path = item["request"]["url"].removeprefix("{{gateway_url}}")
            covered.add((item["request"]["method"], re.sub(r"\{\{[a-z0-9_]+\}\}", "{id}", path)))
        self.assertEqual(GUIDED_ROUTES - covered, set())


SERVICE_COLLECTIONS = sorted((ROOT / "postman").glob("*-service.json"))


class ServiceCollectionTests(unittest.TestCase):
    def requests(self, items):
        for item in items:
            if "item" in item:
                yield from self.requests(item["item"])
            else:
                yield item["request"]

    def test_expected_service_collections_exist(self):
        self.assertEqual(
            [path.name for path in SERVICE_COLLECTIONS],
            [
                "applicant-service.json",
                "credential-service.json",
                "discord-dms-service.json",
                "moderation-service.json",
                "server-rules-service.json",
                "university-record-service.json",
            ],
        )

    def test_collections_use_the_gateway_and_no_lab_names(self):
        for path in SERVICE_COLLECTIONS:
            with self.subTest(collection=path.name):
                text = path.read_text()
                collection = json.loads(text)
                variables = {entry["key"]: entry["value"] for entry in collection["variable"]}
                self.assertEqual(variables["gateway_url"], "http://127.0.0.1:8080")
                self.assertIsNone(re.search(r"\blab[ -]?\d", text, re.IGNORECASE))
                for request in self.requests(collection["item"]):
                    url = request["url"] if isinstance(request["url"], str) else request["url"]["raw"]
                    self.assertTrue(url.startswith("{{gateway_url}}/api/v1/") or url.startswith("{{gateway_url}}/.well-known/"), url)

    def items(self, items):
        for item in items:
            if "item" in item:
                yield from self.items(item["item"])
            else:
                yield item

    def test_collections_assert_success_and_denial_without_stored_tokens(self):
        for path in SERVICE_COLLECTIONS:
            with self.subTest(collection=path.name):
                collection = json.loads(path.read_text())
                for entry in collection["variable"]:
                    if entry["key"].endswith("_token"):
                        self.assertEqual(entry["value"], "", entry["key"])
                shared = any(event["listen"] == "test" for event in collection.get("event", []))
                successes, denials = 0, 0
                for item in self.items(collection["item"]):
                    scripts = "\n".join("\n".join(event["script"]["exec"]) for event in item.get("event", []) if event["listen"] == "test")
                    self.assertTrue(shared or "pm.test(" in scripts, item["name"])
                    self.assertNotIn("Authorization", {header["key"] for header in item["request"].get("header", [])}, item["name"])
                    expected = re.findall(r"have\.status\((\d{3})\)", scripts) or [item["name"][:3]]
                    successes += any(code.startswith("2") for code in expected)
                    denials += any(code in {"401", "403"} for code in expected)
                self.assertGreater(successes, 0)
                self.assertGreater(denials, 0)


if __name__ == "__main__":
    unittest.main()
