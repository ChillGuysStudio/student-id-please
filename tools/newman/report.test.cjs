'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { sanitize, render, verifyNoSecrets, parseArgs, executePhase } = require('./report.cjs');

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
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'lab2-native-reporter-test-'));
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
