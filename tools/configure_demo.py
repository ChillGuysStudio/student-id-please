"""Create local demo configuration without printing or committing credentials."""
import os
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    values = {"SERVICE_VERSION": "1.0.0-rc.1"}
    for name in ("PLAYER_DB_PASSWORD", "SESSION_DB_PASSWORD", "RABBITMQ_PASSWORD",
                 "SESSION_SERVICE_TOKEN", "MODERATION_SERVICE_TOKEN"):
        values[name] = secrets.token_hex(24)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists. Kept the existing credentials.")
    with os.fdopen(fd, "w") as output:
        output.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Created ignored .env. Docker Compose reads it automatically.")


if __name__ == "__main__":
    main()
