"""Run the Player collection against an independently started service."""
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def setting(name):
    if value := os.environ.get(name):
        return value
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == name and value:
                return value
    raise SystemExit(f"Set {name} in the environment or ignored CPR .env before running this collection.")


def main():
    network = os.environ.get("POSTMAN_DOCKER_NETWORK")
    player_url = os.environ.get("PLAYER_URL", "http://player:8001" if network else "http://host.docker.internal:8001")
    gateway_public = os.environ.get("GATEWAY_PUBLIC_URL", "http://gateway:8080" if network else "http://host.docker.internal:8080")
    gateway_internal = os.environ.get("GATEWAY_INTERNAL_URL", "http://gateway:8083" if network else "")
    if not gateway_internal:
        raise SystemExit("Set POSTMAN_DOCKER_NETWORK so Newman reaches the private gateway listener; never publish the internal listener to the host.")
    environment = {"name": "Player local test", "values": [
        {"key": "gateway_public_url", "value": gateway_public, "enabled": True},
        {"key": "gateway_internal_url", "value": gateway_internal, "enabled": True},
        {"key": "player_ops_url", "value": player_url, "enabled": True},
        {"key": "session_token", "value": setting("SESSION_SERVICE_TOKEN"), "enabled": True},
        {"key": "moderation_token", "value": setting("MODERATION_SERVICE_TOKEN"), "enabled": True},
    ]}
    command = ["docker", "run", "--rm", "-i"]
    if network:
        command += ["--network", network]
    command += ["--mount", f"type=bind,src={ROOT / 'postman'},dst=/etc/newman,readonly",
                "--entrypoint", "sh", "postman/newman:6-alpine", "-c",
                "cat > /tmp/local-environment.json && newman run /etc/newman/player-service.json "
                "-e /tmp/local-environment.json --delay-request 100 --bail"]
    result = subprocess.run(command, input=json.dumps(environment), text=True, cwd=ROOT)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
