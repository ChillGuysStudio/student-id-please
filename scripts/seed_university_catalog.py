#!/usr/bin/env python3
"""Seed the University Record reference catalog on a fresh stack. Safe to re-run.

Builds the 69-entry catalog from docs/contracts/simulation.md and imports it
through the public Gateway admin API. A dedicated seed player supplies the
admin principal. Admin is granted for the import and revoked afterwards.
"""
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs/contracts/simulation.md'
CREDENTIALS = ROOT / '.local/lab2/seed-admin.json'
EXPECTED_ENTRIES = 69
CATALOG_PATH = '/api/v1/admin/university-data'


def build_catalog(text):
    programs = dict(re.findall(r'`([A-Z]{2,6})` \(([^)]+)\)',
                               text.split('## Initial programs and courses')[1].split('\n\n')[1]))
    assert programs == {'FAF': 'Software Engineering', 'IA': 'Applied Informatics',
                        'TI': 'Information Technology', 'SC': 'Computer Systems'}
    period = {'label': '2026-2027', 'starts_at': '2026-09-01T00:00:00Z', 'ends_at': '2027-09-01T00:00:00Z'}
    for value in period.values():
        assert value in text
    assert '2027-02-01T00:00:00Z' in text
    catalog = [{'kind': 'academic_year', 'subject_id': None, 'data': period}]
    catalog += [{'kind': 'program', 'subject_id': None,
                 'data': {'code': code, 'name': name, 'study_years': 4}} for code, name in programs.items()]
    courses = []
    for line in text.splitlines():
        match = re.fullmatch(r'\| (FAF|IA|TI|SC) \| ([1-4]) \| `([^`]+)`: ([^|]+) \| `([^`]+)`: ([^|]+) \|', line)
        if match:
            major, year, autumn_code, autumn_title, spring_code, spring_title = match.groups()
            for semester, code, title in [('autumn', autumn_code, autumn_title), ('spring', spring_code, spring_title)]:
                courses.append({'kind': 'course', 'subject_id': None,
                                'data': {'course_id': code, 'title': title.strip(), 'major': major,
                                         'year': int(year), 'semester': semester}})
    assert len(courses) == 32 and len({c['data']['course_id'] for c in courses}) == 32
    catalog += courses
    for course in courses:
        autumn = course['data']['semester'] == 'autumn'
        catalog.append({'kind': 'schedule', 'subject_id': None,
                        'data': {'course_id': course['data']['course_id'], 'semester': course['data']['semester'],
                                 'starts_at': period['starts_at'] if autumn else '2027-02-01T00:00:00Z',
                                 'ends_at': '2027-02-01T00:00:00Z' if autumn else period['ends_at']}})
    assert len(catalog) == EXPECTED_ENTRIES
    return catalog


def normalized(item):
    data = dict(item['data'])
    for key in ('starts_at', 'ends_at'):
        if key in data:
            data[key] = datetime.datetime.fromisoformat(data[key].replace('Z', '+00:00')).isoformat()
    return {'kind': item['kind'], 'subject_id': item['subject_id'], 'data': data}


def natural(item):
    data, kind = item['data'], item['kind']
    if kind == 'academic_year':
        return kind + ':' + data['label']
    if kind == 'program':
        return kind + ':' + data['code']
    return kind + ':' + data['course_id'] + (':' + data['semester'] if kind == 'schedule' else '')


def gateway_url():
    port = '8080'
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('GATEWAY_PORT='):
                port = line.split('=', 1)[1].strip().strip('\'"') or port
    return 'http://127.0.0.1:' + port


def call(base, method, path, body=None, token=None, key=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if body is not None:
        headers.update({'Content-Type': 'application/json', 'Idempotency-Key': key or str(uuid.uuid4())})
    request = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, raw = response.status, response.read(1 << 20)
    except urllib.error.HTTPError as failure:
        status, raw = failure.code, failure.read(1 << 16)
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {}


def load_credentials(base):
    if CREDENTIALS.exists():
        return json.loads(CREDENTIALS.read_text())
    suffix = secrets.token_hex(4)
    creds = {'username': 'seedadmin' + suffix, 'email': 'seedadmin%s@example.test' % suffix,
             'password': secrets.token_urlsafe(24)}
    status, player = call(base, 'POST', '/api/v1/players',
                          {**creds, 'display_name': 'University catalog seeder'})
    if status != 201 or not player.get('player_id', player.get('id')):
        raise RuntimeError('seed player registration failed with HTTP %s' % status)
    creds['player_id'] = str(uuid.UUID(str(player.get('player_id', player.get('id')))))
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(json.dumps(creds, indent=2) + '\n')
    CREDENTIALS.chmod(0o600)
    return creds


def set_admin(player_id, action):
    code = "import json,sys; from app.admin import main; c=json.load(sys.stdin); main([c['player_id'],c['action']])"
    process = subprocess.run(['docker', 'compose', 'exec', '-T', 'player', 'python', '-c', code],
                             input=json.dumps({'player_id': player_id, 'action': action}),
                             capture_output=True, text=True, timeout=60, cwd=ROOT)
    if process.returncode:
        raise RuntimeError('admin %s failed: %s' % (action, process.stderr.strip()[-300:]))


def login(base, creds):
    status, body = call(base, 'POST', '/api/v1/auth/login',
                        {'email': creds['email'], 'password': creds['password']})
    if status != 200 or not body.get('access_token'):
        raise RuntimeError('seed player login failed with HTTP %s' % status)
    return body['access_token']


def import_catalog(base, token, catalog):
    status, page = call(base, 'GET', CATALOG_PATH + '?limit=100', token=token)
    if status != 200:
        raise RuntimeError('catalog read failed with HTTP %s' % status)
    existing = {natural(item): normalized(item) for item in page.get('items', [])}
    created = present = failed = 0
    for item in catalog:
        name = natural(item)
        if name in existing:
            if existing[name] == normalized(item):
                present += 1
            else:
                failed += 1
                print('conflict: %s exists with different data' % name, file=sys.stderr)
            continue
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, 'student-id-please:university-seed:v1:' + name))
        status, _ = call(base, 'POST', CATALOG_PATH, item, token, key)
        if status == 201:
            created += 1
        elif status == 409:
            present += 1
        else:
            failed += 1
            print('failed: %s (HTTP %s)' % (name, status), file=sys.stderr)
    return created, present, failed


def main():
    catalog = build_catalog(CONTRACT.read_text())
    base = gateway_url()
    creds = load_credentials(base)
    granted = False
    try:
        set_admin(creds['player_id'], '--grant')
        granted = True
        token = login(base, creds)
        created, present, failed = import_catalog(base, token, catalog)
    finally:
        if granted:
            set_admin(creds['player_id'], '--revoke')
    print('University catalog: %d created, %d already present, %d failed (of %d)'
          % (created, present, failed, len(catalog)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
