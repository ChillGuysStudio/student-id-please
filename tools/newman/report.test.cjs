'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { sanitize, render, verifyNoSecrets, parseArgs, executePhase, phases } = require('./report.cjs');
const services = require('./services.cjs');

function fixture({ failure = false, skipped = false } = {}) {
    const privateValue = 'PRIVATE_SENTINEL_credential_123456789';
    return {
        collection: { info: { name: privateValue } },
        environment: { values: [{ key: 'token0', value: privateValue }] },
        globals: { values: [{ key: 'password', value: privateValue }] },
        run: {
            stats: { iterations: { total: 1, failed: 0, pending: 0 }, requests: { total: 1, failed: 0, pending: 0 }, assertions: { total: 1, failed: failure ? 1 : 0, pending: 0 } },
            timings: { started: 1700000000000, completed: 1700000000100, responseAverage: 10 },
            transfers: { responseTotal: 123 },
            failures: failure ? [{ error: { message: privateValue } }] : [],
            executions: [{ cursor: { ref: 'private-id', iteration: 0 },
                item: { name: '01 — Gateway health', event: [{ script: { exec: [privateValue] } }] },
                request: { method: 'GET', url: `http://example.invalid/${privateValue}?ticket=${privateValue}`, header: [{ key: 'Authorization', value: privateValue }], body: { raw: privateValue } },
                response: { code: failure ? 500 : 200, status: privateValue, responseTime: 10, responseSize: 123, header: [{ key: 'X-Secret', value: privateValue }], stream: { data: [...Buffer.from(privateValue)] } },
                assertions: [{ assertion: 'Process reports ok', skipped, ...(failure ? { error: { message: privateValue, stack: privateValue, test: privateValue } } : {}) }]
            }]
        }
    };
}

test('allowlist removes URLs, credentials, bodies, scripts and raw diagnostics', () => {
    const raw = fixture({ failure: true });
    const safe = sanitize([raw]);
    assert.ok(!JSON.stringify(safe).includes('PRIVATE_SENTINEL'));
    assert.equal(safe.run.executions[0].response.code, 500);
    assert.equal(safe.run.stats.assertions.failed, 1);
    assert.equal(safe.reportMetadata.failed, true);
    assert.equal(safe.run.executions[0].item.name, '01 — Gateway health');
});

test('native htmlextra renders success, failures and skipped assertions without secrets', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'native-reporter-test-'));
    try {
        for (const options of [{}, { failure: true }, { skipped: true }]) {
            const raw = fixture(options);
            const html = render(sanitize([raw]), path.join(directory, 'report.html'));
            verifyNoSecrets([raw], html);
            assert.ok(html.includes('newman-reporter-htmlextra') || html.includes('htmlextra'));
            assert.ok(!html.includes('PRIVATE_SENTINEL'));
            assert.ok(html.includes('Process reports ok'));
        }
    } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('multiple saved phases retain aggregate counts, failures and timing range', () => {
    const safe = sanitize([fixture(), fixture({ failure: true })]);
    assert.equal(safe.run.stats.requests.total, 2);
    assert.equal(safe.run.stats.assertions.total, 2);
    assert.equal(safe.run.stats.assertions.failed, 1);
    assert.equal(safe.reportMetadata.phases.length, 2);
    assert.deepEqual(safe.run.executions.map(e => e.cursor.iteration), [0, 1]);
    assert.equal(safe.run.timings.responseAverage, 10);
    assert.ok(safe.reportMetadata.scope.includes('Does not include'));
});

test('unknown private assertion and request names are replaced, not copied', () => {
    const raw = fixture();
    raw.run.executions[0].item.name = 'PRIVATE_SENTINEL_request';
    raw.run.executions[0].assertions[0].assertion = 'PRIVATE_SENTINEL_assertion';
    assert.ok(!JSON.stringify(sanitize([raw])).includes('PRIVATE_SENTINEL'));
});

test('privacy check catches secrets and JWT-looking strings', () => {
    const raw = fixture();
    assert.throws(() => verifyNoSecrets([raw], 'PRIVATE_SENTINEL_credential_123456789'), /Private environment/);
    assert.throws(() => verifyNoSecrets([], 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.signature'), /JWT/);
});

test('live execution uses real Newman against an isolated HTTP peer and preserves its environment', async () => {
    const http = require('node:http');
    const server = http.createServer((request, response) => {
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end('{"status":"ok"}');
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
        const collection = { info: { name: 'Isolated runner test', schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json' }, item: [{
            name: '01 — Gateway health', request: { method: 'GET', url: `http://127.0.0.1:${server.address().port}/healthz` },
            event: [{ listen: 'test', script: { type: 'text/javascript', exec: [
                'pm.test("Process reports ok", () => pm.expect(pm.response.json().status).to.eql("ok"));',
                'pm.environment.set("token0", "PRIVATE_SENTINEL_live_123456789");'
            ] } }]
        }] };
        const summary = await executePhase(collection, { name: 'Private test', values: [] });
        const raw = JSON.parse(JSON.stringify(summary));
        assert.equal(raw.run.stats.assertions.failed, 0);
        assert.equal(raw.run.stats.requests.total, 1);
        assert.equal(summary.environment.toJSON().values.find(v => v.key === 'token0').value, 'PRIVATE_SENTINEL_live_123456789');
        assert.ok(!JSON.stringify(sanitize([raw])).includes('PRIVATE_SENTINEL'));
    } finally { await new Promise(resolve => server.close(resolve)); }
});

test('argument validation prevents ambiguous render/run modes', () => {
    assert.equal(parseArgs(['--with-overload']).overload, true);
    assert.equal(parseArgs(['--from-json', 'first.json', '--from-json', 'second.json']).inputs.length, 2);
    assert.throws(() => parseArgs(['--from-json', 'first.json', '--with-overload']), /cannot be combined/);
    assert.throws(() => parseArgs(['--output', 'bad.json']), /end in .html/);
    assert.throws(() => parseArgs(['--from-json']), /Missing value/);
    assert.throws(() => sanitize([]), /At least one/);
    assert.throws(() => sanitize([{}]), /Not a Newman/);
});

test('HTTP checks report omits control credentials, webhook, headers and private IDs', () => {
    const raw = fixture({ failure: true });
    const canaries = ['CONTROL_CANARY_123456789', 'WEBHOOK_CANARY_123456789', 'INSTANCE_CANARY_123456789'];
    raw.environment.values.push({ key: 'control_token', value: canaries[0] }, { key: 'discord_webhook_url', value: canaries[1] });
    raw.run.executions[0].request.header.push({ key: 'X-Control-Token', value: canaries[0] });
    raw.run.executions[0].response.header.push({ key: 'X-Gateway-Instance-Id', value: canaries[2] });
    raw.run.executions[0].response.stream = { data: [...Buffer.from(canaries.join(' '))] };
    raw.run.executions[0].item.name = 'Discovery liveness';
    raw.run.executions[0].assertions[0].assertion = 'Discovery health returns 200';
    const httpChecks = path.resolve(__dirname, '../../postman/http-checks.postman_collection.json');
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'redaction-'));
    try {
        const safe = sanitize([raw], httpChecks);
        const output = path.join(directory, 'report.html');
        const html = render(safe, output);
        verifyNoSecrets([raw], html);
        for (const canary of canaries) {
            assert.ok(!JSON.stringify(safe).includes(canary));
            assert.ok(!fs.readFileSync(output, 'utf8').includes(canary));
            assert.ok(!fs.readFileSync(path.join(directory, 'report.summary.json'), 'utf8').includes(canary));
        }
        assert.equal(safe.reportMetadata.failed, true);
        assert.ok(html.includes('Discovery liveness'));
    } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('HTTP check flags cannot trigger the stateful guided run or overload', () => {
    assert.equal(parseArgs(['--http']).http, 'Safe public smoke');
    assert.equal(parseArgs(['--http-private']).http, 'Private Discovery health');
    assert.throws(() => parseArgs(['--http', '--with-overload']), /cannot run with overload/);
    assert.throws(() => parseArgs(['--http-private', '--http']), /Choose one/);
    assert.throws(() => parseArgs(['--http', '--from-json', 'private.json']), /cannot be combined/);
});

test('guided phases keep overload requests 28 and 29 separate from the later folders', () => {
    const source = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../postman/guided-demo.postman_collection.json'), 'utf8'));
    const plan = phases(source);
    const names = collection => collection.item.flatMap(folder => folder.item).map(item => item.name.slice(0, 2));
    assert.deepEqual(plan.overload.item.map(item => item.name.slice(0, 2)), ['28', '29']);
    assert.equal(plan.labels.before, '01-27');
    assert.ok(!names(plan.before).includes('28') && !names(plan.after).includes('29'));
    assert.equal(plan.labels.after, `30-${names(plan.after).at(-1)}`);
    assert.throws(() => phases({ item: [{ name: 'No overload', item: [] }] }), /no overload folder/);
});

test('service flag selects one collection and rejects other modes', () => {
    const options = parseArgs(['--service', 'applicant', '--compose-dir', '/tmp/stack']);
    assert.equal(options.service, 'applicant');
    assert.equal(options.composeDir, '/tmp/stack');
    assert.ok(options.output.endsWith(path.join('.local/postman/applicant/newman-htmlextra.html')));
    assert.throws(() => parseArgs(['--service', 'unknown']), /Unknown service/);
    assert.throws(() => parseArgs(['--service', 'applicant', '--http']), /cannot be combined/);
    assert.throws(() => parseArgs(['--service', 'applicant', '--with-overload']), /cannot be combined/);
    assert.throws(() => parseArgs(['--service']), /Missing value/);
});

test('service report names its collection and omits private values', () => {
    const raw = fixture();
    raw.run.executions[0].item.name = 'Create preset';
    raw.run.executions[0].assertions[0].assertion = 'PRIVATE_SENTINEL_assertion';
    const safe = sanitize([raw], services.collectionFile('applicant'));
    assert.equal(safe.collection.info.name, 'applicant service collection');
    assert.equal(safe.run.executions[0].item.name, 'Create preset');
    assert.ok(!JSON.stringify(safe).includes('PRIVATE_SENTINEL'));
    assert.ok(!safe.reportMetadata.scope.includes('overload'));
});

// A small Gateway double that answers the public routes the fixture calls.
function fakeGateway({ identityOnAttempt = 1 } = {}) {
    const http = require('node:http');
    const state = { applicants: 0, rejected: 0, requests: [] };
    const server = http.createServer((request, response) => {
        let text = '';
        request.on('data', chunk => { text += chunk; });
        request.on('end', () => {
            const route = request.url.split('?')[0];
            state.requests.push(`${request.method} ${route}`);
            const send = (status, body = {}) => { response.writeHead(status, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(body)); };
            const id = () => require('node:crypto').randomUUID();
            if (request.method === 'POST' && route === '/api/v1/players') return send(201, { player_id: id() });
            if (route === '/api/v1/auth/login') return send(200, { access_token: 'token-' + id() });
            if (route === '/api/v1/friendships') return send(201, { friendship_id: id() });
            if (route.endsWith('/acceptance') || route.endsWith('/roles') || route.endsWith('/record-permissions') || route.endsWith('/start') || route.endsWith('/participants')) return send(200);
            if (route === '/api/v1/teams') return send(201, { team_id: id() });
            if (route.endsWith('/members')) return send(200);
            if (route === '/api/v1/sessions') return send(201, { session_id: id() });
            if (route.endsWith('/cases')) return send(202, { case_id: id() });
            if (route.endsWith('/status')) return send(200, { state: 'ready' });
            if (route.includes('/applicants/')) return send(200, { claims: { student_id: ++state.applicants >= identityOnAttempt ? 'IA-25-1' : null } });
            if (route.endsWith('/decisions')) { state.rejected++; return send(201); }
            if (route === '/api/v1/admin/rule-versions') return send(200, { items: [{ status: 'draft', rule_version: 'draft' }, { status: 'published', rule_version: 'published' }] });
            if (/^\/api\/v1\/sessions\/[^/]+$/.test(route)) return send(200, { current_case_id: null });
            send(404);
        });
    });
    return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve({ server, state, url: `http://127.0.0.1:${server.address().port}` })));
}

test('every collection receives the variables it cannot set itself, and administrator access is revoked', async () => {
    const gateway = await fakeGateway();
    try {
        for (const service of services.SERVICES) {
            const actions = [];
            const fixture = await services.prepare(service, { gateway: gateway.url, grant: (id, action) => actions.push(action) });
            const text = fs.readFileSync(services.collectionFile(service), 'utf8');
            const declared = JSON.parse(text).variable.filter(entry => entry.value === '').map(entry => entry.key);
            const setByScripts = new Set([...text.matchAll(/\.set\(\\?["']([A-Za-z_]+)/g)].map(match => match[1]));
            const needed = declared.filter(key => !setByScripts.has(key) && (key.endsWith('_token') || ['session_id', 'case_id', 'moderator_id', 'junior_id', 'rule_version'].includes(key)));
            for (const key of needed) assert.ok(fixture.values[key], `${service} needs ${key}`);
            assert.deepEqual(actions, ['--grant']);
            await fixture.cleanup();
            assert.deepEqual(actions, ['--grant', '--revoke']);
        }
    } finally { await new Promise(resolve => gateway.server.close(resolve)); }
});

test('collection setup stops at the state each service needs', async () => {
    const gateway = await fakeGateway();
    try {
        const grant = () => {};
        const rules = await services.prepare('server-rules', { gateway: gateway.url, grant });
        assert.equal(rules.values.rule_version, 'published');
        assert.ok(!gateway.state.requests.some(entry => entry.includes('/sessions')));
        const lobby = await services.prepare('university-record', { gateway: gateway.url, grant });
        assert.ok(lobby.values.session_id && !lobby.values.case_id);
        assert.ok(!gateway.state.requests.some(entry => entry.endsWith('/start')));
        const started = await services.prepare('discord-dms', { gateway: gateway.url, grant });
        assert.ok(started.values.session_id && !started.values.case_id);
        assert.ok(gateway.state.requests.some(entry => entry.endsWith('/start')));
        const open = await services.prepare('credential', { gateway: gateway.url, grant });
        assert.ok(open.values.case_id);
    } finally { await new Promise(resolve => gateway.server.close(resolve)); }
});

test('setup failures name the step and status without leaking the response body', async () => {
    const actions = [];
    const gateway = await fakeGateway();
    gateway.server.removeAllListeners('request');
    gateway.server.on('request', (request, response) => { response.writeHead(500); response.end('{"secret":"PRIVATE_SENTINEL"}'); });
    try {
        await assert.rejects(services.prepare('server-rules', { gateway: gateway.url, grant: (id, action) => actions.push(action) }), error => error.safe && !error.message.includes('PRIVATE_SENTINEL') && /HTTP 500/.test(error.message));
        assert.deepEqual(actions, []);
    } finally { await new Promise(resolve => gateway.server.close(resolve)); }
});

test('a ban case is replaced until the applicant has a University identity', async () => {
    const gateway = await fakeGateway({ identityOnAttempt: 3 });
    try {
        const fixture = await services.prepare('moderation', { gateway: gateway.url, grant: () => {} });
        gateway.state.applicants = 0;
        gateway.state.rejected = 0;
        assert.ok(await fixture.freshCase());
        assert.equal(gateway.state.rejected, 2);
    } finally { await new Promise(resolve => gateway.server.close(resolve)); }
});
