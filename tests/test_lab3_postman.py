"""Guard the read-only default and private operator-only Lab 3 collection."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "postman/lab3-http.postman_collection.json"
ENVIRONMENT = ROOT / "postman/lab3-http.postman_environment.json"


class Lab3PostmanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection = json.loads(COLLECTION.read_text())
        cls.environment = json.loads(ENVIRONMENT.read_text())

    def test_safe_public_folder_contains_only_anonymous_gets(self):
        folders = {folder["name"]: folder["item"] for folder in self.collection["item"]}
        self.assertEqual(set(folders), {"Safe public smoke", "Private operator reads"})
        public = folders["Safe public smoke"]
        self.assertEqual(len(public), 3)
        for item in public:
            request = item["request"]
            self.assertEqual(request["method"], "GET")
            self.assertTrue(request["url"].startswith("{{gateway_url}}/"))
            self.assertNotIn("header", request)
            self.assertNotIn("body", request)
        self.assertEqual(
            {item["request"]["url"] for item in public},
            {"{{gateway_url}}/healthz", "{{gateway_url}}/internal/v1/status", "{{gateway_url}}/api/v1/players/me"},
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


if __name__ == "__main__":
    unittest.main()
