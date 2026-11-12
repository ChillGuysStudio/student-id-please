"""Remove nonconforming Docker Hub tag names, never registry manifests by digest."""

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = rf"{NUMBER}\.{NUMBER}\.{NUMBER}"
ALLOWED = re.compile(rf"(?:latest|{VERSION}(?:-(?:amd64|arm64))?)\Z")
TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
REPOSITORY = re.compile(r"[a-z0-9][a-z0-9_-]*/[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
HUB = "https://hub.docker.com"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Hub:
    def __init__(self):
        self.opener = build_opener(NoRedirect)
        self.token = None

    def request(self, path, method="GET", body=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = Request(HUB + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            if method == "DELETE" and error.code == 404:
                return None
            detail = " Check the token's repository delete permission." if error.code == 403 else ""
            raise RuntimeError(f"Docker Hub {method} failed with HTTP {error.code}.{detail}") from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError(f"Docker Hub {method} connection failed.") from None
        return json.loads(raw) if raw else None

    def login(self, username, token):
        result = self.request("/v2/auth/token", "POST", {"identifier": username, "secret": token})
        if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"]:
            raise ValueError("Docker Hub did not return an access token.")
        self.token = result["access_token"]

    def tags(self, repository):
        tags = set()
        for page in range(1, 1001):
            result = self.request(f"/v2/repositories/{repository}/tags/?page_size=100&page={page}")
            if not isinstance(result, dict) or not isinstance(result.get("results"), list) or "next" not in result:
                raise ValueError("Docker Hub returned an invalid tag page. No cleanup plan is available.")
            for item in result["results"]:
                name = item.get("name") if isinstance(item, dict) else None
                if not isinstance(name, str) or not TAG.fullmatch(name):
                    raise ValueError("Docker Hub returned an invalid tag name.")
                tags.add(name)
            if not result["next"]:
                return tags
            # Construct every page locally. Never send credentials to a pagination URL.
        raise ValueError("Docker Hub tag listing exceeded 1000 pages.")

    def delete_tag(self, repository, tag):
        self.request(f"/v2/repositories/{repository}/tags/{tag}/", "DELETE")


def cleanup(hub, repository, *, delete=False, confirmation="", username="", token=""):
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("Use one explicit Docker Hub namespace/repository, without a tag or digest.")
    if delete and (confirmation != repository or not username or not token):
        raise ValueError("Deletion requires an exact repository confirmation and Docker Hub credentials.")
    if delete:
        hub.login(username, token)
    tags = hub.tags(repository)
    junk = sorted(tag for tag in tags if not ALLOWED.fullmatch(tag))
    print(f"{repository}: {len(tags)} tags, {len(tags) - len(junk)} retained, {len(junk)} nonconforming.")
    for tag in sorted(tags):
        print(f"{'WOULD DELETE' if tag in junk else 'KEEP'} {repository}:{tag}")
    if not delete or not junk:
        return junk
    if "latest" not in tags or not any(re.fullmatch(VERSION, tag) for tag in tags):
        raise ValueError("Refusing deletion without latest and at least one conventional version tag.")
    for tag in junk:
        hub.delete_tag(repository, tag)
        print(f"DELETED {repository}:{tag}")
    remaining = hub.tags(repository)
    if tags.difference(junk).difference(remaining):
        raise RuntimeError("A retained tag disappeared during cleanup. Investigate concurrent registry changes.")
    if any(not ALLOWED.fullmatch(tag) for tag in remaining):
        raise RuntimeError("Nonconforming tags remain after cleanup. Inspect the publisher before retrying.")
    print(f"Deleted {len(junk)} nonconforming tags. All retained tag names are still present.")
    return junk


def main():
    delete = os.environ.get("DOCKERHUB_DELETE", "false")
    if delete not in {"true", "false"}:
        raise ValueError("DOCKERHUB_DELETE must be true or false.")
    cleanup(Hub(), os.environ.get("DOCKERHUB_REPOSITORY", ""), delete=delete == "true",
            confirmation=os.environ.get("DOCKERHUB_CONFIRM_REPOSITORY", ""),
            username=os.environ.get("DOCKERHUB_USERNAME", ""), token=os.environ.get("DOCKERHUB_TOKEN", ""))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
