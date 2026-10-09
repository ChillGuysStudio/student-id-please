'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { STATUS_CODES } = require('node:http');

const ROOT = path.resolve(__dirname, '../..');
const COLLECTION = path.join(ROOT, 'postman/lab2-guided-demo.postman_collection.json');
const DEFAULT_OUTPUT = path.join(ROOT, '.local/lab2-postman/newman-htmlextra.html');

function definitions() {
    const source = JSON.parse(fs.readFileSync(COLLECTION, 'utf8'));
    const items = new Map();
    const assertions = new Set();
    function visit(group, folder = 'Requests', inheritedEvents = []) {
        const events = [...inheritedEvents, ...(group.event || [])];
        for (const event of events) {
            const script = (event.script?.exec || []).join('\n');
            for (const match of script.matchAll(/pm\.test\(\s*["']([^"']+)["']/g)) assertions.add(match[1]);
        }
        if (group.item) {
            for (const item of group.item) visit(item, group.info ? folder : group.name, events);
        } else {
            items.set(group.name, { folder, method: group.request.method });
        }
    }
    visit(source);
    return { source, items, assertions };
}

// Only public collection labels and numerical run metrics reach the reporter.
// No raw URL, header, body, environment, script, failure message or stack is copied.
function sanitize(inputs) {
    if (!inputs.length) throw new Error('At least one Newman JSON file is required.');
    const { items, assertions: knownAssertions } = definitions();
    const stats = {};
    const folders = new Map();
    const executions = [];
    const failures = [];
    let started = Infinity, completed = 0, responseTotal = 0, timeTotal = 0, responseCount = 0;
    let runError = false;
    const phases = [];
    function metric(value, fallback = 0) {
        return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback;
    }
    for (const [phase, input] of inputs.entries()) {
        if (!input.run || !Array.isArray(input.run.executions) || !input.run.stats || !input.run.timings) {
            throw new Error('Not a Newman JSON report.');
        }
        const run = input.run;
        started = Math.min(started, metric(run.timings.started));
        completed = Math.max(completed, metric(run.timings.completed));
        responseTotal += metric(run.transfers?.responseTotal);
        runError ||= Boolean(run.error);
        phases.push({ requests: metric(run.stats.requests?.total), assertions: metric(run.stats.assertions?.total), failures: (run.failures || []).length });
        for (const key of ['iterations', 'items', 'scripts', 'prerequests', 'requests', 'tests', 'assertions', 'testScripts', 'prerequestScripts']) {
            const value = run.stats[key];
            if (!value) continue;
            const target = stats[key] ||= { total: 0, pending: 0, failed: 0 };
            for (const field of ['total', 'pending', 'failed']) target[field] += metric(value[field]);
        }
        for (const raw of run.executions) {
            const index = executions.length;
            const definition = items.get(raw.item?.name);
            const name = definition ? raw.item.name : `Request ${index + 1} (private label omitted)`;
            const folder = definition?.folder || 'Other requests';
            const id = `safe-request-${index + 1}`;
            const request = { method: definition?.method || 'GET', url: `http://gateway.invalid/redacted-request-${index + 1}` };
            const item = { id, name, request };
            if (!folders.has(folder)) folders.set(folder, []);
            folders.get(folder).push(item);
            const response = raw.response ? {
                code: metric(raw.response.code), status: STATUS_CODES[raw.response.code] || 'Response',
                responseTime: metric(raw.response.responseTime), responseSize: metric(raw.response.responseSize),
                stream: []
            } : undefined;
            if (response) { timeTotal += response.responseTime; responseCount++; }
            const assertions = (raw.assertions || []).map((assertion, i) => {
                const name = knownAssertions.has(assertion.assertion) ? assertion.assertion : `Assertion ${i + 1} (private label omitted)`;
                return { assertion: name, skipped: Boolean(assertion.skipped), ...(assertion.error ? {
                    error: { name: 'AssertionError', test: name, message: 'Assertion failed; private diagnostic omitted.' }
                } : {}) };
            });
            executions.push({ cursor: { ref: id, iteration: phase, position: index }, item, request, response, assertions,
                ...(raw.requestError ? { requestError: { name: 'RequestError', message: 'Request failed; private diagnostic omitted.' } } : {}) });
        }
        for (const ignored of run.failures || []) {
            failures.push({ error: { name: 'RunFailure', message: 'Failure recorded; private diagnostic omitted.' }, at: 'run', source: { name: 'Private details omitted' } });
        }
    }
    const date = new Date(started).toISOString();
    const overload = executions.some(e => e.item.name.startsWith('28 '));
    const recovery = executions.some(e => e.item.name.startsWith('29 '));
    const scope = overload && recovery ? 'Includes the recorded overload and recovery requests (28–29).' : 'Does not include a complete overload/recovery demonstration (28–29).';
    const description = `Saved run started ${date}. ${inputs.length} recorded phase(s), combined without replaying requests. URL placeholders are intentional privacy redactions, not actual targets. ${scope} No Session activation, task-timeout test or direct WebSocket frames are demonstrated by this collection. Report timestamp is the rendering time.`;
    return {
        collection: { info: { name: 'Lab 2 — Guided Gateway HTTP demo', description }, item: [...folders].map(([name, item]) => ({ name, item })) },
        run: { stats, timings: { started, completed, responseAverage: responseCount ? timeTotal / responseCount : 0 }, transfers: { responseTotal }, executions, failures,
            ...(runError ? { error: { message: 'Run error; private details omitted.' } } : {}) },
        reportMetadata: { started: date, phases, scope, failed: runError || failures.length > 0 || Object.values(stats).some(s => s.failed > 0) }
    };
}

function render(safe, output) {
    const sdk = require('postman-collection');
    const Reporter = require('newman-reporter-htmlextra');
    const emitter = new EventEmitter();
    const collection = new sdk.Collection(safe.collection);
    const itemMap = new Map();
    function visit(group) {
        group.items.each(item => item.items ? visit(item) : itemMap.set(item.id, item));
    }
    visit(collection);
    emitter.summary = { collection, run: { ...safe.run, executions: safe.run.executions.map(execution => {
        const response = execution.response ? new sdk.Response(execution.response) : undefined;
        // SDK hydration recomputes byte size from the intentionally empty body.
        // Retain the original numerical metric without retaining the body itself.
        if (response) response.responseSize = execution.response.responseSize;
        return { ...execution, item: itemMap.get(execution.item.id), request: new sdk.Request(execution.request), response };
    }) } };
    emitter.summary.skippedTests = emitter.summary.run.executions.flatMap(execution => execution.assertions
        .filter(assertion => assertion.skipped)
        .map(assertion => ({ cursor: execution.cursor, assertion: assertion.assertion, skipped: true,
            item: { id: execution.item.id, name: execution.item.name } })));
    emitter.exports = [];
    new Reporter(emitter, {
        export: output, title: `Lab 2 — ${safe.run.executions.length} requests · ${safe.reportMetadata.phases.length} saved phase(s)`, titleSize: 4,
        browserTitle: 'Lab 2 — Newman htmlextra report', skipSensitiveData: true, omitHeaders: true,
        omitRequestBodies: true, omitResponseBodies: true, showEnvironmentData: false, showGlobalData: false,
        logs: false, showFolderDescription: true, timezone: 'UTC'
    }, { newmanVersion: require('newman/package.json').version, reporters: ['htmlextra'] });
    emitter.emit('beforeDone');
    const html = emitter.exports.find(entry => entry.name === 'html-reporter-htmlextra')?.content;
    if (!html) throw new Error('htmlextra did not produce a report.');
    fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
    fs.writeFileSync(output, html, { mode: 0o600 });
    fs.chmodSync(output, 0o600);
    fs.writeFileSync(output.replace(/\.html$/i, '') + '.summary.json', JSON.stringify(safe.reportMetadata, null, 2), { mode: 0o600 });
    return html;
}

function verifyNoSecrets(inputs, html) {
    for (const input of inputs) {
        for (const scope of [input.environment, input.globals]) {
            for (const entry of scope?.values || []) {
                const value = entry.value;
                if (typeof value === 'string' && value.length >= 8 && /password|token|secret|ticket/i.test(entry.key)) {
                    const escaped = value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' }[c]));
                    if (html.includes(value) || html.includes(escaped)) throw new Error('Private environment value detected in report.');
                }
            }
        }
    }
    if (/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(html)) throw new Error('JWT detected in report.');
}

function parseArgs(args) {
    const options = { inputs: [], output: DEFAULT_OUTPUT, gateway: 'http://127.0.0.1:18080', environment: path.join(ROOT, 'postman/lab2-guided-demo.postman_environment.json'), overload: false };
    for (let i = 0; i < args.length; i++) {
        const flag = args[i];
        if (flag === '--help' || flag === '-h') { options.help = true; continue; }
        if (flag === '--with-overload') { options.overload = true; continue; }
        if (!['--from-json', '--output', '--gateway-url', '--environment'].includes(flag)) throw new Error(`Unknown option: ${flag}`);
        const value = args[++i];
        if (!value || value.startsWith('--')) throw new Error(`Missing value for ${flag}`);
        if (flag === '--from-json') options.inputs.push(path.resolve(value));
        else options[{ '--output': 'output', '--gateway-url': 'gateway', '--environment': 'environment' }[flag]] = flag === '--gateway-url' ? value : path.resolve(value);
    }
    if (!options.output.endsWith('.html')) throw new Error('--output must end in .html');
    if (options.inputs.length && options.overload) throw new Error('--with-overload cannot be combined with --from-json');
    return options;
}

function help() {
    console.log(`Usage: scripts/run_lab2_newman.sh [options]\n\nDefault: run requests 01–27 through the public Gateway and generate an htmlextra HTML report.\nThis creates disposable players, friendships, a team, a lobby and record permissions.\n\n  --from-json FILE     Render an existing Newman JSON without making requests; repeat for phases\n  --with-overload      Also run 28 under the 100-slot helper, then 29 after recovery\n                      Requires the helper's localhost Gateway at http://127.0.0.1:18080\n  --gateway-url URL    Public Gateway (default: http://127.0.0.1:18080)\n  --environment FILE   Postman environment (default: blank guided-demo environment)\n  --output FILE.html   Report path (default: .local/lab2-postman/newman-htmlextra.html)\n  --help              Show this help\n\nPrivate raw results/environments stay under ignored .local/lab2-postman/.\nReports redact URLs, all bodies/headers, environments, logs and raw diagnostics.\nSession activation and direct WebSocket frames are not tested.`);
}

async function executePhase(collection, environment) {
    const newman = require('newman');
    return new Promise((resolve, reject) => newman.run({ collection, environment,
        reporters: [], silent: true, timeoutRequest: 15000, timeoutScript: 5000
    }, (error, summary) => error ? reject(new Error('Newman failed; private diagnostic withheld.')) : resolve(summary)));
}

async function runLive(options) {
    const { spawn } = require('node:child_process');
    const { once } = require('node:events');
    const { source } = definitions();
    const gateway = new URL(options.gateway);
    if (!['http:', 'https:'].includes(gateway.protocol) || gateway.username || gateway.password || gateway.search || gateway.hash) throw new Error('Use an HTTP(S) public Gateway URL without credentials, query or fragment.');
    if (options.overload && options.gateway !== 'http://127.0.0.1:18080') throw new Error('--with-overload requires http://127.0.0.1:18080; the existing helper has a fixed local target.');
    const privateRoot = path.join(ROOT, '.local/lab2-postman');
    fs.mkdirSync(privateRoot, { recursive: true, mode: 0o700 });
    const directory = fs.mkdtempSync(path.join(privateRoot, 'run-'));
    let environment = JSON.parse(fs.readFileSync(options.environment, 'utf8'));
    environment.values = (environment.values || []).filter(value => value.key !== 'gateway_url');
    environment.values.push({ key: 'gateway_url', value: gateway.href.replace(/\/$/, ''), enabled: true });
    const results = [];
    async function execute(collection, label) {
        const summary = await executePhase(collection, environment);
        const raw = JSON.parse(JSON.stringify(summary));
        fs.writeFileSync(path.join(directory, `private-${label}.json`), JSON.stringify(raw), { mode: 0o600 });
        environment = summary.environment.toJSON();
        fs.writeFileSync(path.join(directory, 'private-environment.json'), JSON.stringify(environment), { mode: 0o600 });
        results.push(raw);
        const stat = raw.run.stats;
        console.log(`${label}: ${stat.requests.total} requests, ${stat.assertions.total - stat.assertions.failed}/${stat.assertions.total} assertions passed`);
        return !raw.run.error && !raw.run.failures.length && !Object.values(stat).some(value => value.failed > 0);
    }
    const first = { ...source, item: source.item.slice(0, 3) };
    if (!await execute(first, '01-27') || !options.overload) return results;
    const step = number => ({ ...source, item: [{ ...source.item[3], item: source.item[3].item.filter(item => item.name.startsWith(`${number} `)) }] });
    const helper = spawn('python3', [path.join(ROOT, 'postman/lab2-overload.py'), '--hold-seconds', '7'], { stdio: ['ignore', 'pipe', 'pipe'] });
    let helperError = false;
    helper.on('error', () => { helperError = true; });
    const exited = once(helper, 'close').then(([code]) => code).catch(() => -1);
    try {
        await new Promise((resolve, reject) => {
            let text = '';
            const timer = setTimeout(() => { cleanup(); reject(new Error('Overload helper did not become ready.')); }, 6000);
            function cleanup() { clearTimeout(timer); helper.stdout.off('data', data); helper.off('close', closed); helper.off('error', error); }
            function data(chunk) { text += chunk; if (text.includes('READY:')) { cleanup(); resolve(); } }
            function closed() { cleanup(); reject(new Error('Overload helper exited before READY.')); }
            function error() { cleanup(); reject(new Error('Cannot start python3 overload helper.')); }
            helper.stdout.on('data', data); helper.once('close', closed); helper.once('error', error);
        });
        console.log('Overload helper ready: testing request 28.');
        await execute(step(28), '28');
        if (await exited !== 0 || helperError) throw new Error('Overload helper failed; do not claim an overload demonstration.');
        await new Promise(resolve => setTimeout(resolve, 250));
        await execute(step(29), '29');
    } catch (error) {
        helper.kill('SIGTERM');
        await exited.catch(() => {});
        throw error;
    }
    return results;
}

async function main() {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) return help();
    let inputs;
    if (options.inputs.length) inputs = options.inputs.map(file => JSON.parse(fs.readFileSync(file, 'utf8')));
    else inputs = await runLive(options);
    const safe = sanitize(inputs);
    let html;
    try { html = render(safe, options.output); verifyNoSecrets(inputs, html); }
    catch (error) { fs.rmSync(options.output, { force: true }); throw error; }
    console.log(`HTML report: ${options.output}`);
    console.log(`${safe.run.stats.requests.total} requests; ${safe.run.stats.assertions.total - safe.run.stats.assertions.failed}/${safe.run.stats.assertions.total} assertions passed; ${safe.run.failures.length} failures`);
    process.exitCode = safe.reportMetadata.failed ? 1 : 0;
}

module.exports = { sanitize, render, verifyNoSecrets, parseArgs, executePhase };
if (require.main === module) main().catch(() => { console.error('Newman/report generation failed. Private diagnostics are withheld; check inputs, dependencies and Gateway availability.'); process.exitCode = 1; });
