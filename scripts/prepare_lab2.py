#!/usr/bin/env python3
"""Create ignored development configuration without printing credentials."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replicas  # noqa: E402
import uuid

ROOT = Path(__file__).resolve().parents[1]
OWNERS = {
    "player": ("player", "player", "PLAYER", "http://player:8001"),
    "session": ("session", "session", "SESSION", "http://session:8002"),
    "applicant": ("applicant", "applicant", "APPLICANT", "http://applicant:8081"),
    "credential": ("credential", "credential", "CREDENTIAL", "http://credential:8082"),
    "rules": ("rules", "rules", "RULES", "http://server-rules:8005"),
    "university_record": ("university-record", "university_record", "UNIVERSITY", "http://university-record:8006"),
    "moderation": ("moderation", "moderation", "MODERATION", "http://moderation:8000"),
    "discord-dms": ("discord-dms", "discord-dms", "DMS", "http://discord-dms:8000"),
}
# Released Lab 3 images, written to .env as owner/repo:version. Edit .env to change a version, or
# run with --tag latest to follow each repository's newest release.
IMAGES = {
    "GATEWAY_IMAGE": "maxnoragami/gateway-service:3.0.7",
    "DISCOVERY_IMAGE": "maxnoragami/discovery-service:3.0.6",
    "PLAYER_IMAGE": "tirppy/student-id-player-service:3.0.0",
    "SESSION_IMAGE": "tirppy/student-id-session-service:3.0.8",
    "MODERATION_IMAGE": "sentientmoss/pad-moderation-service:3.0.5",
    "DISCORD_DMS_IMAGE": "sentientmoss/pad-discord-dms-service:3.0.3",
    "APPLICANT_IMAGE": "mcittkmims/applicant-service:3.0.3",
    "CREDENTIAL_IMAGE": "mcittkmims/credential-service:3.0.5",
    "UNIVERSITY_RECORD_IMAGE": "maxnoragami/university-record-service:3.0.4",
    "SERVER_RULES_IMAGE": "maxnoragami/server-rules-service:3.0.5",
}
PASSWORDS = (
    "PLAYER_DB_PASSWORD", "SESSION_DB_PASSWORD", "MODERATION_DB_PASSWORD", "DMS_DB_PASSWORD",
    "RABBITMQ_PASSWORD", "REDIS_PASSWORD", "CHAT_TICKET_SECRET", "UNIVERSITY_MONGO_PASSWORD",
    "RULES_DB_PASSWORD", "RULES_CURSOR_SECRET", "APPLICANT_BROKER_PASSWORD", "CREDENTIAL_BROKER_PASSWORD",
    "UNIVERSITY_BROKER_PASSWORD",
)
CONTROL_NAMES = ("GATEWAY", "DISCOVERY", "OPERATOR", "APPLICANT", "CREDENTIAL", "UNIVERSITY_RECORD",
                 "SERVER_RULES", "MODERATION", "PLAYER", "SESSION", "DISCORD_DMS")
REPLICA_NAMES = CONTROL_NAMES[3:]
CALLER_VARIABLES = {
    "SESSION_SERVICE_TOKEN": "session", "MODERATION_SERVICE_TOKEN": "moderation",
    "DISCORD_DMS_SERVICE_TOKEN": "discord-dms",
}


def save(path, content, mode=0o600):
    with path.open("x") as stream:
        stream.write(content)
    path.chmod(mode)


def env_text(values):
    lines = []
    for name, value in values.items():
        value = str(value)
        if "\n" in value or "\r" in value or "'" in value:
            raise ValueError("Configuration contains an unsupported character")
        lines.append(f"{name}='{value}'")
    return "\n".join(lines) + "\n"


def rsa_pair(directory, name):
    private, public = directory / f"{name}-private.pem", directory / f"{name}-public.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                    "-out", str(private)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Only the host owner can traverse the parent. Non-root containers read the mounted files.
    private.chmod(0o444)
    public.chmod(0o444)
    modulus = subprocess.check_output(["openssl", "rsa", "-in", str(private), "-noout", "-modulus"],
                                      stderr=subprocess.DEVNULL).decode().strip().split("=", 1)[1]
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": f"{name}-v1",
                      "n": encode(bytes.fromhex(modulus)), "e": "AQAB"}]}


def select_images(gateway_image=None, tag=None):
    images = {name: (ref.rsplit(":", 1)[0] + ":" + tag if tag else ref) for name, ref in IMAGES.items()}
    if gateway_image:
        images["GATEWAY_IMAGE"] = gateway_image
    if any(not ref or any(char.isspace() for char in ref) for ref in images.values()):
        raise ValueError("Image references must be owner/repo:version without spaces")
    return images


def prepare(root, gateway_image=None, gateway_port=8080, dms_port=8009, tag=None):
    images = select_images(gateway_image, tag)
    if not all(1 <= port <= 65535 for port in (gateway_port, dms_port)) or gateway_port == dms_port:
        raise ValueError("Select distinct valid public and WebSocket ports")
    directory = root / ".local/lab2"
    if (root / ".env").exists() or directory.exists():
        raise ValueError("Existing development configuration is unchanged. Use a fresh clone for another stack")
    if not shutil.which("openssl"):
        raise ValueError("OpenSSL is required")
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    gateway_jwks = json.dumps(rsa_pair(directory, "gateway"), separators=(",", ":"))
    rsa_pair(directory, "player")
    callers = {owner: secrets.token_urlsafe(32) for owner in OWNERS}
    hops = {owner: secrets.token_urlsafe(32) for owner in OWNERS}
    config = {name: secrets.token_urlsafe(32) for name in PASSWORDS}
    config.update({name: callers[owner] for name, owner in CALLER_VARIABLES.items()})
    config.update({f"{name}_CONTROL_TOKEN": secrets.token_urlsafe(32) for name in CONTROL_NAMES})
    config.update({f"{name}_SLOT1_INSTANCE_ID": uuid.uuid4() for name in REPLICA_NAMES})
    config.update(REPLICAS="2", REPLICA_SEED=uuid.uuid4(), COMPOSE_FILE="compose.yaml:compose.replicas.yaml")
    config.update(GATEWAY_INSTANCE_ID=uuid.uuid4(), DISCOVERY_INSTANCE_ID=uuid.uuid4(), DISCOVERY_DISCORD_WEBHOOK_URL="")
    config.update(images)
    config.update(GATEWAY_PORT=gateway_port, DMS_PORT=dms_port,
                  HTTP_TASK_TIMEOUT_SECONDS="30", HTTP_MAX_CONCURRENT_TASKS="100", JAVA_TASK_TIMEOUT="30s")
    save(root / ".env", env_text(config))
    receiver_config, caller_names, credentials = {}, {}, {}
    runtime = {
        "GATEWAY_PUBLIC_ADDR": ":8080", "GATEWAY_INTERNAL_ADDR": ":8083",
        "GATEWAY_SIGNING_KEY_FILE": "/keys/gateway-private.pem", "GATEWAY_KEY_ID": "gateway-v1",
        "GATEWAY_PLAYER_PUBLIC_KEY_FILE": "/keys/player-public.pem", "GATEWAY_PLAYER_KEY_ID": "player-v1",
        "GATEWAY_EXTERNAL_WS_URL": f"ws://localhost:{dms_port}",
        "GATEWAY_ALLOW_INSECURE_WS": "true", "GATEWAY_ALLOW_LOCAL_WS": "true",
        "HTTP_TASK_TIMEOUT_SECONDS": "30", "HTTP_MAX_CONCURRENT_TASKS": "100",
        "GATEWAY_PEER_TIMEOUT": "2s",
    }
    for owner, (target, caller, setting, url) in OWNERS.items():
        audience = f"student-id-{target}-service"
        receiver_config[owner] = {"Target": target, "Audience": audience, "HopToken": hops[owner]}
        caller_names[owner], credentials[caller] = caller, callers[owner]
        runtime[f"GATEWAY_{setting}_URL"] = url
        settings = {"HTTP_TASK_TIMEOUT_SECONDS": "30", "HTTP_MAX_CONCURRENT_TASKS": "100"}
        if owner in ("player", "session"):
            settings = {"AUTH_MODE": "gateway", "GATEWAY_PUBLIC_KEY_FILE": "/keys/gateway-public.pem",
                        "GATEWAY_KEY_ID": "gateway-v1", "GATEWAY_ASSERTION_ISSUER": "student-id-gateway",
                        "GATEWAY_ASSERTION_AUDIENCE": audience, "GATEWAY_ASSERTION_SECRET": "",
                        "SERVICE_TOKENS": json.dumps({"gateway": hops[owner]}, separators=(",", ":")),
                        "MAX_CONCURRENT_TASKS": "100", "TASK_TIMEOUT_SECONDS": "30",
                        "JWT_ISSUER": "student-id-please", "JWT_AUDIENCE": "student-id-players"}
            if owner == "session":
                settings.update(GATEWAY_URL="http://gateway:8083", GATEWAY_SERVICE_TOKEN=callers[owner],
                                JWT_PUBLIC_KEY_PATH="/keys/player-public.pem")
        else:
            settings.update(AUTH_MODE="gateway", GATEWAY_KEY_ID="gateway-v1", GATEWAY_AUDIENCE=audience,
                            GATEWAY_PUBLIC_KEY_FILE="/keys/gateway-public.pem", GATEWAY_HOP_TOKEN=hops[owner],
                            GATEWAY_INTERNAL_URL="http://gateway:8083", GATEWAY_CALLER_TOKEN=callers[owner])
        if owner in ("applicant", "credential"):
            settings["GATEWAY_JWKS_JSON"] = gateway_jwks
        if owner == "rules":
            settings.update(GATEWAY_RULES_RECEIVER_TOKEN=hops[owner], INTERNAL_GATEWAY_URL="http://gateway:8083",
                            RULES_SERVICE_TOKEN=callers[owner])
        save(directory / f"{owner}.env", env_text(settings))
    for name, values in (("GATEWAY_RECEIVERS", receiver_config), ("GATEWAY_CALLER_NAMES", caller_names),
                         ("GATEWAY_SERVICE_TOKENS", credentials)):
        runtime[name] = json.dumps(values, separators=(",", ":"))
    save(directory / "gateway.env", env_text(runtime))
    (root / replicas.OUTPUT).write_text(replicas.render(replicas.read_env(root / ".env")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-image", help="override GATEWAY_IMAGE (owner/repo:version)")
    parser.add_argument("--tag", help="use this tag for every service image, e.g. latest")
    parser.add_argument("--gateway-port", type=int, default=8080)
    parser.add_argument("--dms-port", type=int, default=8009)
    args = parser.parse_args()
    try:
        prepare(ROOT, args.gateway_image, args.gateway_port, args.dms_port, args.tag)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Development configuration failed: {error}\n")
    print("Created ignored .env and .local/lab2 configuration. No credentials were printed.")
    print("Service images are set in .env as owner/repo:version (*_IMAGE).")
    print("Wrote compose.replicas.yaml for REPLICAS=2; see scripts/replicas.py to change it.")


if __name__ == "__main__":
    main()
