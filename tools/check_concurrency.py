"""Exercise PostgreSQL locking and event deduplication against the running pair."""
import concurrent.futures
import json
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def call(base, method, path, body=None, token=None, key=None, extra=None, expected=200):
    headers = {"Content-Type": "application/json", "Idempotency-Key": key or str(uuid4())}
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra or {})
    request = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            assert response.status == expected, f"{method} {path}: expected {expected}, got {response.status}"
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as error:
        raise AssertionError(f"{method} {path}: expected {expected}, got {error.code}") from None


def main():
    config = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                  if line and not line.startswith("#"))
    player, session = "http://localhost:8001", "http://localhost:8002"
    suffix = uuid4().hex[:12]
    actors = []
    for index in range(3):
        username = f"race_{index}_{suffix}"
        password = secrets.token_urlsafe(24)
        account = call(player, "POST", "/api/v1/players", {"username": username, "email": username + "@example.test",
                       "password": password, "display_name": username}, expected=201)
        tokens = call(player, "POST", "/api/v1/auth/login", {"email": username + "@example.test", "password": password})
        actors.append((account["player_id"], tokens["access_token"]))
    owner, access = actors[0]
    team = call(player, "POST", "/api/v1/teams", {"name": "Concurrency demo"}, access, expected=201)
    for target, token in actors[1:]:
        friendship = call(player, "POST", "/api/v1/friendships", {"recipient_id": target}, access, expected=201)
        call(player, "PUT", f"/api/v1/friendships/{friendship['friendship_id']}/acceptance", {}, token)
        call(player, "POST", f"/api/v1/teams/{team['team_id']}/members", {"player_id": target}, access)
    shift = call(session, "POST", "/api/v1/sessions", {"team_id": team["team_id"]}, access, expected=201)
    path = f"/api/v1/sessions/{shift['session_id']}"
    for _, token in actors[1:]:
        call(session, "POST", path + "/participants", {}, token)
    call(session, "POST", path + "/start", {}, access)
    key = str(uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(session, "POST", path + "/cases", {"entry_service": "applicant"},
                                               access, key=key, expected=202), range(8)))
    assert len({result["case_id"] for result in results}) == 1
    case_id = results[0]["case_id"]
    call(session, "GET", path + f"/cases/{case_id}/status", token=access)
    event = {"event_id": str(uuid4()), "event_type": "DecisionScored", "schema_version": 1,
             "occurred_at": datetime.now(timezone.utc).isoformat(), "producer": "moderation",
             "correlation_id": case_id, "payload": {"decision_id": str(uuid4()), "session_id": shift["session_id"],
             "case_id": case_id, "moderator_id": owner, "action": "accept", "correct": True, "score_delta": 10, "penalty": 0}}
    credentials = {"X-Service-Name": "moderation", "X-Service-Token": config["MODERATION_SERVICE_TOKEN"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(session, "POST", "/internal/v1/events", event, extra=credentials), range(8)))
    assert sum(result["applied"] for result in results) == 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: call(session, "POST", path + "/end", {}, access), range(8)))
    assert all(result["status"] == "ended" and result["score"] == 10 and result["processed_count"] == 1 for result in results)
    for _ in range(50):
        result = call(player, "GET", "/api/v1/players/me", token=access)
        if result["xp"] == 10:
            break
        time.sleep(0.1)
    assert result["xp"] == 10
    print("PASS: eight concurrent case retries created one case; eight scoring deliveries counted once.")
    print("PASS: eight concurrent end requests produced one final award, delivered through RabbitMQ.")


if __name__ == "__main__":
    main()
