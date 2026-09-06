'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const { FakeIndexedDB, clone, keyString } = require('./offline-ban-v1.test.js');

const SOURCE = fs.readFileSync('static/js/offline-ban.js', 'utf8');
const DB = 'fselling-offline';
const TOKEN_A = 'A'.repeat(43);
const TOKEN_B = 'B'.repeat(43);
const TOKEN_C = 'C'.repeat(43);
const IDENTITY_KEY = JSON.stringify([1, 11, 'alice', 'dev_00000000-0000-4000-8000-000000000001']);

function stores(receipts = [], credentials = [credential()]) {
    return {
        phieu: { keyPath: 'offline_uuid', indexes: [{ name: 'shop_id', keyPath: 'shop_id' }] },
        anhchup: { keyPath: 'khoa' },
        credential_v1: { keyPath: 'lease_id', rows: credentials },
        catalog_v1: { keyPath: 'lease_id' },
        receipt_v1: { keyPath: 'offline_uuid', rows: receipts },
        meta_v1: { keyPath: 'key' },
        sync_lock_v1: { keyPath: 'lock_name' }
    };
}

function credential(overrides = {}) {
    return {
        lease_id: 'lse_0000000000000000000001', shop_id: 1, user_id: 11,
        username: 'alice', device_id: 'dev_00000000-0000-4000-8000-000000000001',
        identity_key: IDENTITY_KEY, contract_version: 1, local_state: 'ACTIVE',
        status: 'ACTIVE', sealed: false, lease_token: TOKEN_A,
        catalog_version: 7, catalog_snapshot_digest: 'd'.repeat(64),
        server_anchor_id: 'anc_0000000000000000000001',
        anchor_server_time_utc: '2026-08-13 01:00:00.000000',
        issued_at: '2026-08-13 01:00:00.000000',
        expires_at: '2099-08-13 01:00:00.000000', state_version: 0,
        ...overrides
    };
}

function receipt(sequence, overrides = {}) {
    return {
        contract_version: 1, state: 'READY', attempt_count: 0,
        identity_key: IDENTITY_KEY, username: 'alice', shop_id: 1, user_id: 11,
        lease_id: 'lse_0000000000000000000001',
        device_id: 'dev_00000000-0000-4000-8000-000000000001',
        offline_session_id: 'lse_0000000000000000000001', sequence,
        offline_uuid: `off_00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
        sold_at_client_utc: '2026-08-13 01:00:01.000000', client_monotonic_ms: 1000,
        monotonic_valid: true, server_anchor_id: 'anc_0000000000000000000001',
        catalog_version: 7, catalog_snapshot_digest: 'd'.repeat(64),
        client_fingerprint: String(sequence).padStart(64, 'a'),
        items: [{ product_id: 2, product_name: 'Cà phê', unit_price_vnd: 25000, quantity: 2 }],
        cash_tendered: 50000, ...overrides
    };
}

function response(status, body, retryAfter = null) {
    return {
        status,
        text: async () => body === undefined ? '' : JSON.stringify(body),
        headers: { get: name => name.toLowerCase() === 'retry-after' ? retryAfter : null }
    };
}

function ack(row, created = true, orderId = 9001) {
    return {
        contract_version: 1, order_id: orderId, offline_uuid: row.offline_uuid,
        total: 50000, shift_id: 17, sold_by_user_id: 11, synced_by_user_id: 11,
        sold_at_effective: '2026-08-13 01:00:01.000000',
        time_confidence: 'ANCHORED_CLIENT', server_time_utc: '2026-08-13 01:00:02.000000',
        issues: [], created
    };
}

function memoryStorage(entries = []) {
    const values = new Map(entries);
    return {
        getItem: key => values.has(key) ? values.get(key) : null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: key => values.delete(key),
        key: index => Array.from(values.keys())[index] ?? null,
        get length() { return values.size; }
    };
}

function webLocks() {
    const held = new Set();
    return {
        request: async (name, options, callback) => {
            if (held.has(name)) return callback(null);
            held.add(name);
            try { return await callback({ name, mode: options.mode }); }
            finally { held.delete(name); }
        }
    };
}

function fakeTimers(clock) {
    let nextId = 1;
    const tasks = new Map();
    return {
        setTimeout(callback, delay) {
            const id = nextId++;
            tasks.set(id, { callback, at: clock.value + Number(delay) });
            return id;
        },
        clearTimeout(id) { tasks.delete(id); },
        count() { return tasks.size; },
        nextAt() {
            return tasks.size ? Math.min(...Array.from(tasks.values(), task => task.at)) : null;
        },
        async advance(milliseconds) {
            const target = clock.value + milliseconds;
            while (true) {
                const due = Array.from(tasks.entries())
                    .filter(([, task]) => task.at <= target)
                    .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
                if (!due) break;
                tasks.delete(due[0]);
                clock.value = due[1].at;
                await due[1].callback();
            }
            clock.value = target;
            await new Promise(resolve => setImmediate(resolve));
        }
    };
}

function load(fake, clock, fetcher, options = {}) {
    const context = {
        console, indexedDB: fake, crypto: global.crypto, structuredClone,
        TextEncoder, TextDecoder, Date, Math, JSON, Promise, Map, Set,
        setTimeout, clearTimeout, setImmediate,
        setInterval: options.setInterval || setInterval,
        clearInterval: options.clearInterval || clearInterval,
        localStorage: options.localStorage || memoryStorage([['username', 'alice']]),
        sessionStorage: memoryStorage(),
        navigator: { onLine: true, ...(options.webLocks === false ? {} : { locks: options.locks || webLocks() }) },
        addEventListener: () => {}, getToken: () => 'current-jwt', currentLanguage: () => 'vi',
        apiCall: async () => { throw new Error('generic apiCall must not be used by v1 sync'); },
        clearAuthState: () => { throw new Error('401 sync must not clear auth'); }
    };
    context.window = context;
    context.__FSellingOfflineSyncTestHooks = {
        now: () => clock.value, random: () => 0.5, fetch: fetcher,
        tab_id: options.tabId || 'tab-one',
        setInterval: options.setInterval || setInterval,
        clearInterval: options.clearInterval || clearInterval,
        setTimeout: options.syncSetTimeout,
        clearTimeout: options.syncClearTimeout
    };
    vm.createContext(context);
    vm.runInContext(SOURCE, context, { filename: 'static/js/offline-ban.js' });
    return context;
}

function seed(receipts, credentials) {
    const fake = new FakeIndexedDB();
    fake.seed(DB, 3, stores(receipts, credentials));
    return fake;
}

function rows(fake) { return fake.inspect(DB, 'receipt_v1'); }
function row(fake, uuid) { return rows(fake).find(item => item.offline_uuid === uuid); }
async function settle(turns = 12) {
    for (let index = 0; index < turns; index += 1) {
        await new Promise(resolve => setImmediate(resolve));
    }
}

async function successAndIdempotentAck() {
    const first = receipt(1);
    const second = receipt(2);
    const fake = seed([first, second]);
    const clock = { value: Date.parse('2026-08-13T01:05:00Z') };
    const calls = [];
    const context = load(fake, clock, async (url, options) => {
        calls.push({ url, options: clone(options) });
        const body = JSON.parse(options.body);
        return response(200, ack(body, body.sequence === 1, 9000 + body.sequence));
    });
    const result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice', user_id: 11 });
    assert.deepEqual(JSON.parse(JSON.stringify(result)), {
        acked: 2, blocked: 0, quarantined: 0, pending: 0, paused: false
    });
    assert.equal(calls.length, 2);
    assert.equal(calls[0].url, '/api/orders/1/offline');
    assert.equal(calls[0].options.headers.Authorization, 'Bearer current-jwt');
    assert.equal(calls[0].options.headers['X-Offline-Lease-Token'], TOKEN_A);
    const sent = JSON.parse(calls[0].options.body);
    assert.deepEqual(Object.keys(sent).sort(), [
        'cash_tendered', 'catalog_snapshot_digest', 'catalog_version', 'client_fingerprint',
        'client_monotonic_ms', 'device_id', 'items', 'lease_id', 'monotonic_valid',
        'offline_contract_version', 'offline_session_id', 'offline_uuid', 'sequence',
        'server_anchor_id', 'sold_at_client_utc'
    ]);
    for (const tombstone of rows(fake)) {
        assert.deepEqual(Object.keys(tombstone).sort(), [
            'acked_at', 'offline_uuid', 'order_id', 'sold_at', 'state', 'total'
        ]);
        assert.equal(tombstone.state, 'ACKED');
    }
    assert(!JSON.stringify(rows(fake)).includes(TOKEN_A));
}

async function transientAuthAndBackoff() {
    const invalid = receipt(1);
    let fake = seed([invalid]);
    let clock = { value: Date.parse('2026-08-13T02:00:00Z') };
    let context = load(fake, clock, async () => ({
        status: 200, text: async () => '{truncated', headers: { get: () => null }
    }));
    let result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    let saved = row(fake, invalid.offline_uuid);
    assert.equal(result.paused, true);
    assert.equal(saved.state, 'RETRYABLE');
    assert.equal(saved.attempt_count, 1);
    assert.equal(Date.parse(saved.next_attempt_at), clock.value + 2000);
    assert.deepEqual(saved.last_error, { code: 'SYNC_INVALID_ACK', http_status: 200 });

    const unauthorized = receipt(2);
    delete unauthorized.attempt_count;
    const untouched = receipt(3);
    fake = seed([unauthorized, untouched]);
    let loggedIn = false;
    context = load(fake, clock, async (url, options) => loggedIn
        ? response(200, ack(JSON.parse(options.body), false))
        : response(401, { detail: { code: 'AUTH_INVALID', message: TOKEN_A } }));
    result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    saved = row(fake, unauthorized.offline_uuid);
    assert.equal(result.paused, true);
    assert.equal(saved.state, 'READY');
    assert.equal(Object.prototype.hasOwnProperty.call(saved, 'attempt_count'), false);
    assert.equal(Object.prototype.hasOwnProperty.call(saved, 'last_error'), false);
    assert.equal(row(fake, untouched.offline_uuid).attempt_count, 0);
    assert(!JSON.stringify(rows(fake)).includes('message'));
    let summary = await context.OfflineBan.getSyncSummaryV1({ shop_id: 1, username: 'alice' });
    assert.equal(summary.paused, true);
    assert.equal(summary.state_counts.READY, 2);
    assert.deepEqual(JSON.parse(JSON.stringify(summary.error)), { code: 'AUTH_INVALID', http_status: 401 });
    loggedIn = true;
    result = await context.OfflineBan.resumeSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.acked, 2);
    summary = await context.OfflineBan.getSyncSummaryV1({ shop_id: 1, username: 'alice' });
    assert.equal(summary.paused, false);
    assert.equal(summary.pending, 0);

    for (const status of [402, 403]) {
        const denied = receipt(status);
        fake = seed([denied]);
        let deniedAllow = false;
        let deniedCalls = 0;
        context = load(fake, clock, async (url, options) => {
            deniedCalls += 1;
            return deniedAllow
                ? response(200, ack(JSON.parse(options.body)))
                : response(status, {
                    detail: { code: `SYNC_HTTP_${status}`, message: TOKEN_A }
                });
        });
        result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
        assert.equal(result.paused, true);
        assert.equal(row(fake, denied.offline_uuid).state, 'READY');
        await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
        assert.equal(deniedCalls, 1);
        deniedAllow = true;
        result = await context.OfflineBan.resumeSyncV1({ shop_id: 1, username: 'alice' });
        assert.equal(result.acked, 1);
    }

    const limited = receipt(4);
    fake = seed([limited]);
    context = load(fake, clock, async () => response(429, { detail: { code: 'TOO_MANY_REQUESTS' } }, '7'));
    await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    saved = row(fake, limited.offline_uuid);
    assert.equal(Date.parse(saved.next_attempt_at), clock.value + 7000);

    const malformedRetryAfter = receipt(6);
    fake = seed([malformedRetryAfter]);
    context = load(fake, clock, async () => response(429, {
        detail: { code: 'TOO_MANY_REQUESTS' }
    }, 'not-a-date'));
    await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(Date.parse(row(fake, malformedRetryAfter.offline_uuid).next_attempt_at), clock.value + 2000);

    const longCycle = receipt(5, { attempt_count: 49 });
    fake = seed([longCycle]);
    context = load(fake, clock, async () => response(503, { detail: { code: 'UPSTREAM_DOWN' } }));
    await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    saved = row(fake, longCycle.offline_uuid);
    assert.equal(saved.attempt_count, 50);
    assert.equal(Date.parse(saved.next_attempt_at), clock.value + 30 * 60 * 1000);
}

async function hardPauseRestoresReceiptExactly() {
    const original = receipt(77, {
        state: 'RETRYABLE', attempt_count: 7,
        next_attempt_at: '2026-08-13T01:59:59.000Z',
        last_error: { code: 'PREVIOUS_TRANSIENT', http_status: 503 }
    });
    const fake = seed([original]);
    const clock = { value: Date.parse('2026-08-13T02:00:00Z') };
    const timers = fakeTimers(clock);
    let allow = false;
    let sends = 0;
    const context = load(fake, clock, async (url, options) => {
        sends += 1;
        return allow
            ? response(200, ack(JSON.parse(options.body)))
            : response(401, { detail: { code: 'AUTH_INVALID', message: TOKEN_A } });
    }, {
        syncSetTimeout: timers.setTimeout,
        syncClearTimeout: timers.clearTimeout
    });
    let result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.paused, true);
    const restored = row(fake, original.offline_uuid);
    for (const field of ['state', 'attempt_count', 'next_attempt_at', 'last_error']) {
        assert.deepEqual(restored[field], original[field]);
    }
    result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.paused, true);
    assert.equal(sends, 1);
    const onlineWake = context.OfflineBan.batTuDongBoV1(
        () => ({ shop_id: 1, username: 'alice' }),
        () => {}
    );
    await settle();
    assert.equal(timers.count(), 0);
    await onlineWake();
    assert.equal(sends, 1);
    allow = true;
    result = await context.OfflineBan.resumeSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.acked, 1);
}

async function automaticRetryScheduler() {
    for (const failure of ['network', 'server', 'rate']) {
        const pending = receipt(failure === 'network' ? 81 : failure === 'server' ? 82 : 83);
        const fake = seed([pending]);
        const clock = { value: Date.parse('2026-08-13T02:30:00Z') };
        const timers = fakeTimers(clock);
        let sends = 0;
        const context = load(fake, clock, async (url, options) => {
            sends += 1;
            if (sends > 1) return response(200, ack(JSON.parse(options.body)));
            if (failure === 'network') throw new Error('offline');
            if (failure === 'rate') {
                return response(429, { detail: { code: 'TOO_MANY_REQUESTS' } }, '7');
            }
            return response(503, { detail: { code: 'UPSTREAM_DOWN' } });
        }, {
            syncSetTimeout: timers.setTimeout,
            syncClearTimeout: timers.clearTimeout
        });
        context.OfflineBan.batTuDongBoV1(
            () => ({ shop_id: 1, username: 'alice' }),
            () => {}
        );
        await settle();
        assert.equal(timers.count(), 1);
        await timers.advance(1500);
        assert.equal(sends, 1);
        const deadline = clock.value + (failure === 'rate' ? 7000 : 2000);
        assert.equal(timers.count(), 1);
        assert.equal(timers.nextAt(), deadline);
        const early = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
        assert.equal(early.paused, true);
        assert.equal(sends, 1);
        assert.equal(timers.count(), 1);
        await timers.advance(deadline - clock.value - 1);
        assert.equal(sends, 1);
        await timers.advance(1);
        assert.equal(sends, 2);
        assert.equal(row(fake, pending.offline_uuid).state, 'ACKED');
        assert.equal(timers.count(), 0);
    }

    const reloadPending = receipt(84);
    const reloadFake = seed([reloadPending]);
    const reloadClock = { value: Date.parse('2026-08-13T02:45:00Z') };
    let first = load(reloadFake, reloadClock, async () => response(503, {}));
    await first.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    const persistedDeadline = Date.parse(row(reloadFake, reloadPending.offline_uuid).next_attempt_at);
    const reloadTimers = fakeTimers(reloadClock);
    let reloadSends = 0;
    const reloaded = load(reloadFake, reloadClock, async (url, options) => {
        reloadSends += 1;
        return response(200, ack(JSON.parse(options.body)));
    }, {
        syncSetTimeout: reloadTimers.setTimeout,
        syncClearTimeout: reloadTimers.clearTimeout
    });
    reloaded.OfflineBan.batTuDongBoV1(
        () => ({ shop_id: 1, username: 'alice' }),
        () => {}
    );
    await settle();
    assert.equal(reloadTimers.count(), 1);
    assert.equal(reloadTimers.nextAt(), persistedDeadline);
    await reloadTimers.advance(persistedDeadline - reloadClock.value);
    assert.equal(reloadSends, 1);
    assert.equal(row(reloadFake, reloadPending.offline_uuid).state, 'ACKED');

    const longPending = receipt(85, { attempt_count: 49 });
    const longFake = seed([longPending]);
    const longClock = { value: Date.parse('2026-08-13T03:00:00Z') };
    const longTimers = fakeTimers(longClock);
    const longContext = load(longFake, longClock, async () => response(503, {}), {
        syncSetTimeout: longTimers.setTimeout,
        syncClearTimeout: longTimers.clearTimeout
    });
    longContext.OfflineBan.batTuDongBoV1(
        () => ({ shop_id: 1, username: 'alice' }),
        () => {}
    );
    await settle();
    await longTimers.advance(1500);
    assert.equal(longTimers.count(), 1);
    assert.equal(longTimers.nextAt(), longClock.value + 30 * 60 * 1000);
}

async function permanentErrorsContinue() {
    const blocked = receipt(1);
    const quarantined = receipt(2);
    const good = receipt(3);
    const fake = seed([blocked, quarantined, good]);
    const clock = { value: Date.parse('2026-08-13T03:00:00Z') };
    const context = load(fake, clock, async (url, options) => {
        const body = JSON.parse(options.body);
        if (body.sequence === 1) return response(409, { detail: { code: 'OFFLINE_LEASE_REVOKED' } });
        if (body.sequence === 2) {
            return response(409, { detail: { code: 'OFFLINE_RECEIPT_FINGERPRINT_CONFLICT' } });
        }
        return response(200, ack(body));
    });
    const result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.paused, false);
    assert.equal(result.blocked, 1);
    assert.equal(result.quarantined, 1);
    assert.equal(result.acked, 1);
    assert.equal(row(fake, blocked.offline_uuid).state, 'BLOCKED_RECOVERABLE');
    assert.equal(row(fake, quarantined.offline_uuid).state, 'QUARANTINED');
    assert.equal(row(fake, good.offline_uuid).state, 'ACKED');

    const unknown = receipt(4);
    const unknownFake = seed([unknown]);
    const unknownContext = load(unknownFake, clock, async () => response(418, {
        detail: { code: 'UNRECOGNIZED_CLIENT_ERROR' }
    }));
    const unknownResult = await unknownContext.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(unknownResult.paused, true);
    assert.equal(row(unknownFake, unknown.offline_uuid).state, 'RETRYABLE');
}

async function reclaimSealedCredential() {
    const pending = receipt(1);
    const sealed = credential({ sealed: true, local_state: 'SEALED' });
    const fake = seed([pending], [sealed]);
    const clock = { value: Date.parse('2026-08-13T04:00:00Z') };
    const calls = [];
    const context = load(fake, clock, async (url, options) => {
        calls.push({ url, options: clone(options) });
        if (url.includes('/reclaim')) {
            return response(200, {
                ...sealed, status: 'SYNC_ONLY', state_version: 1,
                lease_token: TOKEN_B, sealed: undefined, local_state: undefined,
                identity_key: undefined, username: undefined
            });
        }
        return response(200, ack(JSON.parse(options.body)));
    });
    const result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice', user_id: 11 });
    assert.equal(result.acked, 1);
    assert.equal(calls[0].url, `/api/offline/leases/${sealed.lease_id}/reclaim`);
    assert.deepEqual(JSON.parse(calls[0].options.body), { expected_state_version: 0 });
    assert.equal(calls[0].options.headers['X-Offline-Lease-Token'], undefined);
    assert.equal(calls[1].options.headers['X-Offline-Lease-Token'], TOKEN_B);
    const savedCredential = fake.inspect(DB, 'credential_v1')[0];
    assert.equal(savedCredential.lease_token, TOKEN_B);
    assert.equal(savedCredential.sealed, false);

    const deniedReceipt = receipt(2);
    const deniedFake = seed([deniedReceipt], [sealed]);
    const deniedContext = load(deniedFake, clock, async () => response(403, {
        detail: { code: 'OFFLINE_LEASE_RECLAIM_DENIED', message: TOKEN_A }
    }));
    const denied = await deniedContext.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice', user_id: 11 });
    assert.equal(denied.paused, true);
    assert.equal(row(deniedFake, deniedReceipt.offline_uuid).state, 'READY');
    assert.equal(deniedFake.inspect(DB, 'credential_v1')[0].sealed, true);
    assert(!JSON.stringify(rows(deniedFake)).includes(TOKEN_A));

    const lostReceipt = receipt(4);
    const lostFake = seed([lostReceipt], [sealed]);
    const expectedVersions = [];
    const lostContext = load(lostFake, clock, async (url, options) => {
        if (url.includes('/reclaim')) {
            const expected = JSON.parse(options.body).expected_state_version;
            expectedVersions.push(expected);
            if (expected === 0) {
                return response(409, { detail: {
                    code: 'OFFLINE_LEASE_STATE_CONFLICT', current_state_version: 1
                } });
            }
            return response(200, {
                ...sealed, status: 'SYNC_ONLY', state_version: 2,
                lease_token: TOKEN_B, sealed: undefined, local_state: undefined,
                identity_key: undefined, username: undefined
            });
        }
        return response(200, ack(JSON.parse(options.body), false));
    });
    const recovered = await lostContext.OfflineBan.triggerSyncV1({
        shop_id: 1, username: 'alice', user_id: 11
    });
    assert.equal(recovered.acked, 1);
    assert.deepEqual(expectedVersions, [0, 1]);
    const recoveredCredential = lostFake.inspect(DB, 'credential_v1')[0];
    assert.equal(recoveredCredential.state_version, 2);
    assert.equal(recoveredCredential.lease_token, TOKEN_B);

    let fetchCount = 0;
    const bobContext = load(seed([receipt(3)]), clock, async () => { fetchCount += 1; }, {
        localStorage: memoryStorage([['username', 'bob']])
    });
    const wrongIdentity = await bobContext.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(wrongIdentity.paused, true);
    assert.equal(fetchCount, 0);
}

async function crashRestartAndCleanup() {
    const pending = receipt(1);
    const oldAck = {
        offline_uuid: 'old-ack', state: 'ACKED', order_id: 1,
        sold_at: '2026-06-01 00:00:00.000000', total: 1,
        acked_at: '2026-06-01T00:00:00.000Z', contract_version: 1,
        shop_id: 1, user_id: 11, username: 'alice'
    };
    const blocked = receipt(8, { state: 'BLOCKED_RECOVERABLE' });
    const fake = seed([pending, oldAck, blocked]);
    const clock = { value: Date.parse('2026-08-13T05:00:00Z') };
    let context = load(fake, clock, async () => { throw new Error(`network ${TOKEN_A}`); });
    await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(row(fake, pending.offline_uuid).state, 'RETRYABLE');
    assert.equal(row(fake, 'old-ack'), undefined);
    assert.equal(row(fake, blocked.offline_uuid).state, 'BLOCKED_RECOVERABLE');

    clock.value += 2000;
    context = load(fake, clock, async (url, options) => response(200, ack(JSON.parse(options.body), false)));
    const result = await context.OfflineBan.resumeSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.acked, 1);
    assert.equal(row(fake, pending.offline_uuid).state, 'ACKED');
}

async function staleAttemptAndFallbackFence() {
    const stale = receipt(1, {
        state: 'SYNCING', attempt_count: 1,
        sync_started_at: '2026-08-13T05:58:00.000Z',
        attempt_token: 'attempt_old', fence_token: 'old'
    });
    let fake = seed([stale]);
    let clock = { value: Date.parse('2026-08-13T06:00:00Z') };
    let context = load(fake, clock, async (url, options) => response(200, ack(JSON.parse(options.body))));
    let result = await context.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.acked, 1);
    assert.equal(row(fake, stale.offline_uuid).attempt_count, undefined); // ACK tombstone stripped working fields.

    const webContested = receipt(9);
    fake = seed([webContested]);
    clock = { value: Date.parse('2026-08-13T06:30:00Z') };
    const sharedLocks = webLocks();
    let resolveWeb;
    let webSends = 0;
    const webResponse = new Promise(resolve => { resolveWeb = resolve; });
    const webTabA = load(fake, clock, async () => { webSends += 1; return webResponse; }, {
        locks: sharedLocks, tabId: 'web-a'
    });
    const webTabB = load(fake, clock, async () => { webSends += 1; return response(500, {}); }, {
        locks: sharedLocks, tabId: 'web-b'
    });
    const webRunA = webTabA.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    while (row(fake, webContested.offline_uuid).state !== 'SYNCING') {
        await new Promise(resolve => setImmediate(resolve));
    }
    const webResultB = await webTabB.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(webResultB.paused, true);
    assert.equal(webResultB.error.code, 'SYNC_LOCK_BUSY');
    assert.equal(webSends, 1);
    resolveWeb(response(200, ack(webContested)));
    assert.equal((await webRunA).acked, 1);

    const contested = receipt(2);
    fake = seed([contested]);
    clock = { value: Date.parse('2026-08-13T07:00:00Z') };
    let resolveOld;
    const oldResponse = new Promise(resolve => { resolveOld = resolve; });
    const noopInterval = () => 1;
    const oldTab = load(fake, clock, async () => oldResponse, {
        webLocks: false, tabId: 'old-tab', setInterval: noopInterval, clearInterval: () => {}
    });
    const oldRun = oldTab.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    while (row(fake, contested.offline_uuid).state !== 'SYNCING') {
        await new Promise(resolve => setImmediate(resolve));
    }
    clock.value += 61 * 1000; // owner chết quá TTL 15 giây và attempt quá stale 60 giây.
    const newTab = load(fake, clock, async (url, options) => response(200, ack(JSON.parse(options.body), false, 9010)), {
        webLocks: false, tabId: 'new-tab', setInterval: noopInterval, clearInterval: () => {}
    });
    result = await newTab.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(result.acked, 1);
    resolveOld(response(200, ack(contested, true, 9009)));
    const oldResult = await oldRun;
    assert.equal(oldResult.paused, true);
    assert.equal(row(fake, contested.offline_uuid).order_id, 9010);
    const lockRow = fake.inspect(DB, 'sync_lock_v1')[0];
    assert.equal(lockRow.fence, 2);

    const reclaimRace = receipt(10);
    const sealed = credential({ sealed: true, local_state: 'SEALED' });
    fake = seed([reclaimRace], [sealed]);
    clock = { value: Date.parse('2026-08-13T08:00:00Z') };
    let resolveLateReclaim;
    let reclaimStarted = false;
    const lateReclaim = new Promise(resolve => { resolveLateReclaim = resolve; });
    const reclaimTabA = load(fake, clock, async url => {
        assert(url.includes('/reclaim'));
        reclaimStarted = true;
        return lateReclaim;
    }, {
        webLocks: false, tabId: 'reclaim-old', setInterval: noopInterval, clearInterval: () => {}
    });
    const reclaimRunA = reclaimTabA.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    while (!reclaimStarted) await new Promise(resolve => setImmediate(resolve));
    clock.value += 61 * 1000;
    const newExpectedVersions = [];
    const reclaimTabB = load(fake, clock, async (url, options) => {
        if (url.includes('/reclaim')) {
            const expected = JSON.parse(options.body).expected_state_version;
            newExpectedVersions.push(expected);
            if (expected === 0) {
                return response(409, { detail: {
                    code: 'OFFLINE_LEASE_STATE_CONFLICT', current_state_version: 1
                } });
            }
            return response(200, {
                ...sealed, status: 'SYNC_ONLY', state_version: 2,
                lease_token: TOKEN_B, sealed: undefined, local_state: undefined,
                identity_key: undefined, username: undefined
            });
        }
        return response(200, ack(JSON.parse(options.body), false, 9020));
    }, {
        webLocks: false, tabId: 'reclaim-new', setInterval: noopInterval, clearInterval: () => {}
    });
    const reclaimResultB = await reclaimTabB.OfflineBan.triggerSyncV1({ shop_id: 1, username: 'alice' });
    assert.equal(reclaimResultB.acked, 1);
    assert.deepEqual(newExpectedVersions, [0, 1]);
    resolveLateReclaim(response(200, {
        ...sealed, status: 'SYNC_ONLY', state_version: 1,
        lease_token: TOKEN_C, sealed: undefined, local_state: undefined,
        identity_key: undefined, username: undefined
    }));
    assert.equal((await reclaimRunA).paused, true);
    const finalCredential = fake.inspect(DB, 'credential_v1')[0];
    assert.equal(finalCredential.state_version, 2);
    assert.equal(finalCredential.lease_token, TOKEN_B);
    assert.equal(row(fake, reclaimRace.offline_uuid).order_id, 9020);
}

async function main() {
    await successAndIdempotentAck();
    await transientAuthAndBackoff();
    await hardPauseRestoresReceiptExactly();
    await automaticRetryScheduler();
    await permanentErrorsContinue();
    await reclaimSealedCredential();
    await crashRestartAndCleanup();
    await staleAttemptAndFallbackFence();
    console.log('offline-ban-sync-v1 harness: 8 passed');
}

main().catch(error => {
    console.error(error && error.stack || error);
    process.exit(1);
});
