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
        cls.rows = list(combined.values())

    def test_nine_unique_published_sources_and_native_images(self):
        self.assertEqual(len(self.rows), 9)
        self.assertEqual(len({row["submodule"] for row in self.rows}), 9)
        self.assertEqual({row["service"] for row in self.rows},
                         {"player", "session", "moderation", "applicant", "credential", "rules", "university_record", "gateway", "discovery"})
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
        self.assertEqual(pairs, services)
        self.assertNotIn("discovery", pairs)
        self.assertNotIn("discord-dms", pairs)
        self.assertFalse(any(word in text for word in ["environment:", "ports:", "build:", "volumes:"]))

    def test_absent_source_label_and_unfinished_dms_are_explicit(self):
        missing = [row for row in self.rows if not row["repository_source_labels_verified"]]
        self.assertEqual([row["service"] for row in missing], ["moderation"])
        self.assertIn("Repository-source labels are absent", missing[0]["repository_source_evidence"])
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


if __name__ == "__main__":
    unittest.main()
