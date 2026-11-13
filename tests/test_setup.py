"""Check generated adapter configuration without Docker or private service checkouts."""
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup", ROOT / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def read_env(path):
    return {name: value[1:-1] for name, value in
            (line.split("=", 1) for line in path.read_text().splitlines())}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.keys = patch.object(setup, "rsa_pair", return_value={"keys": [{"kid": "gateway-v1"}]})
        self.keys.start()
        self.addCleanup(self.keys.stop)
        self.openssl = patch.object(setup.shutil, "which", return_value="openssl")
        self.openssl.start()
        self.addCleanup(self.openssl.stop)

    def test_runtime_and_current_receiver_adapters_match(self):
        setup.prepare(self.root, 28080, 18009)
        directory = self.root / ".local/stack"
        runtime = read_env(directory / "gateway.env")
        broker = read_env(directory / "broker.env")
        receivers = json.loads(broker["BROKER_RECEIVERS"])
        credentials = json.loads(broker["BROKER_SERVICE_TOKENS"])
        names = json.loads(broker["BROKER_CALLER_NAMES"])
        self.assertEqual(names, json.loads(runtime["GATEWAY_CALLER_NAMES"]))
        self.assertEqual(names["university_record"], "university_record")
        self.assertEqual(names["discord-dms"], "discord-dms")
        self.assertEqual(json.loads(runtime["GATEWAY_RECEIVERS"]),
                         {owner: {"Target": value["Target"], "Audience": value["Audience"]}
                          for owner, value in receivers.items()})
        self.assertEqual(set(receivers), set(setup.OWNERS))
        self.assertEqual(runtime["GATEWAY_BROKER_URL"], "http://message-broker:8080")
        self.assertEqual(runtime["BROKER_GRPC_URL"], "http://message-broker:50051")
        self.assertEqual(runtime["GATEWAY_BROKER_TOKEN"], broker["BROKER_GATEWAY_TOKEN"])
        for name in ("GATEWAY_SERVICE_TOKENS", "GATEWAY_EXTERNAL_WS_URL", "GATEWAY_PLAYER_URL", "GATEWAY_DMS_URL"):
            self.assertNotIn(name, runtime)
        self.assertEqual((broker["BROKER_SIGNING_KEY_FILE"], broker["BROKER_KEY_ID"]),
                         ("/keys/broker-private.pem", "broker-v1"))
        self.assertEqual((broker["BROKER_GATEWAY_PUBLIC_KEY_FILE"], broker["BROKER_GATEWAY_KEY_ID"]),
                         ("/keys/gateway-public.pem", "gateway-v1"))
        config = read_env(self.root / ".env")
        controls = [config[f"{name}_CONTROL_TOKEN"] for name in setup.CONTROL_NAMES]
        all_tokens = (list(credentials.values()) + [value["HopToken"] for value in receivers.values()] +
                      [broker["BROKER_GATEWAY_TOKEN"]] + controls)
        self.assertEqual(len(all_tokens), len(set(all_tokens)))
        self.assertTrue(all(len(token) >= 43 for token in all_tokens))
        for variable, caller in setup.CALLER_VARIABLES.items():
            self.assertEqual(config[variable], credentials[caller])
        for owner in setup.OWNERS:
            settings = read_env(directory / f"{owner}.env")
            self.assertEqual(settings["AUTH_MODE"], "gateway")
            self.assertEqual(settings["BROKER_HOP_TOKEN"], receivers[owner]["HopToken"])
            self.assertEqual(settings["BROKER_KEY_ID"], "broker-v1")
            self.assertEqual(settings["BROKER_ASSERTION_ISSUER"], "student-id-broker")
            self.assertNotIn("BROKER_URL", settings)
            for name in ("GATEWAY_HOP_TOKEN", "GATEWAY_RULES_RECEIVER_TOKEN", "SERVICE_TOKENS", "GATEWAY_URL",
                         "GATEWAY_SERVICE_TOKEN", "GATEWAY_INTERNAL_URL", "GATEWAY_CALLER_TOKEN",
                         "INTERNAL_GATEWAY_URL", "RULES_SERVICE_TOKEN"):
                self.assertNotIn(name, settings)
            if owner in ("applicant", "credential"):
                self.assertEqual(json.loads(settings["GATEWAY_JWKS_JSON"])["keys"][0]["kid"], "gateway-v1")
                self.assertIn("BROKER_JWKS_JSON", settings)
                self.assertNotIn("BROKER_PUBLIC_KEY_FILE", settings)
            else:
                self.assertEqual(settings["BROKER_PUBLIC_KEY_FILE"], "/keys/broker-public.pem")
            if owner in ("player", "moderation", "discord-dms"):
                self.assertNotIn("BROKER_SERVICE_TOKEN", settings)
            else:
                self.assertEqual(settings["BROKER_GRPC_URL"], "http://message-broker:50051")
                self.assertEqual(settings["BROKER_SERVICE_TOKEN"], credentials[names[owner]])
            if owner in ("player", "session"):
                self.assertEqual(settings["GATEWAY_ASSERTION_AUDIENCE"], receivers[owner]["Audience"])
                self.assertEqual(settings["GATEWAY_ASSERTION_ISSUER"], "student-id-gateway")
                self.assertEqual(settings["MAX_CONCURRENT_TASKS"], "100")
                self.assertEqual(settings["TASK_TIMEOUT_SECONDS"], "30")
                self.assertNotIn("GATEWAY_JWKS_URL", settings)
                self.assertNotIn("PLAYER_JWKS_URL", settings)
                if owner == "session":
                    self.assertEqual(settings["JWT_PUBLIC_KEY_PATH"], "/keys/player-public.pem")
                continue
            self.assertEqual(settings["GATEWAY_AUDIENCE"], receivers[owner]["Audience"])
        self.assertFalse([name for name in config if name.endswith("_IMAGE")])
        self.assertFalse([name for name in config if "INSTANCE_ID" in name or "REPLICA" in name])
        self.assertNotIn("COMPOSE_FILE", config)
        self.assertEqual(config["DMS_PORT"], "18009")
        self.assertNotIn("DMS_PORT_2", config)
        self.assertFalse((self.root / "compose.replicas.yaml").exists())
        self.assertEqual(config["DISCOVERY_DISCORD_WEBHOOK_URL"], "")
        self.assertGreaterEqual(len(config["BROKER_DB_PASSWORD"]), 43)
        self.assertFalse([name for name in config if "RABBITMQ" in name or name.endswith("_BROKER_PASSWORD")])
        self.assertNotIn("PLAYER_VERSION", config)
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_existing_configuration_is_never_overwritten(self):
        (self.root / ".env").write_text("existing development file")
        with self.assertRaisesRegex(ValueError, "unchanged"):
            setup.prepare(self.root)
        self.assertEqual((self.root / ".env").read_text(), "existing development file")
        self.assertFalse((self.root / ".local").exists())

    def test_invalid_ports_create_nothing(self):
        for ports in ((8080, 8080), (0, 8009), (8080, 70000), (70000, 8009)):
            with self.assertRaises(ValueError):
                setup.prepare(self.root, *ports)
            self.assertFalse((self.root / ".env").exists())

    def test_compose_images_default_to_latest(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertNotIn("_IMAGE:?", compose)
        self.assertEqual(len(re.findall(r"image: \$\{[A-Z_]+_IMAGE:-[a-z0-9._-]+/[a-z0-9._-]+:latest\}", compose)), 12)

    def test_bind_mounts_carry_the_shared_selinux_label(self):
        # On SELinux hosts such as Fedora, a bind mount without `z` is unreadable inside the container.
        # `Z` would give each file a private label, but the key files are shared by several services.
        mounts = re.findall(r"^\s+- (\./\S+)$", (ROOT / "compose.yaml").read_text(), re.MULTILINE)
        self.assertTrue(mounts)
        for mount in mounts:
            options = mount.rsplit(":", 1)[1].split(",")
            self.assertIn("z", options, mount)
            self.assertNotIn("Z", options, mount)

    def test_compose_exposes_only_public_gateway_and_chat_proxy(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertEqual(compose.count("    ports:\n"), 4)
        self.assertIn("      - '127.0.0.1:${GATEWAY_PORT:-8080}:8080'\n", compose)
        self.assertIn("      - '127.0.0.1:${DMS_PORT:-8009}:8009'\n", compose)
        self.assertNotIn("http://session:8002", compose)
        self.assertNotIn("http://player:8001", compose)
        self.assertNotIn("EXTERNAL_SERVICES_MODE: mock", compose)
        self.assertNotIn("PLAYER_JWKS_URL:", compose)
        self.assertNotIn("OUTGOING_SERVICE_TOKEN:", compose)
        self.assertNotIn("GATEWAY_URL:", compose)
        for name in ("GATEWAY_INTERNAL_URL", "INTERNAL_GATEWAY_URL", "PLAYER_URL:", "RULES_URL:"):
            self.assertNotIn(name, compose)
        self.assertIn("INSTANCE_HTTP_URL: http://gateway:8083", compose)
        self.assertIn("INSTANCE_HTTP_URL: http://message-broker:8080", compose)
        self.assertNotIn("BROKER_URL:", compose)
        self.assertEqual(compose.count("BROKER_GRPC_URL: http://message-broker:50051"), 4)
        self.assertIn("  DISCOVERY_GRPC_URL: http://discovery:50051\n", compose)
        for name in ("DISCOVERY_URL", "INSTANCE_WS_URL", "SESSION_URL:", "UNIVERSITY_URL:", "PLAYER_MODE:",
                     "EXTERNAL_SERVICES_MODE:", "DMS_PORT_2"):
            self.assertNotIn(name, compose)
        self.assertIn("player-public.pem:/keys/player-public.pem:ro", compose)
        self.assertNotIn("player-public-key:", compose)
        self.assertIn("SPRING_PROFILES_ACTIVE: gateway", compose)
        self.assertIn("broker-public.pem:/keys/broker-public.pem:ro", compose)
        self.assertNotIn("slot", compose)
        self.assertNotIn("pull_policy", compose)
        self.assertNotIn("INSTANCE_ID", compose)
        self.assertEqual(compose.count("INSTANCE_HTTP_URL"), 2)

    def test_events_use_the_broker_and_its_database(self):
        compose = (ROOT / "compose.yaml").read_text()
        for name in ("rabbitmq", "RABBITMQ", "BROKER_PRODUCERS", "_BROKER_PASSWORD", "broker-data:", "start_broker"):
            self.assertNotIn(name, compose)
        self.assertFalse((ROOT / "scripts/start_broker.sh").exists())
        self.assertIn("\n  broker-db:\n    image: postgres:17-alpine\n", compose)
        self.assertIn("      - broker-db-data:/var/lib/postgresql/data\n", compose)
        self.assertIn("BROKER_DATABASE_URL: postgres://broker:${BROKER_DB_PASSWORD:?", compose)
        self.assertRegex(compose, r"\n  moderation-publisher:\n(    .*\n)*      BROKER_SERVICE_TOKEN: "
                         r"\$\{MODERATION_SERVICE_TOKEN:\?")

    def test_domain_services_scale_natively(self):
        compose = (ROOT / "compose.yaml").read_text()
        for service in ("player", "session", "applicant", "credential", "university-record", "server-rules",
                        "moderation", "discord-dms"):
            self.assertRegex(compose, rf"\n  {service}:\n    deploy:\n      replicas: 2\n", service)
        self.assertEqual(compose.count("replicas: 2"), 8)
        self.assertIn("GATEWAY_CHAT_WS_URL: ws://localhost:${DMS_PORT:-8009}", compose)

    def test_monitoring_services_bind_to_localhost_and_publish_no_metrics_port(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertRegex(compose, r"\n  prometheus:\n(    .*\n|      .*\n)*    image: prom/prometheus:v3\.1\.0\n")
        self.assertRegex(compose, r"\n  grafana:\n(    .*\n|      .*\n)*    image: grafana/grafana:11\.4\.0\n")
        self.assertIn("      - '127.0.0.1:${PROMETHEUS_PORT:-9090}:9090'\n", compose)
        self.assertIn("      - '127.0.0.1:${GRAFANA_PORT:-3000}:3000'\n", compose)
        self.assertNotIn("9464:", compose.replace("':9464'", ""))
        self.assertEqual(compose.count("METRICS_ADDRESS: ':9464'"), 2)
        self.assertIn("      GF_AUTH_ANONYMOUS_ENABLED: 'false'\n", compose)
        self.assertIn("      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?", compose)
        self.assertIn("--storage.tsdb.retention.time=2d", compose)
        self.assertIn("  prometheus-data:\n", compose)
        self.assertNotIn("grafana-data", compose)
        self.assertEqual(compose.count('"prometheus":"${PROMETHEUS_CONTROL_TOKEN:?'), 1)
        discovery = compose.split("\n  discovery:\n", 1)[1].split("\n  player-db:", 1)[0]
        self.assertIn('"prometheus":"${PROMETHEUS_CONTROL_TOKEN:?', discovery)
        registration = compose.split("\nservices:", 1)[0]
        self.assertNotIn("PROMETHEUS_CONTROL_TOKEN", registration)

    def test_prometheus_and_grafana_configuration_follow_the_contract(self):
        prometheus = (ROOT / "config/prometheus/prometheus.yml").read_text()
        self.assertIn("url: http://discovery:8081/sd/v1/targets", prometheus)
        self.assertIn("files: [/etc/prometheus/control-token]", prometheus)
        self.assertIn("scrape_interval: 5s", prometheus)
        self.assertNotIn("relabel", prometheus)
        datasource = (ROOT / "config/grafana/provisioning/datasources/prometheus.yaml").read_text()
        self.assertIn("uid: prometheus", datasource)
        self.assertIn("url: http://prometheus:9090", datasource)
        self.assertIn("allowUiUpdates: false", (ROOT / "config/grafana/provisioning/dashboards/student-id.yaml").read_text())
        for name, uid, panels in (("services", "student-id-services", 10), ("broker", "student-id-broker", 15)):
            dashboard = json.loads((ROOT / f"config/grafana/dashboards/{name}.json").read_text())
            self.assertEqual(dashboard["uid"], uid)
            self.assertEqual(len(dashboard["panels"]), panels)
            self.assertEqual(dashboard["templating"]["list"][0]["definition"],
                             "label_values(student_id_requests_total, service)")
            for panel in dashboard["panels"]:
                self.assertEqual(panel["datasource"]["uid"], "prometheus")
                self.assertTrue(all(target["expr"] for target in panel["targets"]))

    def test_log_collection_is_read_only_bounded_and_unpublished(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertRegex(compose, r"\n  loki:\n(    .*\n|      .*\n)*    image: grafana/loki:3\.3\.2\n")
        self.assertRegex(compose, r"\n  promtail:\n(    .*\n|      .*\n)*    image: grafana/promtail:3\.3\.2\n")
        loki = compose.split("\n  loki:\n", 1)[1].split("\n  promtail:\n", 1)[0]
        promtail = compose.split("\n  promtail:\n", 1)[1].split("\n  grafana:\n", 1)[0]
        self.assertNotIn("ports:", loki)
        self.assertNotIn("ports:", promtail)
        self.assertIn(":/var/lib/docker/containers:ro\n", promtail)
        self.assertNotIn("docker.sock", compose)
        self.assertIn("  loki-data:\n", compose)
        self.assertIn("retention_period: 72h", (ROOT / "config/loki/loki.yml").read_text())
        promtail_config = (ROOT / "config/promtail/promtail.yml").read_text()
        self.assertIn("/var/lib/docker/containers/*/*-json.log", promtail_config)
        self.assertIn("url: http://loki:3100/loki/api/v1/push", promtail_config)
        self.assertEqual(re.findall(r"labels:\n((?:          \w+:\n)+)", promtail_config)[0].split(), ["service:", "level:"])
        datasource = (ROOT / "config/grafana/provisioning/datasources/loki.yaml").read_text()
        self.assertIn("uid: loki", datasource)
        self.assertIn("url: http://loki:3100", datasource)
        dashboard = json.loads((ROOT / "config/grafana/dashboards/logs.json").read_text())
        self.assertEqual(dashboard["uid"], "student-id-logs")
        self.assertEqual([variable["name"] for variable in dashboard["templating"]["list"]], ["service", "level", "search"])
        self.assertEqual([panel["type"] for panel in dashboard["panels"]], ["timeseries", "logs"])
        for panel in dashboard["panels"]:
            self.assertEqual(panel["datasource"]["uid"], "loki")
            self.assertTrue(all(target["expr"] for target in panel["targets"]))

    def test_monitoring_secrets_are_generated_and_the_token_file_is_readable(self):
        setup.prepare(self.root)
        config = read_env(self.root / ".env")
        self.assertGreaterEqual(len(config["GRAFANA_ADMIN_PASSWORD"]), 43)
        token_file = self.root / ".local/stack/prometheus-control-token"
        self.assertEqual(token_file.read_text(), config["PROMETHEUS_CONTROL_TOKEN"])
        self.assertEqual(token_file.stat().st_mode & 0o777, 0o444)
        others = [value for name, value in config.items() if name.endswith("_CONTROL_TOKEN")
                  and name != "PROMETHEUS_CONTROL_TOKEN"]
        self.assertNotIn(config["PROMETHEUS_CONTROL_TOKEN"], others)

    def test_chat_proxy_balances_dms_replicas(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertRegex(compose, r"\n  dms-proxy:\n(    .*\n)*    image: caddy:2\.8-alpine\n")
        self.assertIn("./config/dms-proxy.Caddyfile:/etc/caddy/Caddyfile:ro,z", compose)
        self.assertRegex(compose, r"\n  dms-proxy:\n(    .*\n|      .*\n)*    depends_on:\n      discord-dms:\n"
                         r"        condition: service_healthy\n")
        caddyfile = (ROOT / "config/dms-proxy.Caddyfile").read_text()
        self.assertIn("dynamic a discord-dms 8000", caddyfile)
        self.assertIn("lb_policy least_conn", caddyfile)


if __name__ == "__main__":
    unittest.main()
