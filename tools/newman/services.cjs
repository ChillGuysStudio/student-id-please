'use strict';

// Creates the state a per-service collection needs through public Gateway routes,
// so a collection runs without hand-set variables. An administrator is granted for
// the run and revoked afterwards, like scripts/seed_university_catalog.py.
const crypto = require('node:crypto');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '../..');
const SERVICES = ['applicant', 'credential', 'discord-dms', 'moderation', 'server-rules', 'university-record'];
// How far each collection needs the shared fixture to go.
const STAGES = { 'server-rules': 'accounts', 'university-record': 'permissions', 'discord-dms': 'started', applicant: 'case', credential: 'case', moderation: 'case' };
// Junior 1 reaches the enrollment and course channels but not the faculty channel.
const PERMISSIONS = [['enrollment', 'academic_year', 'course', 'schedule'], ['outlook_group', 'fcim_message']];

// These messages name a step and status only, so the runner may print them.
function fail(message) { return Object.assign(new Error(message), { safe: true }); }

function collectionFile(service) {
    if (!SERVICES.includes(service)) throw fail(`Unknown service collection: ${service}`);
    return path.join(ROOT, 'postman', `${service}-service.json`);
}

function client(gateway) {
    return async function call(method, route, { body, token } = {}) {
        const headers = { Accept: 'application/json' };
        if (token) headers.Authorization = `Bearer ${token}`;
        if (body !== undefined) Object.assign(headers, { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() });
        const response = await fetch(gateway + route, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20000) });
        const text = await response.text();
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
        return { status: response.status, data };
    };
}

function setAdmin(playerId, action, composeDir) {
    const code = "import json,sys; from app.admin import main; c=json.load(sys.stdin); main([c['player_id'],c['action']])";
    execFileSync('docker', ['compose', 'exec', '-T', 'player', 'python', '-c', code], {
        cwd: composeDir, input: JSON.stringify({ player_id: playerId, action }), stdio: ['pipe', 'ignore', 'ignore'], timeout: 60000
    });
}

// Failures name the step and HTTP status only, never a body or credential.
function expect(step, response, ...statuses) {
    if (!statuses.includes(response.status)) throw fail(`${step} failed with HTTP ${response.status}`);
    return response.data;
}

async function register(call, label) {
    const suffix = crypto.randomBytes(5).toString('hex');
    const account = { username: `${label}${suffix}`, email: `${label}${suffix}@example.test`, password: crypto.randomBytes(18).toString('base64url') };
    const player = expect(`register ${label}`, await call('POST', '/api/v1/players', { body: { ...account, display_name: `Collection ${label}` } }), 201);
    return { ...account, id: player.player_id };
}

async function login(call, account) {
    const tokens = expect('login', await call('POST', '/api/v1/auth/login', { body: { email: account.email, password: account.password } }), 200);
    return tokens.access_token;
}

async function until(step, read, done) {
    for (let attempt = 0; attempt < 30; attempt++) {
        const data = await read();
        if (done(data)) return data;
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw fail(`${step} did not finish in time`);
}

async function prepare(service, { gateway, composeDir = ROOT, grant = setAdmin }) {
    collectionFile(service);
    const call = client(gateway);
    const stage = STAGES[service];
    const accounts = {};
    for (const label of ['moderator', 'junior', 'junior2', 'outsider', 'admin']) {
        if (stage === 'accounts' && !['outsider', 'admin'].includes(label)) continue;
        accounts[label] = await register(call, label);
        accounts[label].token = await login(call, accounts[label]);
    }
    const token = label => accounts[label].token;
    const values = { admin_id: accounts.admin.id, outsider_id: accounts.outsider.id, outsider_token: token('outsider'), player_token: token('outsider') };
    let freshCase = async () => { throw fail('This collection does not need a second case.'); };
    let openCase;
    if (stage !== 'accounts') {
        const m = accounts.moderator, j1 = accounts.junior, j2 = accounts.junior2;
        for (const friend of [j1, j2]) {
            const friendship = expect('request friendship', await call('POST', '/api/v1/friendships', { token: token('moderator'), body: { recipient_id: friend.id } }), 201);
            expect('accept friendship', await call('PUT', `/api/v1/friendships/${friendship.friendship_id}/acceptance`, { token: friend.token, body: {} }), 200);
        }
        const team = expect('create team', await call('POST', '/api/v1/teams', { token: m.token, body: { name: `Collection ${crypto.randomBytes(4).toString('hex')}` } }), 201);
        for (const friend of [j1, j2]) expect('add member', await call('POST', `/api/v1/teams/${team.team_id}/members`, { token: m.token, body: { player_id: friend.id } }), 200, 201);
        const session = expect('create session', await call('POST', '/api/v1/sessions', { token: m.token, body: { team_id: team.team_id } }), 201);
        const base = `/api/v1/sessions/${session.session_id}`;
        openCase = async () => {
            const opened = expect('open case', await call('POST', `${base}/cases`, { token: m.token, body: { entry_service: 'applicant' } }), 202);
            await until('case initialization', async () => expect('read case status', await call('GET', `${base}/cases/${opened.case_id}/status`, { token: m.token }), 200), data => data.state === 'ready');
            return opened;
        };
        // A ban needs an applicant with a University identity. Cases without one are rejected and replaced.
        freshCase = async () => {
            for (let attempt = 0; attempt < 12; attempt++) {
                await until('previous case scoring', async () => expect('read session', await call('GET', base, { token: m.token }), 200), data => data.current_case_id === null);
                const opened = await openCase();
                const applicant = expect('read applicant', await call('GET', `${base}/applicants/${opened.case_id}`, { token: m.token }), 200);
                if (applicant.claims && applicant.claims.student_id) return opened.case_id;
                expect('reject case', await call('POST', `${base}/decisions`, { token: m.token, body: { case_id: opened.case_id, action: 'reject', reason: 'Collection setup' } }), 201);
            }
            throw fail('No applicant with a University identity was generated.');
        };
        for (const friend of [j1, j2]) expect('join session', await call('POST', `${base}/participants`, { token: friend.token, body: {} }), 200, 201);
        expect('assign roles', await call('PUT', `${base}/roles`, { token: m.token, body: { participants: [
            { player_id: m.id, role: 'moderator' }, { player_id: j1.id, role: 'junior_moderator' }, { player_id: j2.id, role: 'junior_moderator' }] } }), 200);
        expect('assign record permissions', await call('PUT', `${base}/record-permissions`, { token: m.token, body: { permissions: [j1, j2].map((friend, i) => (
            { session_id: session.session_id, player_id: friend.id, record_kinds: PERMISSIONS[i] })) } }), 200);
        Object.assign(values, { session_id: session.session_id, moderator_id: m.id, junior_id: j1.id, moderator_token: m.token, junior_token: j1.token });
        if (stage !== 'permissions') expect('start session', await call('POST', `${base}/start`, { token: m.token, body: {} }), 200);
        if (stage === 'case') values.case_id = (await openCase()).case_id;
    }
    // Administrator access lasts only for the run; the caller revokes it through cleanup.
    grant(accounts.admin.id, '--grant', composeDir);
    try {
        values.admin_token = await login(call, accounts.admin);
        if (stage === 'accounts') {
            // Players read any published rule version; an administrator lists them.
            const page = expect('list rule versions', await call('GET', '/api/v1/admin/rule-versions?limit=100', { token: values.admin_token }), 200);
            const published = (page.items || []).find(item => item.status === 'published');
            if (!published) throw fail('No published rule version exists; publish one before running this collection.');
            values.rule_version = published.rule_version;
        }
    } catch (error) { grant(accounts.admin.id, '--revoke', composeDir); throw error; }
    return { values, freshCase, cleanup: async () => grant(accounts.admin.id, '--revoke', composeDir) };
}

module.exports = { fail, SERVICES, STAGES, collectionFile, prepare };
