"""Pure helpers: environment parsing, secret redaction, log shortening, identifiers, and timing."""
from __future__ import annotations

import datetime
import re
import uuid

NAMESPACE = uuid.UUID("6f1c2f0e-5a52-4c1b-9d6e-0b7a5b1d2a11")
SECRET_NAME = re.compile(r"token|secret|password|authorization|assertion|passwd|api_key|private", re.I)
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
HTTPS_HOOK = re.compile(r"https://discord(?:app)?\.com/api/webhooks/\S+")
DOCKER_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z\s?(.*)$", re.S)


def parse_env(text: str) -> dict[str, str]:
    """Read KEY=VALUE lines, dropping comments and one layer of matching quotes."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def set_env_value(text: str, key: str, value: str | None) -> str:
    """Return env text with KEY set to value, or removed when value is None. Other lines stay byte for byte."""
    lines = text.splitlines(keepends=True)
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key and "=" in line and not line.lstrip().startswith("#"):
            if value is not None and not done:
                out.append(f"{key}={value}\n")
            done = True
            continue
        out.append(line)
    if value is not None and not done:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"{key}={value}\n")
    return "".join(out)


class Redactor:
    """Replaces known secret values and token-shaped strings so nothing sensitive reaches the screen or a report."""

    def __init__(self, secrets=()):
        self.secrets: list[str] = []
        self.add(*secrets)

    def add(self, *values):
        for value in values:
            if value and len(value) >= 6 and value not in self.secrets:
                self.secrets.append(value)
        self.secrets.sort(key=len, reverse=True)

    def scrub(self, text) -> str:
        text = str(text)
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        text = JWT.sub("[jwt]", text)
        text = HTTPS_HOOK.sub("[webhook]", text)
        return re.sub(r"\b([A-Za-z_]*(?:token|secret|password|authorization)[A-Za-z_]*)=\S+", r"\1=[redacted]", text, flags=re.I)

    def holds_secret(self, text: str) -> bool:
        return any(secret in text for secret in self.secrets)


def secret_values(env: dict[str, str]) -> list[str]:
    """Values of .env keys whose names look like credentials."""
    return [v for k, v in env.items() if SECRET_NAME.search(k) and len(v) >= 6]


def new_run_id(now: datetime.datetime, suffix: str) -> str:
    return "vf-" + now.strftime("%y%m%d%H%M%S") + "-" + suffix[:4]


def idem_key(run_id: str, purpose: str) -> str:
    """A stable Idempotency-Key for one purpose inside one run."""
    return str(uuid.uuid5(NAMESPACE, f"{run_id}/{purpose}"))


def fmt_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes} min {rest:02d} s"


def split_docker_line(line: str):
    """Split `docker logs -t` output into (datetime, text). Returns (None, line) when there is no stamp."""
    match = DOCKER_STAMP.match(line.rstrip("\n"))
    if not match:
        return None, line.rstrip("\n")
    base, frac, text = match.groups()
    stamp = datetime.datetime.fromisoformat(base).replace(tzinfo=datetime.timezone.utc)
    if frac:
        stamp += datetime.timedelta(microseconds=int(float(frac) * 1_000_000))
    return stamp, text


ACCESS = re.compile(r'uvicorn\.access \S+ - "(?P<req>[A-Z]+ \S+) HTTP/[\d.]+" (?P<code>\d{3})')
KEYS = ("event", "service_name", "state", "previous_state", "destination_instance_id", "endpoint", "failure_kind",
        "removal_reason", "removal_outcome", "utilization", "reason", "attempt_id", "status", "message_id")
UUID_IN_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
WEBSOCKET = re.compile(r'"WebSocket (?P<path>[^\s?"]+)(?:\?\S*)?"\s*(?P<rest>.*)$')
GO_LINE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? ")
PY_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (?:INFO|WARNING|ERROR|DEBUG) ")
JAVA_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(?:INFO|WARN|ERROR|DEBUG)\s+\d+ --- \[[^\]]*\] \[[^\]]*\] \S+\s*: ")


def shorten(raw: str, limit: int = 150) -> str:
    """One short readable line from a raw container log line."""
    text = raw.strip()
    access = ACCESS.search(text)
    if access:
        request = UUID_IN_TEXT.sub(lambda m: m.group(0)[:8], access["req"])
        request = re.sub(r"vf=vf-\d+-[0-9a-f]{4}-", "vf=", request)
        return f"{request} {access['code']}"
    for pattern in (GO_LINE, PY_LINE, JAVA_LINE):
        text = pattern.sub("", text, count=1)
    text = re.sub(r"^(?:INFO|WARN(?:ING)?|ERROR)\s+", "", text)
    socket = WEBSOCKET.search(text)
    if socket:
        return UUID_IN_TEXT.sub(lambda m: m.group(0)[:8], f"WebSocket {socket['path']} {socket['rest']}".strip())
    pairs = dict(re.findall(r"\b([a-z_]+)=([^\s]+)", text))
    picked = [f"{k}={shorten_id(pairs[k])}" for k in KEYS if k in pairs and pairs[k] not in ("-", "None")]
    head = text.split(" ", 1)[0]
    if picked:
        text = " ".join(([head] if re.fullmatch(r"[A-Za-z_.]+", head) else []) + picked)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shorten_id(value: str) -> str:
    return value[:8] if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value) else value


def replica_of(service: str) -> str:
    """Compose service name to a replica label: session -> 1, session-slot-2 -> 2."""
    match = re.search(r"-slot-(\d+)$", service)
    return match.group(1) if match else "1"


def base_service(service: str) -> str:
    return re.sub(r"-slot-\d+$", "", service)


def host_to_service(host: str) -> str:
    """Registry host (`session-slot-2`) to the Compose service name (`session-slot-2`; slot 1 is `session`)."""
    match = re.fullmatch(r"(.+)-slot-(\d+)", host)
    if not match:
        return host
    base, slot = match.groups()
    return base if slot == "1" else f"{base}-slot-{slot}"


def service_to_host(service: str) -> str:
    return service if re.search(r"-slot-\d+$", service) else f"{service}-slot-1"


def served_by(lines, run_id: str) -> dict:
    """Map each request marker (`?vf=<marker>`) to the replica whose access log shows it, e.g. {"x-0": "session#2"}."""
    found = {}
    for line in lines:
        match = re.search(r"[?&]vf=(" + re.escape(run_id) + r"[A-Za-z0-9._-]*)", line.raw or line.text)
        if match:
            found[match.group(1)] = f"{line.service}#{line.replica}"
    return found


def alternates(sequence) -> bool:
    """True when no replica serves two requests in a row and at least two replicas appear."""
    return len(set(sequence)) >= 2 and all(a != b for a, b in zip(sequence, sequence[1:]))


def balanced(sequence, replicas: int) -> bool:
    """True when every one of `replicas` replicas served the same number of requests."""
    counts = {r: sequence.count(r) for r in set(sequence)}
    return len(counts) == replicas and len(set(counts.values())) == 1
