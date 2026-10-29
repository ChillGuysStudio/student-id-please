"""Check recorded image and Git pointer consistency, not a live registry or runtime."""
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
IMAGE_KEYS = {"gateway": "GATEWAY", "discovery": "DISCOVERY", "player": "PLAYER", "session": "SESSION",
              "moderation": "MODERATION", "discord-dms": "DISCORD_DMS", "applicant": "APPLICANT",
              "credential": "CREDENTIAL", "rules": "SERVER_RULES", "university_record": "UNIVERSITY_RECORD"}


class ServiceReleases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / "docs/releases/services.json").read_text())["services"]

    def test_ten_unique_services_and_native_images(self):
        self.assertEqual(len(self.rows), 10)
        self.assertEqual(len({row["service"] for row in self.rows}), 10)
        self.assertEqual(len({row["submodule"] for row in self.rows}), 10)
        self.assertEqual({row["service"] for row in self.rows}, set(IMAGE_KEYS))
        for row in self.rows:
            self.assertRegex(row["source_sha"], "^" + SHA + "$")
            self.assertRegex(row["version"], r"^[0-9]+\.[0-9]+\.[0-9]+$")
            self.assertRegex(row["image"], r"^[a-z0-9._-]+/[a-z0-9._-]+@" + DIGEST + "$")
            self.assertGreater(row["publication_run"], 0)
            self.assertEqual(set(row["platforms"]), {"amd64", "arm64"})
            self.assertEqual(len(set(row["platforms"].values())), 2)
            for value in [*row["platforms"].values(), *row.get("configs", {}).values()]:
                self.assertRegex(value, "^" + DIGEST + "$")
            if "revision_labels" in row:
                self.assertEqual(set(row["revision_labels"].values()), {row["source_sha"]})

    def test_index_gitlinks_match_without_fetching_private_sources(self):
        # The index is present in ordinary CI checkouts even when private
        # submodules remain uninitialized. Do not read private source trees.
        raw = subprocess.check_output(["git", "ls-files", "--stage"], cwd=ROOT, text=True)
        gitlinks = {line.split("\t", 1)[1]: line.split()[1]
                    for line in raw.splitlines() if line.startswith("160000 ")}
        for row in self.rows:
            self.assertEqual(gitlinks[row["submodule"]], row["source_sha"])

    def test_compose_image_fallbacks_match_recorded_repositories(self):
        compose = (ROOT / "compose.yaml").read_text()
        fallbacks = {}
        for key, repo in re.findall(r"image: \$\{([A-Z_]+_IMAGE):-([^:}]+):latest\}", compose):
            fallbacks.setdefault(key, set()).add(repo)
        for row in self.rows:
            repo = row["image"].split("@", 1)[0]
            self.assertEqual(fallbacks[IMAGE_KEYS[row["service"]] + "_IMAGE"], {repo})

    def test_unverified_source_labels_carry_evidence(self):
        for row in self.rows:
            if not row["repository_source_labels_verified"]:
                self.assertTrue(row["repository_source_evidence"])


if __name__ == "__main__":
    unittest.main()
