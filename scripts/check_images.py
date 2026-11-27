#!/usr/bin/env python3
"""Check every pinned service image on Docker Hub without credentials.

For each row of docs/releases/services.json, check that the version tag and
`latest` point to the pinned release index, that the index has native
linux/amd64 and linux/arm64 images, and that their source labels name the
pinned source commit. List every tag outside the naming policy. The check
reads only; it deletes nothing. It needs `docker buildx` and network access.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
POLICY = re.compile(r"^(latest|(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-(amd64|arm64))?)$")
PLATFORMS = ["linux/amd64", "linux/arm64"]


def hub(url):
    request = urllib.request.Request(url, headers={"User-Agent": "student-id-image-check"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def tags(repository):
    """Return {tag: index digest} for every tag of a Docker Hub repository."""
    found, url = {}, f"https://hub.docker.com/v2/repositories/{repository}/tags?page_size=100"
    while url:
        page = hub(url)
        found.update({tag["name"]: tag.get("digest") for tag in page["results"]})
        url = page.get("next")
    return found


def inspect(reference):
    """Return the index's platforms and each platform's OCI labels."""
    result = subprocess.run(["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{json .}}"],
                            capture_output=True, text=True, timeout=120, check=True)
    data = json.loads(result.stdout)
    platforms = sorted(f"{m['platform']['os']}/{m['platform']['architecture']}"
                       for m in data["manifest"]["manifests"] if m.get("platform", {}).get("os") not in (None, "unknown"))
    images = data.get("image", {})
    labels = {platform: images.get(platform, {}).get("config", {}).get("Labels") or {} for platform in platforms}
    return platforms, labels


def check(row, tag_map, platforms, labels):
    """Return the problems of one pinned image as text."""
    repository, digest = row["image"].split("@")
    problems = []
    if tag_map.get(row["version"]) != digest:
        problems.append(f"{row['version']} is not the pinned index")
    if tag_map.get("latest") != digest:
        problems.append("latest is not the pinned index")
    if platforms != PLATFORMS:
        problems.append("platforms are " + ", ".join(platforms))
    for platform in PLATFORMS:
        found = labels.get(platform, {})
        if found.get("org.opencontainers.image.revision") != row["source_sha"]:
            problems.append(f"{platform} revision label is not {row['source_sha'][:7]}")
        if not found.get("org.opencontainers.image.source", "").startswith("https://github.com/"):
            problems.append(f"{platform} has no source label")
    return problems


def main():
    rows = json.loads((ROOT / "docs/releases/services.json").read_text())["services"]
    failed = False
    for row in rows:
        repository = row["image"].split("@")[0]
        tag_map = tags(repository)
        platforms, labels = inspect(row["image"])
        problems = check(row, tag_map, platforms, labels)
        outside = sorted(name for name in tag_map if not POLICY.match(name))
        failed |= bool(problems)
        print(f"{'ok  ' if not problems else 'FAIL'}  {row['service']}: {repository}:{row['version']}, "
              f"{len(tag_map)} tags, {len(outside)} outside the policy" + "".join("; " + p for p in problems), flush=True)
        for name in outside:
            print("      outside the policy: " + name)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
