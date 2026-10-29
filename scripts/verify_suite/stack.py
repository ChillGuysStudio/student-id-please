"""Access to the running Compose stack: docker, Discovery, the Gateway API, and the demo players."""
from __future__ import annotations

import concurrent.futures
import datetime
import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .util import Redactor, base_service, host_to_service, idem_key, parse_env, replica_of, secret_values, shorten, split_docker_line

BACKING = re.compile(r"postgres|mongo|redis|rabbitmq|busybox")
PINNED_TOOL = "nicolaka/netshoot@sha256:b09d9b21381f47a79b3cbcb30da25266dc17186ea00ae65e99fdc51396f48e70"

REGISTRY_CODE = """import json,sys,urllib.request
c=json.load(sys.stdin)
r=urllib.request.Request(c['url']+'/internal/v1/discovery/instances?include_unavailable=true',headers={'X-Control-Name':'operator','X-Control-Token':c['token']})
with urllib.request.urlopen(r,timeout=5) as x:print(json.dumps(json.load(x)['instances']))
"""

STATUS_CODE = """import json,sys,urllib.request,urllib.error
c=json.load(sys.stdin)
def get(token):
    r=urllib.request.Request(c['url'],headers={'X-Control-Name':'operator','X-Control-Token':token})
    try:
        with urllib.request.urlopen(r,timeout=4) as x:return x.status,json.load(x)
    except urllib.error.HTTPError as e:return e.code,{}
    except Exception as e:return type(e).__name__,{}
ok,body=get(c['token']);bad,_=get('wrong-token')
print(json.dumps({'ok':ok,'wrong':bad,'live':body.get('live'),'ready':body.get('ready'),'service':body.get('service_name'),'instance_id':body.get('instance_id')}))
"""

# The documented operator reactivation: wait for a fresh ready boot, wait out the cooldown, take two distinct ready
# probes, send one reactivation, then wait for a lease renewal.
REACTIVATE_CODE = """import datetime,json,sys,time,urllib.request,urllib.error
c=json.load(sys.stdin);H={'X-Control-Name':'operator','X-Control-Token':c['token']};base=c['discovery']+'/internal/v1/discovery/instances'
def call(url,payload=None,headers=None):
    hh=dict(headers or H)
    if payload is not None:hh['Content-Type']='application/json'
    r=urllib.request.Request(url,headers=hh,method='GET' if payload is None else 'POST',data=None if payload is None else json.dumps(payload).encode())
    try:
        with urllib.request.urlopen(r,timeout=4) as x:return x.status,json.load(x)
    except urllib.error.HTTPError as e:
        try:return e.code,json.load(e)
        except Exception:return e.code,{}
    except Exception:return 0,{}
P=lambda s:datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
now=lambda:datetime.datetime.now(datetime.timezone.utc)
def read():
    code,row=call(base+'/'+c['instance']);return row if code==200 else None
def fin(**k):
    print(json.dumps(k));sys.exit(0)
end=time.monotonic()+c['timeout']
while True:
    row=read();sc,st=call(c['origin']+'/internal/v1/status')
    if row and sc==200 and st.get('ready') is True and st.get('live') is True and st.get('instance_id')==c['instance'] and st.get('boot_id')==row['boot_id'] and (row.get('status') or {}).get('boot_id')==row['boot_id'] and not st.get('load',{}).get('critical') and P(row['lease_expires_at'])>now():break
    if time.monotonic()>end:fin(ok=False,last='boot_not_ready',state=row and row['state'])
    time.sleep(1)
if row['state']=='ready':fin(ok=True,reactivated=False)
if row['state']!='removed':fin(ok=False,last='state_'+row['state'])
wait=7.5-(now()-P(row['removed_at'])).total_seconds()
if wait>0:time.sleep(wait)
first=read();time.sleep(2.1);second=read()
for r in(first,second):
    if not(r and r['state']=='removed' and r['boot_id']==row['boot_id'] and (r.get('status') or {}).get('ready')):fin(ok=False,last='cooldown_probes_failed')
if first['last_checked_at']>=second['last_checked_at']:fin(ok=False,last='probes_not_distinct')
code,new=call(base+'/'+c['instance']+'/reactivate',{'registration_id':second['registration_id'],'operation_id':c['operation']})
if code!=200 or new.get('state')!='ready':fin(ok=False,last='reactivate_http_%s'%code)
end=time.monotonic()+30
while True:
    time.sleep(1);cur=read()
    if cur and cur['state']=='ready' and cur['registration_id']==new['registration_id'] and cur['last_checked_at']>new['last_checked_at'] and cur['lease_expires_at']>new['lease_expires_at']:fin(ok=True,reactivated=True)
    if time.monotonic()>end:fin(ok=False,last='no_renewal')
"""


class StackError(Exception):
    """The stack is missing or not reachable. The message says how to fix it."""


class Stack:
    def __init__(self, root: Path, run_id: str):
        self.root = Path(root).resolve()
        self.run_id = run_id
        env_file = self.root / ".env"
        if not env_file.exists():
            raise StackError(f"No .env in {self.root}. Create the configuration first:\n  cd {self.root} && python3 scripts/setup.py")
        self.env = parse_env(env_file.read_text())
        self.redactor = Redactor(secret_values(self.env))
        compose = (self.root / "compose.yaml").read_text() if (self.root / "compose.yaml").exists() else ""
        named = re.search(r"^name:\s*(\S+)", compose, re.M)
        self.project = self.env.get("COMPOSE_PROJECT_NAME") or (named.group(1) if named else self.root.name)
        self.gateway_url = f"http://127.0.0.1:{self.env.get('GATEWAY_PORT') or 8080}"
        self.discovery_url = self.env.get("DISCOVERY_URL") or "http://discovery-slot-1:8081"
        self._containers: dict | None = None
        self._players: dict | None = None
        self._tokens: dict = {}
        self._counter = 0
        self.notice = lambda text: None  # the command line replaces this to print progress
        self.redactor.add(self.env.get("OPERATOR_CONTROL_TOKEN", ""))

    # ---------------------------------------------------------------- docker
    @property
    def start_command(self) -> str:
        return f"cd {self.root} && docker compose up -d --wait"

    def docker(self, *args, timeout=60, input=None, check=False):
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, input=input, check=check)

    def compose(self, *args, timeout=600):
        return subprocess.run(["docker", "compose", *args], cwd=self.root, capture_output=True, text=True, timeout=timeout)

    def containers(self, refresh=False) -> dict:
        """Running containers of this project: Compose service name to container name."""
        if self._containers is None or refresh:
            out = self.docker("ps", "--filter", f"label=com.docker.compose.project={self.project}", "--format",
                              '{{.Label "com.docker.compose.service"}} {{.Names}}')
            if out.returncode:
                raise StackError("Docker is not available to this user: " + out.stderr.strip()[:200])
            self._containers = dict(line.split(" ", 1) for line in out.stdout.splitlines() if " " in line)
        return self._containers

    def container(self, service: str) -> str:
        found = self.containers().get(service) or self.containers(refresh=True).get(service)
        if not found:
            raise StackError(f"No running container for service {service}.")
        return found

    def inspect(self, service: str) -> dict:
        return json.loads(self.docker("inspect", self.container(service), check=True).stdout)[0]

    def container_env(self, service: str) -> dict:
        return dict(e.split("=", 1) for e in self.inspect(service)["Config"]["Env"] if "=" in e)

    def in_network(self, code: str, payload: dict | None = None, timeout=90):
        """Run Python inside the Player container, which can reach every private address."""
        data = {"token": self.env["OPERATOR_CONTROL_TOKEN"], "url": self.discovery_url, **(payload or {})}
        out = self.docker("exec", "-i", self.container("player"), "python", "-c", code, input=json.dumps(data), timeout=timeout)
        if out.returncode:
            raise StackError("In-network call failed: " + self.redactor.scrub((out.stderr.strip().splitlines() or ["no output"])[-1][-200:]))
        return json.loads(out.stdout.strip().splitlines()[-1])

    # ---------------------------------------------------------------- Discovery
    def registry(self, attempts=4) -> list:
        """The full Discovery registry. A busy Discovery can answer 503 for a moment, so retry a few times."""
        for attempt in range(attempts):
            try:
                return self.in_network(REGISTRY_CODE)
            except StackError:
                if attempt == attempts - 1:
                    raise
                time.sleep(1.5)

    def live_rows(self, rows=None) -> list:
        """Registry rows that have a running container. Removed rows without one are tombstones and do not count."""
        running = self.containers()
        rows = self.registry() if rows is None else rows
        return [r for r in rows if host_to_service(re.search(r"//([^:/]+)", r["http_url"]).group(1)) in running]

    def expected_services(self) -> list:
        """Compose services that register with Discovery (they carry DISCOVERY_URL)."""
        names = []
        for service in sorted(self.containers()):
            if "DISCOVERY_URL" in self.container_env(service):
                names.append(service)
        return names

    def ready_count(self):
        rows = self.live_rows()
        return sum(r["state"] == "ready" for r in rows), len(rows)

    def probe_status(self, origin: str) -> dict:
        return self.in_network(STATUS_CODE, {"url": origin.rstrip("/") + "/internal/v1/status"})

    def reactivate(self, row: dict, timeout=150) -> dict:
        service = host_to_service(re.search(r"//([^:/]+)", row["http_url"]).group(1))
        origin = row["http_url"]
        return self.in_network(REACTIVATE_CODE, {"discovery": self.discovery_url, "instance": row["instance_id"], "origin": origin,
                                                   "timeout": timeout, "operation": str(uuid.uuid4())}, timeout=timeout + 90) | {"service": service}

    def removed_since(self, since_iso: str, rows=None) -> list:
        """Removed registrants whose removal happened at or after `since_iso` (UTC ISO text), Gateway first."""
        rows = self.live_rows(rows)
        hit = [r for r in rows if r["state"] == "removed" and (r.get("removed_at") or "") >= since_iso]
        return sorted(hit, key=lambda r: r["service_name"] != "gateway")

    def recover(self, since_iso: str, expected: int | None = None, quiet: float = 18.0, min_elapsed: float = 0.0,
                deadline: float = 420.0, log=lambda s: None):
        """Reactivate everything removed since `since_iso` (Gateway first) until the registry stays fully ready.

        A caller can remove the Gateway and the Gateway can remove a caller slot, so each round rescans. A removal
        report that is still pending lands seconds later, and a cold Java replica can be removed after it is ready, so
        the registry must stay ready for `quiet` seconds, and at least `min_elapsed` seconds must pass in total.
        Returns the list of reactivated services."""
        begin = time.monotonic()
        end = begin + deadline
        done, ready_since = [], None
        while time.monotonic() < end:
            rows = self.registry()
            if any("removal_outcome=pending" in l.text for l in self.recent_lines("gateway", 25)):
                ready_since = None
                time.sleep(3)
                continue
            victims = self.removed_since(since_iso, rows)
            if victims:
                ready_since = None
                for row in victims:
                    result = self.reactivate(row)
                    log(f"reactivated {result.get('service')}: {result.get('ok')} {result.get('last', '')}")
                    done.append(result.get("service"))
                continue
            live = self.live_rows(rows)
            if all(r["state"] == "ready" for r in live) and (expected is None or len(live) == expected):
                ready_since = ready_since or time.monotonic()
                if time.monotonic() - ready_since >= quiet and time.monotonic() - begin >= min_elapsed:
                    return done
            else:
                ready_since = None
            time.sleep(3)
        raise StackError("The registry did not return to all ready: " + self.redactor.scrub(self.registry_summary()))

    def registry_summary(self) -> str:
        live = self.live_rows()
        return ", ".join(sorted(f"{r['service_name']}{host_to_service(re.search(r'//([^:/]+)', r['http_url']).group(1))[-7:]}:{r['state']}"
                                for r in live if r["state"] != "ready")) or "all ready"

    # ---------------------------------------------------------------- logs
    def fetch_logs(self, service: str, since: datetime.datetime, until: datetime.datetime | None = None) -> list:
        args = ["logs", "-t", "--since", since.strftime("%Y-%m-%dT%H:%M:%S.%fZ")]
        if until:
            args += ["--until", until.strftime("%Y-%m-%dT%H:%M:%S.%fZ")]
        proc = self.docker(*args, self.container(service), timeout=40)
        out = []
        for line in (proc.stdout + proc.stderr).splitlines():
            stamp, text = split_docker_line(line)
            if stamp is not None:
                out.append((stamp, text))
        out.sort(key=lambda item: item[0])
        return out

    def recent_lines(self, service: str, seconds: float) -> list:
        from .model import LogLine
        now = datetime.datetime.now(datetime.timezone.utc)
        return [LogLine(service, replica_of(service), s.isoformat(), t) for s, t in self.fetch_logs(service, now - datetime.timedelta(seconds=seconds))]

    def collect_logs(self, services, since, until, match=None) -> list:
        """Log lines of several services in [since, until] whose text matches `match`, merged by stamp."""
        from .model import LogLine
        pattern = re.compile(match) if isinstance(match, str) else match
        found = []

        def one(service):
            try:
                return service, self.fetch_logs(service, since, until)
            except Exception:
                return service, []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for service, lines in pool.map(one, list(services)):
                for stamp, text in lines:
                    if pattern is None or pattern.search(text):
                        found.append(LogLine(base_service(service), replica_of(service), stamp.strftime("%H:%M:%S.%f")[:-3], shorten(text), text))
        found.sort(key=lambda l: l.stamp)
        return found

    # ---------------------------------------------------------------- Gateway API
    def api(self, method, path, token=None, body=None, key=None, timeout=20):
        """One Gateway call. Returns (status, parsed JSON or {}). Status 0 means the client gave up."""
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None
        if body is not None:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": key or str(uuid.uuid4())})
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.gateway_url + path, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status, raw = response.status, response.read(200_000)
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read(20_000)
        except Exception as error:  # noqa: BLE001
            return 0, {"code": "CLIENT_" + type(error).__name__}
        try:
            return status, (json.loads(raw) if raw else {})
        except ValueError:
            return status, {}

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self.gateway_url + "/healthz", timeout=3) as response:
                return response.status == 200
        except Exception:  # noqa: BLE001
            return False

    # ---------------------------------------------------------------- demo players
    def player_env_files(self) -> list:
        files = glob.glob(str(self.root / ".local/postman/run-*/private-environment.json"))
        return sorted(files, key=os.path.getmtime)

    def create_players(self):
        """Run the guided Newman requests once, which register three demo players."""
        script = self.root / "scripts" / "run_newman.sh"
        if not script.exists():
            raise StackError(f"No demo players exist and {script} is missing.")
        self.notice("No demo players exist yet. Running scripts/run_newman.sh to create them.")
        done = subprocess.run([str(script), "--gateway-url", self.gateway_url], cwd=self.root, capture_output=True, text=True, timeout=420)
        if done.returncode:
            raise StackError(f"scripts/run_newman.sh exited with {done.returncode}, so no demo players were created.")

    def players(self, refresh=False) -> dict:
        if self._players is None or refresh:
            files = self.player_env_files()
            if not files:
                self.create_players()
                files = self.player_env_files()
            if not files:
                raise StackError("No demo players exist. Create them with:\n  cd %s && ./scripts/run_newman.sh" % self.root)
            values = {v["key"]: v["value"] for v in json.loads(Path(files[-1]).read_text())["values"]}
            self.redactor.add(*[values.get(f"password{n}", "") for n in range(3)], *[values.get(f"token{n}", "") for n in range(3)])
            self._players = values
            self._tokens = {}
        return self._players

    def login(self, number: int) -> str:
        cached = self._tokens.get(number)
        if cached and cached[1] > time.monotonic() + 60:
            return cached[0]
        players = self.players()
        self._counter += 1
        status, body = self.api("POST", "/api/v1/auth/login", body={"email": players[f"email{number}"], "password": players[f"password{number}"]},
                                key=idem_key(self.run_id, f"login-{number}-{self._counter}"))
        if status != 200 or "access_token" not in body:
            raise StackError(f"Login for demo player {number} returned HTTP {status}.")
        self.redactor.add(body["access_token"], body.get("refresh_token", ""))
        self._tokens[number] = (body["access_token"], time.monotonic() + float(body.get("expires_in", 900)))
        return body["access_token"]

    def fresh_login(self, number: int) -> str:
        """Log in again, ignoring the cached token. Needed after a role change, because tokens carry the role."""
        self._tokens.pop(number, None)
        return self.login(number)

    def forget_token(self, number: int):
        self._tokens.pop(number, None)

    # ---------------------------------------------------------------- databases
    def psql(self, service: str, user: str, database: str, sql: str):
        """Run one SQL query that returns a single JSON value and return it parsed."""
        out = self.docker("exec", self.container(service), "psql", "-U", user, "-d", database, "-At", "-c", sql, timeout=30)
        if out.returncode:
            raise StackError(f"psql failed in {service}")
        return json.loads(out.stdout.strip().splitlines()[-1])

    def mongo(self, js: str, university: bool = False):
        """Run a JavaScript function body in mongosh and return its JSON result."""
        wrapped = "print(JSON.stringify((function(){" + js + "})()))"
        if university:
            command = ["exec", "-e", "JS=" + wrapped, self.container("university-mongodb"), "sh", "-c",
                       'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
                       '--authenticationDatabase admin university_records --eval "$JS"']
        else:
            command = ["exec", self.container("mongodb"), "mongosh", "--quiet", "--eval", wrapped]
        out = self.docker(*command, timeout=40)
        if out.returncode:
            raise StackError("mongosh failed")
        return json.loads(out.stdout.strip().splitlines()[-1])

    def images(self) -> list:
        out = self.compose("config", "--images", timeout=60)
        if out.returncode:
            raise StackError("docker compose config failed: " + self.redactor.scrub(out.stderr.strip()[:200]))
        return sorted({l.strip() for l in out.stdout.splitlines() if l.strip() and not BACKING.search(l)})
