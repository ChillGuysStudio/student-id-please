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


if __name__ == "__main__":
    unittest.main()
