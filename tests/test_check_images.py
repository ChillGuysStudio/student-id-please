import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_images", ROOT / "scripts/check_images.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

SHA = "a" * 40
ROW = {"service": "player", "version": "5.0.6", "image": "owner/player@sha256:" + "1" * 64, "source_sha": SHA}
GOOD_LABELS = {"org.opencontainers.image.revision": SHA, "org.opencontainers.image.source": "https://github.com/owner/player"}


class CheckImages(unittest.TestCase):
    def good(self):
        digest = ROW["image"].split("@")[1]
        return {"5.0.6": digest, "latest": digest}, list(check.PLATFORMS), {p: dict(GOOD_LABELS) for p in check.PLATFORMS}

    def test_a_pinned_release_passes(self):
        self.assertEqual(check.check(ROW, *self.good()), [])

    def test_moved_tags_fail(self):
        tags, platforms, labels = self.good()
        tags["latest"] = "sha256:" + "2" * 64
        del tags["5.0.6"]
        self.assertEqual(check.check(ROW, tags, platforms, labels),
                         ["5.0.6 is not the pinned index", "latest is not the pinned index"])

    def test_a_missing_platform_and_wrong_label_fail(self):
        tags, _, labels = self.good()
        labels["linux/arm64"]["org.opencontainers.image.revision"] = "b" * 40
        problems = check.check(ROW, tags, ["linux/amd64"], labels)
        self.assertIn("platforms are linux/amd64", problems)
        self.assertIn("linux/arm64 revision label is not aaaaaaa", problems)

    def test_policy_allows_only_versions_latest_and_platform_versions(self):
        allowed = ["latest", "5.0.6", "10.0.0", "5.0.6-amd64", "5.0.6-arm64"]
        refused = ["lab-3", "sha-" + SHA, "build-1-1", "05.0.1", "5.0", "5.0.6-rc1", "latest-amd64", "5.0.6-s390x"]
        self.assertTrue(all(check.POLICY.match(name) for name in allowed))
        self.assertFalse(any(check.POLICY.match(name) for name in refused))


if __name__ == "__main__":
    unittest.main()
