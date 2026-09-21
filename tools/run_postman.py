"""Run the public collection in Newman using the local Compose credentials."""
import json
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    values = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines()
                  if line and not line.startswith("#"))
    # Pass credentials through stdin, not process arguments or a committed file.
    environment = {"name": "Local Compose", "values": [
        {"key": "player_url", "value": "http://player:8001", "enabled": True},
        {"key": "session_url", "value": "http://session:8002", "enabled": True},
        {"key": "moderation_token", "value": values["MODERATION_SERVICE_TOKEN"], "enabled": True}]}
    command = ["docker", "run", "--rm", "-i", "--network", "student-id-lab1_default",
               "--mount", f"type=bind,src={root / 'postman'},dst=/etc/newman,readonly",
               "--entrypoint", "sh", "postman/newman:6-alpine", "-c",
               "cat > /tmp/local-environment.json && newman run /etc/newman/lab1.postman_collection.json "
               "-e /tmp/local-environment.json --delay-request 100 --bail"]
    result = subprocess.run(command, input=json.dumps(environment), text=True, cwd=root)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
