"""Exercise registry cleanup with mocked HTTP requests, never live deletion."""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dockerhub_cleanup", ROOT / ".github/actions/dockerhub-cleanup/cleanup.py")
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)
IMAGE = "example/service"


class CleanupTests(unittest.TestCase):
    def run_cleanup(self, tags, **kwargs):
        hub = Mock()
        retained = {tag for tag in tags if cleanup.ALLOWED.fullmatch(tag)}
        hub.tags.side_effect = [set(tags), retained]
        with redirect_stdout(io.StringIO()):
            result = cleanup.cleanup(hub, IMAGE, **kwargs)
        return hub, result

    def test_only_latest_versions_and_versioned_architectures_are_retained(self):
        for tag in ["latest", "0.0.0", "4.0.0", "12.3.456", "4.0.0-amd64", "4.0.0-arm64"]:
            with self.subTest(tag=tag):
                self.assertIsNotNone(cleanup.ALLOWED.fullmatch(tag))
        for tag in ["4", "4.0", "v4.0.0", "04.0.0", "4.00.0", "4.0.00", "4.0.0\n",
                    "4.0.0-rc.1", "0.1.0-SNAPSHOT", "dev", "test", "build-123-1", "lab-4",
                    "sha-" + "a" * 40, "sha-abc-run-123-1-amd64", "latest-amd64", "arm64",
                    "4.0.0-armv7", "4.0.0+build.1"]:
            with self.subTest(tag=tag):
                self.assertIsNone(cleanup.ALLOWED.fullmatch(tag))

    def test_preview_never_authenticates_or_deletes(self):
        hub, result = self.run_cleanup(["latest", "4.0.0", "lab-4", "build-1-1"])
        self.assertEqual(result, ["build-1-1", "lab-4"])
        hub.login.assert_not_called()
        hub.delete_tag.assert_not_called()

    def test_delete_preserves_all_versions_and_supported_architecture_tags(self):
        tags = ["latest", "1.0.0", "4.0.0", "4.0.0-amd64", "4.0.0-arm64", "lab-4", "build-1-1"]
        hub, _ = self.run_cleanup(tags, delete=True, confirmation=IMAGE, username="user", token="secret")
        hub.login.assert_called_once_with("user", "secret")
        self.assertEqual(hub.delete_tag.call_args_list, [call(IMAGE, "build-1-1"), call(IMAGE, "lab-4")])

    def test_delete_requires_exact_confirmation_and_credentials_before_network(self):
        for values in [{}, {"confirmation": "other/service", "username": "u", "token": "p"},
                       {"confirmation": IMAGE, "username": "u"}, {"confirmation": IMAGE, "token": "p"}]:
            hub = Mock()
            with self.subTest(values=values), self.assertRaises(ValueError):
                cleanup.cleanup(hub, IMAGE, delete=True, **values)
            self.assertEqual(hub.mock_calls, [])

    def test_invalid_repository_is_rejected_before_network(self):
        for image in ["", "service", "example/service:latest", "example/service@sha256:abc",
                      "example/service/other", "example/../service", "https://hub.docker.com/example/service"]:
            hub = Mock()
            with self.subTest(image=image), self.assertRaises(ValueError):
                cleanup.cleanup(hub, image)
            self.assertEqual(hub.mock_calls, [])

    def test_no_delete_without_a_version_and_latest(self):
        for tags in [["latest", "junk"], ["4.0.0", "junk"], ["junk"]]:
            hub = Mock()
            hub.tags.return_value = set(tags)
            with redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                cleanup.cleanup(hub, IMAGE, delete=True, confirmation=IMAGE, username="u", token="p")
            hub.delete_tag.assert_not_called()

    def test_incomplete_listing_cannot_delete_anything(self):
        hub = Mock()
        hub.tags.side_effect = RuntimeError("listing failed")
        with self.assertRaises(RuntimeError):
            cleanup.cleanup(hub, IMAGE, delete=True, confirmation=IMAGE, username="u", token="p")
        hub.delete_tag.assert_not_called()

    def test_delete_error_fails_without_claiming_success(self):
        hub = Mock()
        hub.tags.return_value = {"latest", "4.0.0", "junk"}
        hub.delete_tag.side_effect = RuntimeError("forbidden")
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(RuntimeError):
            cleanup.cleanup(hub, IMAGE, delete=True, confirmation=IMAGE, username="u", token="p")
        self.assertNotIn("DELETED", output.getvalue())

    def test_readback_rejects_leftover_junk_or_missing_retained_tags(self):
        for remaining in [{"latest", "4.0.0", "junk"}, {"latest"}]:
            hub = Mock()
            hub.tags.side_effect = [{"latest", "4.0.0", "junk"}, remaining]
            with redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                cleanup.cleanup(hub, IMAGE, delete=True, confirmation=IMAGE, username="u", token="p")

    def test_invalid_delete_environment_is_not_truthy(self):
        with patch.dict(cleanup.os.environ, {"DOCKERHUB_DELETE": "yes"}), patch.object(cleanup, "Hub") as hub:
            with self.assertRaises(ValueError):
                cleanup.main()
            hub.assert_not_called()


class HubTests(unittest.TestCase):
    def test_pagination_is_complete_and_never_follows_server_urls(self):
        hub = cleanup.Hub()
        hub.request = Mock(side_effect=[{"results": [{"name": "latest"}], "next": "https://other.invalid/"},
                                        {"results": [{"name": "4.0.0"}], "next": None}])
        self.assertEqual(hub.tags(IMAGE), {"latest", "4.0.0"})
        self.assertEqual(hub.request.call_args_list,
                         [call(f"/v2/repositories/{IMAGE}/tags/?page_size=100&page=1"),
                          call(f"/v2/repositories/{IMAGE}/tags/?page_size=100&page=2")])

    def test_malformed_tag_pages_fail_closed(self):
        for response in [None, {}, {"results": []}, {"results": "invalid", "next": None},
                         {"results": [{"name": "../other"}], "next": None}]:
            hub = cleanup.Hub()
            hub.request = Mock(return_value=response)
            with self.subTest(response=response), self.assertRaises(ValueError):
                hub.tags(IMAGE)

    def test_tag_deletion_never_addresses_a_digest(self):
        hub = cleanup.Hub()
        hub.request = Mock()
        hub.delete_tag(IMAGE, "junk")
        hub.request.assert_called_once_with(f"/v2/repositories/{IMAGE}/tags/junk/", "DELETE")

    def test_http_errors_hide_response_bodies_and_credentials(self):
        hub = cleanup.Hub()
        hub.opener.open = Mock(side_effect=HTTPError("https://hub.docker.com/", 403, "secret-value", {}, None))
        with self.assertRaisesRegex(RuntimeError, "delete permission") as raised:
            hub.request("/v2/auth/token", "POST", {"secret": "secret-value"})
        self.assertNotIn("secret-value", str(raised.exception))

    def test_already_deleted_tag_is_idempotent_but_listing_404_is_not(self):
        hub = cleanup.Hub()
        hub.opener.open = Mock(side_effect=HTTPError("https://hub.docker.com/", 404, "missing", {}, None))
        self.assertIsNone(hub.request("/tags/junk/", "DELETE"))
        with self.assertRaises(RuntimeError):
            hub.request("/tags/")

    def test_auth_uses_short_lived_bearer_without_printing_it(self):
        hub = cleanup.Hub()
        hub.request = Mock(return_value={"access_token": "bearer-secret"})
        hub.login("user", "personal-secret")
        hub.request.assert_called_once_with("/v2/auth/token", "POST", {"identifier": "user", "secret": "personal-secret"})
        self.assertEqual(hub.token, "bearer-secret")

    def test_credentials_cannot_be_forwarded_on_redirect(self):
        self.assertIsNone(cleanup.NoRedirect().redirect_request(None, None, 307, "", {}, "https://other.invalid/"))

    def test_delete_request_uses_bearer_and_no_manifest_endpoint(self):
        hub = cleanup.Hub()
        hub.token = "bearer-secret"
        response = Mock()
        response.read.return_value = b""
        hub.opener.open = Mock()
        hub.opener.open.return_value.__enter__ = Mock(return_value=response)
        hub.opener.open.return_value.__exit__ = Mock(return_value=False)
        hub.delete_tag(IMAGE, "junk")
        request = hub.opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(request.full_url, f"https://hub.docker.com/v2/repositories/{IMAGE}/tags/junk/")
        self.assertEqual(request.headers["Authorization"], "Bearer bearer-secret")


if __name__ == "__main__":
    unittest.main()
