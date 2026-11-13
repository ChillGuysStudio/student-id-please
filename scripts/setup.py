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

ROOT = Path(__file__).resolve().parents[1]
# Owner registry name: (receiver target, caller name).
OWNERS = {
    "player": ("player", "player"),
    "session": ("session", "session"),
    "applicant": ("applicant", "applicant"),
    "credential": ("credential", "credential"),
    "rules": ("rules", "rules"),
    "university_record": ("university-record", "university_record"),
    "moderation": ("moderation", "moderation"),
    "discord-dms": ("discord-dms", "discord-dms"),
}
BROKER_URL = "http://message-broker:8080"
BROKER_GRPC_URL = "http://message-broker:50051"
PASSWORDS = (
    "PLAYER_DB_PASSWORD", "SESSION_DB_PASSWORD", "MODERATION_DB_PASSWORD", "DMS_DB_PASSWORD",
    "BROKER_DB_PASSWORD", "REDIS_PASSWORD", "CHAT_TICKET_SECRET", "UNIVERSITY_MONGO_PASSWORD",
    "RULES_DB_PASSWORD", "RULES_CURSOR_SECRET", "GRAFANA_ADMIN_PASSWORD",
)
CONTROL_NAMES = ("GATEWAY", "DISCOVERY", "OPERATOR", "APPLICANT", "CREDENTIAL", "UNIVERSITY_RECORD",
                 "SERVER_RULES", "MODERATION", "PLAYER", "SESSION", "DISCORD_DMS", "MESSAGE_BROKER", "PROMETHEUS")
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


def prepare(root, gateway_port=8080, dms_port=8009):
    ports = (gateway_port, dms_port)
    if not all(1 <= port <= 65535 for port in ports) or len(set(ports)) != len(ports):
        raise ValueError("Select distinct valid public and chat ports")
    directory = root / ".local/stack"
    if (root / ".env").exists() or directory.exists():
        raise ValueError("Existing development configuration is unchanged. Use a fresh clone for another stack")
    if not shutil.which("openssl"):
        raise ValueError("OpenSSL is required")
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    gateway_jwks = json.dumps(rsa_pair(directory, "gateway"), separators=(",", ":"))
    rsa_pair(directory, "player")
    broker_jwks = json.dumps(rsa_pair(directory, "broker"), separators=(",", ":"))
    callers = {owner: secrets.token_urlsafe(32) for owner in OWNERS}
    hops = {owner: secrets.token_urlsafe(32) for owner in OWNERS}
    broker_gateway_token = secrets.token_urlsafe(32)
    config = {name: secrets.token_urlsafe(32) for name in PASSWORDS}
    config.update({name: callers[owner] for name, owner in CALLER_VARIABLES.items()})
    config.update({f"{name}_CONTROL_TOKEN": secrets.token_urlsafe(32) for name in CONTROL_NAMES})
    config.update(DISCOVERY_DISCORD_WEBHOOK_URL="")
    config.update(GATEWAY_PORT=gateway_port, DMS_PORT=dms_port,
                  HTTP_TASK_TIMEOUT_SECONDS="30", HTTP_MAX_CONCURRENT_TASKS="100", JAVA_TASK_TIMEOUT="30s")
    save(root / ".env", env_text(config))
    # Prometheus runs as an unprivileged user, so it reads the token file like the mounted public keys.
    save(directory / "prometheus-control-token", config["PROMETHEUS_CONTROL_TOKEN"], 0o444)
    caller_names, credentials = {}, {}
    runtime = {
        "GATEWAY_PUBLIC_ADDR": ":8080", "GATEWAY_INTERNAL_ADDR": ":8083",
        "GATEWAY_SIGNING_KEY_FILE": "/keys/gateway-private.pem", "GATEWAY_KEY_ID": "gateway-v1",
        "GATEWAY_PLAYER_PUBLIC_KEY_FILE": "/keys/player-public.pem", "GATEWAY_PLAYER_KEY_ID": "player-v1",
        "GATEWAY_ALLOW_INSECURE_WS": "true", "GATEWAY_ALLOW_LOCAL_WS": "true",
        "HTTP_TASK_TIMEOUT_SECONDS": "30", "HTTP_MAX_CONCURRENT_TASKS": "100",
        "GATEWAY_PEER_TIMEOUT": "2s",
        "GATEWAY_BROKER_URL": BROKER_URL, "BROKER_GRPC_URL": BROKER_GRPC_URL,
        "GATEWAY_BROKER_TOKEN": broker_gateway_token,
    }
    broker = {
        "BROKER_SIGNING_KEY_FILE": "/keys/broker-private.pem", "BROKER_KEY_ID": "broker-v1",
        "BROKER_GATEWAY_PUBLIC_KEY_FILE": "/keys/gateway-public.pem", "BROKER_GATEWAY_KEY_ID": "gateway-v1",
        "BROKER_GATEWAY_TOKEN": broker_gateway_token,
    }
    broker_receivers, gateway_receivers = {}, {}
    for owner, (target, caller) in OWNERS.items():
        audience = f"student-id-{target}-service"
        gateway_receivers[owner] = {"Target": target, "Audience": audience}
        broker_receivers[owner] = {"Target": target, "Audience": audience, "HopToken": hops[owner]}
        caller_names[owner], credentials[caller] = caller, callers[owner]
        settings = {"HTTP_TASK_TIMEOUT_SECONDS": "30", "HTTP_MAX_CONCURRENT_TASKS": "100"}
        if owner in ("player", "session"):
            settings = {"AUTH_MODE": "gateway", "GATEWAY_PUBLIC_KEY_FILE": "/keys/gateway-public.pem",
                        "GATEWAY_KEY_ID": "gateway-v1", "GATEWAY_ASSERTION_ISSUER": "student-id-gateway",
                        "GATEWAY_ASSERTION_AUDIENCE": audience, "GATEWAY_ASSERTION_SECRET": "",
                        "MAX_CONCURRENT_TASKS": "100", "TASK_TIMEOUT_SECONDS": "30",
                        "JWT_ISSUER": "student-id-please", "JWT_AUDIENCE": "student-id-players"}
            if owner == "session":
                settings.update(BROKER_GRPC_URL=BROKER_GRPC_URL, BROKER_SERVICE_TOKEN=callers[owner],
                                JWT_PUBLIC_KEY_PATH="/keys/player-public.pem")
        else:
            settings.update(AUTH_MODE="gateway", GATEWAY_KEY_ID="gateway-v1", GATEWAY_AUDIENCE=audience,
                            GATEWAY_PUBLIC_KEY_FILE="/keys/gateway-public.pem")
            if owner not in CALLER_VARIABLES.values():
                settings.update(BROKER_GRPC_URL=BROKER_GRPC_URL, BROKER_SERVICE_TOKEN=callers[owner])
        settings.update(BROKER_HOP_TOKEN=hops[owner], BROKER_KEY_ID="broker-v1",
                        BROKER_ASSERTION_ISSUER="student-id-broker")
        if owner in ("applicant", "credential"):
            settings.update(GATEWAY_JWKS_JSON=gateway_jwks, BROKER_JWKS_JSON=broker_jwks)
        else:
            settings["BROKER_PUBLIC_KEY_FILE"] = "/keys/broker-public.pem"
        save(directory / f"{owner}.env", env_text(settings))
    runtime["GATEWAY_RECEIVERS"] = json.dumps(gateway_receivers, separators=(",", ":"))
    runtime["GATEWAY_CALLER_NAMES"] = json.dumps(caller_names, separators=(",", ":"))
    for name, values in (("BROKER_RECEIVERS", broker_receivers), ("BROKER_CALLER_NAMES", caller_names),
                         ("BROKER_SERVICE_TOKENS", credentials)):
        broker[name] = json.dumps(values, separators=(",", ":"))
    save(directory / "gateway.env", env_text(runtime))
    save(directory / "broker.env", env_text(broker))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-port", type=int, default=8080)
    parser.add_argument("--dms-port", type=int, default=8009)
    args = parser.parse_args()
    try:
        prepare(ROOT, args.gateway_port, args.dms_port)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Development configuration failed: {error}\n")
    print("Created ignored .env and .local/stack configuration. No credentials were printed.")
    print("Service images default to latest. Set a *_IMAGE key in .env to pin a version.")


if __name__ == "__main__":
    main()
