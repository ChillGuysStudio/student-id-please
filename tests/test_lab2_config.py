"""Check generated adapter configuration without Docker or private service checkouts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_lab2", ROOT / "scripts/prepare_lab2.py")
prepare_lab2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_lab2)


def read_env(path):
    return {name: value[1:-1] for name, value in
            (line.split("=", 1) for line in path.read_text().splitlines())}


class Lab2ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.keys = patch.object(prepare_lab2, "rsa_pair", return_value={"keys": [{"kid": "gateway-v1"}]})
        self.keys.start()
        self.addCleanup(self.keys.stop)
        self.openssl = patch.object(prepare_lab2.shutil, "which", return_value="openssl")
        self.openssl.start()
        self.addCleanup(self.openssl.stop)

    def test_runtime_and_current_receiver_adapters_match(self):
        prepare_lab2.prepare(self.root, "test/gateway@sha256:" + "a" * 64, 18080, 18009)
        directory = self.root / ".local/lab2"
        runtime = read_env(directory / "gateway.env")
        receivers = json.loads(runtime["GATEWAY_RECEIVERS"])
        credentials = json.loads(runtime["GATEWAY_SERVICE_TOKENS"])
        names = json.loads(runtime["GATEWAY_CALLER_NAMES"])
        self.assertEqual(names["university_record"], "university_record")
        self.assertEqual(names["discord-dms"], "discord-dms")
        self.assertEqual(runtime["GATEWAY_EXTERNAL_WS_URL"], "ws://localhost:18009")
        all_tokens = list(credentials.values()) + [value["HopToken"] for value in receivers.values()]
        self.assertEqual(len(all_tokens), len(set(all_tokens)))
        for owner in prepare_lab2.OWNERS:
            settings = read_env(directory / f"{owner}.env")
            if owner in ("player", "session"):
                self.assertEqual(settings["AUTH_MODE"], "gateway")
                self.assertEqual(settings["GATEWAY_ASSERTION_AUDIENCE"], receivers[owner]["Audience"])
                self.assertEqual(settings["GATEWAY_ASSERTION_ISSUER"], "student-id-gateway")
                self.assertEqual(json.loads(settings["SERVICE_TOKENS"]), {"gateway": receivers[owner]["HopToken"]})
                self.assertEqual(settings["MAX_CONCURRENT_TASKS"], "100")
                self.assertEqual(settings["TASK_TIMEOUT_SECONDS"], "30")
                self.assertNotIn("GATEWAY_JWKS_URL", settings)
                self.assertNotIn("PLAYER_JWKS_URL", settings)
                if owner == "session":
                    self.assertEqual(settings["GATEWAY_URL"], "http://gateway:8083")
                    self.assertEqual(settings["GATEWAY_SERVICE_TOKEN"], credentials["session"])
                    self.assertEqual(settings["JWT_PUBLIC_KEY_PATH"], "/keys/player-public.pem")
                continue
            self.assertEqual(settings["AUTH_MODE"], "gateway")
            self.assertEqual(settings["GATEWAY_HOP_TOKEN"], receivers[owner]["HopToken"])
            self.assertEqual(settings["GATEWAY_AUDIENCE"], receivers[owner]["Audience"])
            self.assertEqual(settings["GATEWAY_CALLER_TOKEN"], credentials[names[owner]])
            self.assertEqual(settings["GATEWAY_INTERNAL_URL"], "http://gateway:8083")
            if owner in ("applicant", "credential"):
                self.assertEqual(json.loads(settings["GATEWAY_JWKS_JSON"])["keys"][0]["kid"], "gateway-v1")
        rules = read_env(directory / "rules.env")
        self.assertEqual(rules["GATEWAY_RULES_RECEIVER_TOKEN"], receivers["rules"]["HopToken"])
        self.assertEqual(rules["RULES_SERVICE_TOKEN"], credentials["rules"])
        config = read_env(self.root / ".env")
        self.assertEqual(config["PLAYER_VERSION"], "2.0.1")
        self.assertEqual(config["SESSION_VERSION"], "2.0.0")
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_existing_configuration_is_never_overwritten(self):
        (self.root / ".env").write_text("existing development file")
        with self.assertRaisesRegex(ValueError, "unchanged"):
            prepare_lab2.prepare(self.root, "test/gateway:local")
        self.assertEqual((self.root / ".env").read_text(), "existing development file")
        self.assertFalse((self.root / ".local").exists())

    def test_missing_image_or_invalid_ports_create_nothing(self):
        for image, gateway_port, dms_port in (("", 8080, 8009), ("test/gateway:local", 8080, 8080),
                                               ("test/gateway:local", 0, 8009)):
            with self.assertRaises(ValueError):
                prepare_lab2.prepare(self.root, image, gateway_port, dms_port)
            self.assertFalse((self.root / ".env").exists())

    def test_compose_exposes_only_public_gateway_and_direct_dms(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertEqual(compose.count("    ports:\n"), 2)
        self.assertNotIn("http://session:8002", compose)
        self.assertNotIn("http://player:8001", compose)
        self.assertNotIn("EXTERNAL_SERVICES_MODE: mock", compose)
        self.assertNotIn("PLAYER_JWKS_URL:", compose)
        self.assertNotIn("OUTGOING_SERVICE_TOKEN:", compose)
        self.assertIn("GATEWAY_URL: http://gateway:8083", compose)
        self.assertIn("player-public.pem:/keys/player-public.pem:ro", compose)
        self.assertNotIn("player-public-key:", compose)
        self.assertIn("SPRING_PROFILES_ACTIVE: gateway", compose)
        self.assertIn("SESSION_URL: http://gateway:8083", compose)


if __name__ == "__main__":
    unittest.main()
