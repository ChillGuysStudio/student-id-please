"""Check recorded image and Git pointer consistency, not a live registry or runtime."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"


class PublishedIncrement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads((ROOT / "docs/releases/lab3-increment-20261027.json").read_text())
        cls.update = json.loads((ROOT / "docs/releases/lab3-package-updates-20261028.json").read_text())
        combined = {row["service"]: row for row in cls.record["services"]}
        combined.update({row["service"]: row for row in cls.update["updates"]})
        cls.negotiation = json.loads((ROOT / "docs/releases/lab3-gateway-negotiation-20261028.json").read_text())
        combined.update({row["service"]: row for row in cls.negotiation["updates"]})
        cls.completion = json.loads((ROOT / "docs/releases/lab3-completion-packages-20261028.json").read_text())
        combined.update({row["service"]: row for row in cls.completion["updates"]})
        cls.dms = json.loads((ROOT / "docs/releases/lab3-dms-official-package-20261028.json").read_text())
        combined.update({row["service"]: row for row in cls.dms["updates"]})
        cls.moderation = json.loads((ROOT / "docs/releases/lab3-moderation-3.0.5-20261028.json").read_text())
        combined.update({row["service"]: row for row in cls.moderation["updates"]})
        cls.rows = list(combined.values())

    def test_ten_unique_published_sources_and_native_images(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(len({row["submodule"] for row in self.rows}), 10)
        self.assertEqual({row["service"] for row in self.rows},
                         {"player", "session", "moderation", "applicant", "credential", "rules", "university_record", "gateway", "discovery", "discord-dms"})
        for row in self.rows:
            self.assertRegex(row["source_sha"], "^" + SHA + "$")
            self.assertRegex(row["version"], r"^3\.0\.[0-9]+$")
            self.assertRegex(row["image"], r"^[a-z0-9._-]+/[a-z0-9._-]+@" + DIGEST + "$")
            self.assertGreater(row["publication_run"], 0)
            self.assertEqual(set(row["platforms"]), {"amd64", "arm64"})
            self.assertEqual(len(set(row["platforms"].values())), 2)
            for value in row["platforms"].values():
                self.assertRegex(value, "^" + DIGEST + "$")

    def test_index_gitlinks_match_without_fetching_private_sources(self):
        # The index is present in ordinary CI checkouts even when private
        # submodules remain uninitialized. Do not read private source trees.
        raw = subprocess.check_output(["git", "ls-files", "--stage"], cwd=ROOT, text=True)
        gitlinks = {line.split("\t", 1)[1]: line.split()[1]
                    for line in raw.splitlines() if line.startswith("160000 ")}
        for row in self.rows:
            self.assertEqual(gitlinks[row["submodule"]], row["source_sha"])

    def test_overlay_selects_only_existing_images(self):
        text = (ROOT / "compose.published.yaml").read_text()
        pairs = dict(re.findall(r"^  ([a-z0-9-]+):\n    image: ([^\s]+)$", text, re.MULTILINE))
        services = {row["service"]: row["image"] for row in self.rows if row["service"] != "discovery"}
        services["server-rules"] = services.pop("rules")
        services["university-record"] = services.pop("university_record")
        services["moderation-publisher"] = services["moderation"]
        for name in ["player", "session", "moderation", "discord-dms", "applicant", "credential",
                     "server-rules", "university-record"]:
            services[name + "-slot-2"] = services[name]
        self.assertEqual(pairs, services)
        self.assertNotIn("discovery", pairs)
        self.assertFalse(any(word in text for word in ["environment:", "ports:", "build:", "volumes:"]))

    def test_absent_source_labels_and_historical_dms_exclusion_are_explicit(self):
        missing = [row for row in self.rows if not row["repository_source_labels_verified"]]
        self.assertEqual({row["service"] for row in missing}, {"moderation", "discord-dms"})
        self.assertIn("Repository-source labels are absent", next(row for row in missing if row["service"] == "moderation")["repository_source_evidence"])
        self.assertFalse(self.record["cumulative_grade_claimed"])
        self.assertEqual([row["service"] for row in self.record["excluded"]], ["discord-dms"])
        self.assertIn(198, self.record["excluded"][0]["issues"])

    def test_previous_release_is_preserved_and_updates_do_not_claim_dms_publication(self):
        self.assertEqual(self.update["previous_inventory"], "lab3-increment-20261027.json")
        self.assertEqual(self.update["previous_cpr_release"], "v3.0.0")
        self.assertEqual(self.update["previous_cpr_source"], "80e0063a75d898573396596f1fd10c6b83526ec5")
        self.assertEqual({row["service"] for row in self.update["updates"]},
                         {"session", "credential", "moderation", "university_record"})
        self.assertFalse(self.update["cumulative_grade_claimed"])
        native = self.update["dms_native_runtime_only"]
        for key in ["official_version_or_channels_verified", "canonical_pointer_updated", "breaker_task_169_included"]:
            self.assertFalse(native[key])
        old_session = next(row for row in self.record["services"] if row["service"] == "session")
        self.assertEqual(old_session["version"], "3.0.7")

    def test_negotiation_increment_records_actual_ports_without_promoting_dms(self):
        self.assertEqual(self.negotiation["previous_cpr_release"], "v3.0.1")
        self.assertEqual(self.negotiation["previous_inventory"], "lab3-package-updates-20261028.json")
        self.assertEqual([row["service"] for row in self.negotiation["updates"]], ["gateway"])
        self.assertFalse(self.negotiation["cumulative_grade_claimed"])
        runtime = self.negotiation["runtime"]
        self.assertEqual(runtime["selected_dms_ports"], [8009, 18009])
        self.assertEqual(runtime["actual_cross_replica_messages"], 2)
        self.assertFalse(runtime["duplicate_frame_created_extra_message"])
        self.assertEqual(runtime["consumed_ticket_reuse_http"], 401)
        self.assertFalse(runtime["official_dms_release_reconciliation_claimed"])
        self.assertEqual(runtime["websocket_frames_through_gateway"], 0)

    def test_completion_packages_advance_gateway_and_rules_without_claiming_grade(self):
        self.assertEqual(self.completion["previous_cpr_release"], "v3.0.2")
        self.assertEqual(self.completion["previous_inventory"], "lab3-gateway-negotiation-20261028.json")
        self.assertEqual({row["service"] for row in self.completion["updates"]}, {"gateway", "rules"})
        self.assertFalse(self.completion["cumulative_grade_claimed"])
        runtime = self.completion["runtime_updates"]
        self.assertTrue(runtime["python_startup_logging_verified"])
        self.assertEqual(runtime["python_slots_verified"], 8)
        self.assertTrue(runtime["ticket_and_bearer_redacted_in_logs"])
        self.assertFalse(runtime["all_logging_event_classes_claimed"])
        self.assertTrue(runtime["dms_post_restart_history_verified"])
        self.assertEqual(runtime["dms_messages_retained_once"], 2)
        self.assertFalse(runtime["simultaneous_first_write_races_executed"])
        self.assertFalse(runtime["official_dms_release_reconciliation_claimed"])

    def test_dms_official_provenance_and_historical_runtime(self):
        self.assertEqual(self.dms["previous_inventory"], "lab3-completion-packages-20261028.json")
        self.assertEqual(self.dms["previous_cpr_release"], "v3.0.3")
        row, = self.dms["updates"]
        self.assertEqual(row["source_sha"], "9624f8810cce570337068da81b22b7d8b1a40feb")
        self.assertEqual(row["image"], "sentientmoss/pad-discord-dms-service@sha256:4c2c3ed603a0c4f8ce5dfafcf3363fdc0dac83c4f15c966be33fd5b8f06a65ff")
        self.assertEqual(row["release_tag_object"], "102f3ef0110f5538b1938fba31c231e1e305907e")
        self.assertEqual(row["publication_run"], 40694772096)
        self.assertEqual(row["sync_run"], 40694772798)
        self.assertEqual(row["verified_aliases"], ["3.0.1", "latest", "lab-3"])
        self.assertEqual(row["platforms"], {"amd64": "sha256:2001f31a34f3f9f5ad8005c4777ef4f3b911cf968908f14651526ccf03112201", "arm64": "sha256:7d3a5a1f558640c48c0e38a56149cc92fdf4b96c3621ae458a0abb4282c88e9f"})
        self.assertEqual(row["configs"], {"amd64": "sha256:cc0363db64405a16840c0ab82ef636b0a316e7130712bb92e54b2b91bb9d6d37", "arm64": "sha256:df6c8021272d05864a626b681de45171f9d8424fc23db8099c0e5d42cc6af24c"})
        self.assertEqual(row["revision_labels"], {arch: row["source_sha"] for arch in ("amd64", "arm64")})
        self.assertFalse(row["repository_source_labels_verified"])
        self.assertTrue(self.dms["sync"]["content_only_no_op"])
        self.assertTrue(self.dms["sync"]["dev_is_ancestor_of_main"])
        self.assertFalse(self.dms["sync"]["branch_heads_identical"])
        self.assertFalse(self.dms["runtime_rollout_verified"])
        runtime = self.dms["runtime"]
        self.assertEqual(runtime["running_version"], "3.0.0")
        self.assertEqual(runtime["running_source_sha"], self.update["dms_native_runtime_only"]["source_sha"])
        self.assertEqual(runtime["running_image"], self.update["dms_native_runtime_only"]["image"])
        self.assertEqual(runtime["running_slots"], 2)
        self.assertEqual(runtime["rollout_status"], "blocked_after_two_preflight_attempts")
        self.assertFalse(runtime["runtime_mutated"])
        self.assertFalse(runtime["live_breaker_acceptance_tested"])
        self.assertFalse(self.dms["cumulative_grade_claimed"])
        self.assertEqual(self.update["dms_native_runtime_only"]["source_sha"], "474eab2233dd85641f2aedac518661a24b1edf25")
        self.assertTrue(self.update["dms_native_runtime_only"]["image"].endswith("sha256:2f07ff156e99603e05eca9f2e535ed98e72d2068c4a788b6ff53a53853f13970"))

    def test_moderation_3_0_5_is_official_and_api_and_publisher_share_it(self):
        self.assertEqual(self.moderation["previous_inventory"], "lab3-dms-official-package-20261028.json")
        row, = self.moderation["updates"]
        self.assertEqual(row["version"], "3.0.5")
        self.assertEqual(row["source_sha"], "11ec1207af4a45d79c61527914b45e712077d554")
        self.assertEqual(row["verified_aliases"], ["3.0.5", "latest", "lab-3"])
        self.assertFalse(row["repository_source_labels_verified"])
        self.assertFalse(self.moderation["cumulative_grade_claimed"])
        text = (ROOT / "compose.published.yaml").read_text()
        self.assertEqual(text.count(row["image"]), 3)


if __name__ == "__main__":
    unittest.main()
