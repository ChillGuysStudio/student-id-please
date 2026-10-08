"""Check local Markdown links and imported images without network access."""

from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
IMAGE = re.compile(r'<img\b[^>]*\bsrc=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)


def without_fences(text):
    lines = []
    marker = None
    for line in text.splitlines():
        stripped = line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            if marker is None:
                marker = fence[1][0]
            elif fence[1][0] == marker:
                marker = None
            continue
        if marker is None:
            lines.append(line)
    return "\n".join(lines)


def anchors(text):
    result = set()
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", without_fences(text), re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


def check_file(path):
    text = without_fences(path.read_text(encoding="utf-8"))
    errors = []
    for target in LINK.findall(text) + IMAGE.findall(text):
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            continue
        destination = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
        try:
            destination.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link leaves repository: {target}")
            continue
        if not destination.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing target: {target}")
        elif parts.fragment and destination.suffix == ".md":
            if unquote(parts.fragment) not in anchors(destination.read_text(encoding="utf-8")):
                errors.append(f"{path.relative_to(ROOT)}: missing heading: {target}")
    return errors


def main():
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").rglob("*.md"))]
    errors = []
    for path in files:
        if not path.is_file():
            errors.append(f"Missing document: {path.relative_to(ROOT)}")
        else:
            errors.extend(check_file(path))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Documentation links valid in {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
