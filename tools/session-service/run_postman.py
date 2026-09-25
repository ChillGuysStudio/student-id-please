"""Create a Player fixture team, then run only Session API requests."""
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


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


def create_player_fixtures():
    base = os.environ.get("PLAYER_SETUP_URL", "http://localhost:8001").rstrip("/")

    def call(method, path, body, expected, token=None):
        headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != expected:
                    raise RuntimeError(f"Player fixture {method} {path} returned {response.status}, expected {expected}")
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Player fixture {method} {path} returned {error.code}, expected {expected}") from None

    suffix = uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    actors = {}
    for label in ("moderator", "junior1", "junior2"):
        username = f"session_{label}_{suffix}"
        account = call("POST", "/api/v1/players", {"username": username,
                       "email": username + "@example.test", "password": password,
                       "display_name": label}, 201)
        tokens = call("POST", "/api/v1/auth/login", {"email": username + "@example.test",
                      "password": password}, 200)
        actors[label] = (account["player_id"], tokens["access_token"])

    owner_id, owner_token = actors["moderator"]
    team = call("POST", "/api/v1/teams", {"name": "Session collection fixture"}, 201, owner_token)
    for label in ("junior1", "junior2"):
        player_id, player_token = actors[label]
        friendship = call("POST", "/api/v1/friendships", {"recipient_id": player_id}, 201, owner_token)
        call("PUT", f"/api/v1/friendships/{friendship['friendship_id']}/acceptance", {}, 200, player_token)
        call("POST", f"/api/v1/teams/{team['team_id']}/members", {"player_id": player_id}, 200, owner_token)

    return {"team_id": team["team_id"],
            **{label + "_id": value[0] for label, value in actors.items()},
            **{label + "_token": value[1] for label, value in actors.items()}}


def main():
    fixtures = create_player_fixtures()
    network = os.environ.get("POSTMAN_DOCKER_NETWORK")
    session_url = os.environ.get("SESSION_URL", "http://session:8002" if network else "http://host.docker.internal:8002")
    environment = {"name": "Session local test", "values": [
        {"key": "session_url", "value": session_url, "enabled": True},
        {"key": "moderation_token", "value": setting("MODERATION_SERVICE_TOKEN"), "enabled": True},
        *({"key": key, "value": value, "enabled": True} for key, value in fixtures.items()),
    ]}
    command = ["docker", "run", "--rm", "-i"]
    if network:
        command += ["--network", network]
    command += ["--mount", f"type=bind,src={ROOT / 'postman'},dst=/etc/newman,readonly",
                "--entrypoint", "sh", "postman/newman:6-alpine", "-c",
                "cat > /tmp/local-environment.json && newman run /etc/newman/session-service.json "
                "-e /tmp/local-environment.json --delay-request 100 --bail"]
    result = subprocess.run(command, input=json.dumps(environment), text=True, cwd=ROOT)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
