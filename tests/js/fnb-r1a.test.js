const assert = require('node:assert/strict');
const { createController, escapeHtml } = require('../../static/js/fnb-r1a.js');

function floor(revision = 2) {
    return {
        changed: true,
        shop_id: 1,
        fnb_revision: revision,
        areas: [{
            id: 10,
            name: 'Trong nhà',
            active: true,
            tables: [
                { id: 20, name: 'Bàn 1', active: true, state: 'EMPTY', state_version: 4, session: null },
                { id: 21, name: 'Bàn 2', active: true, state: 'SERVING', state_version: 8,
                    session: { id: 31, revision: 6 } },
            ],
        }],
    };
}

function session(revision = 3) {
    return {
        id: 30,
        shop_id: 1,
        revision,
        tables: [{ id: 20, name: 'Bàn 1', state_version: 5 }],
        lines: [{ id: 40, product_id: 7, quantity: 2, cancelled_quantity: 0, state_version: 9 }],
        subtotal_vnd: 20000,
    };
}

function makeDeps(overrides = {}) {
    let uuidIndex = 0;
    const renders = [];
    const timers = [];
    const cleared = [];
    return {
        request: async () => floor(),
        render: event => renders.push(event),
        setTimeoutFn: (callback, delay) => {
            timers.push({ callback, delay });
            return timers.length;
        },
        clearTimeoutFn: id => cleared.push(id),
        storage: new Map(),
        now: () => 1_000,
        uuid: () => `operation-${++uuidIndex}`,
        username: 'lan',
        role: 'SELLER',
        staffRole: null,
        renders,
        timers,
        cleared,
        ...overrides,
    };
}

async function loadedController(overrides = {}) {
    const deps = makeDeps(overrides);
    const controller = createController(deps);
    await controller.selectShop(1);
    return { controller, deps };
}

async function testLateFloorResponseIsIgnoredAfterShopChange() {
    const pending = [];
    const deps = makeDeps({
        request: endpoint => new Promise(resolve => pending.push({ endpoint, resolve })),
    });
    const controller = createController(deps);
    const first = controller.selectShop(1);
    const second = controller.selectShop(2);
    pending.find(row => row.endpoint.includes('shop_id=2')).resolve({
        changed: true, shop_id: 2, fnb_revision: 2, areas: [],
    });
    await second;
    pending.find(row => row.endpoint.includes('shop_id=1')).resolve({
        changed: true, shop_id: 1, fnb_revision: 9, areas: [{ id: 9, tables: [] }],
    });
    await first;
    assert.equal(controller.getState().shopId, 2);
    assert.deepEqual(controller.getState().floor.areas, []);
}

async function testPollingAndLifecycle() {
    const replies = [floor(4), { changed: false, fnb_revision: 4 }];
    const endpoints = [];
    const deps = makeDeps({
        request: async endpoint => {
            endpoints.push(endpoint);
            return replies.shift();
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    const floorRenders = deps.renders.filter(event => event.type === 'floor').length;
    await controller.loadFloor(false);
    assert.match(endpoints[1], /after_revision=4/);
    assert.equal(deps.renders.filter(event => event.type === 'floor').length, floorRenders);
    assert.equal(deps.timers.at(-1).delay, 2_000);
    controller.dispose();
    assert.ok(deps.cleared.length > 0);

    const hidden = makeDeps({ isHidden: () => true });
    const background = createController(hidden);
    await background.selectShop(1);
    assert.equal(hidden.timers.at(-1).delay, 10_000);
}

async function testSessionAnnouncementsOnlyFollowMutations() {
    const replies = [floor(), session()];
    const deps = makeDeps({ request: async () => replies.shift() });
    const controller = createController(deps);
    await controller.selectShop(1);
    await controller.loadSession(30);
    assert.equal(deps.renders.at(-1).saved, false);

    deps.request = async endpoint => endpoint.startsWith('/fnb/floor') ? floor() : session(4);
    await controller.addLine({ product_id: 7, quantity: 1, note: '' });
    const savedSession = deps.renders.findLast(event => event.type === 'session');
    assert.equal(savedSession.saved, true);
}

async function testConflictKeepsDraftAndUsesAuthoritativeSnapshot() {
    const draft = { product_id: 7, quantity: 2, note: 'Ít đá' };
    const latest = { ...session(3), lines: [] };
    const deps = makeDeps({
        request: async endpoint => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            const error = new Error('changed');
            error.status = 409;
            error.code = 'FNB_SESSION_CHANGED';
            error.detail = { code: 'FNB_SESSION_CHANGED', snapshot: latest };
            throw error;
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    controller.seedSession(session(2));
    await assert.rejects(controller.addLine(draft));
    assert.deepEqual(controller.getState().session, latest);
    assert.deepEqual(controller.getState().recoverableDraft, draft);
    assert.equal(deps.renders.at(-1).type, 'conflict');
}

async function testSingleFlightRetryAndDefinitiveFailure() {
    let resolveRequest;
    const calls = [];
    const deps = makeDeps({
        request: endpoint => {
            if (endpoint.startsWith('/fnb/floor')) return Promise.resolve(floor());
            calls.push({ endpoint, body: arguments[2] });
            return new Promise(resolve => { resolveRequest = resolve; });
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    controller.seedSession(session());
    const first = controller.addLine({ product_id: 7, quantity: 1, note: '' });
    const second = controller.addLine({ product_id: 7, quantity: 1, note: '' });
    assert.strictEqual(first, second);
    assert.equal(calls.length, 1);
    resolveRequest(session(4));
    await first;

    let attempt = 0;
    const bodies = [];
    const retryDeps = makeDeps({
        request: async (endpoint, method, body) => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            bodies.push(body);
            attempt += 1;
            if (attempt === 1) throw new Error('offline');
            return session(4);
        },
    });
    const retry = createController(retryDeps);
    await retry.selectShop(1);
    retry.seedSession(session());
    await assert.rejects(retry.addLine({ product_id: 7, quantity: 1, note: 'Nóng' }));
    const key = [...retryDeps.storage.keys()][0];
    assert.match(key, /lan.*1.*30/);
    await retry.addLine({ product_id: 7, quantity: 1, note: 'Nóng' });
    assert.equal(bodies[0].operation_id, bodies[1].operation_id);

    const rejectedBodies = [];
    const rejectedDeps = makeDeps({
        request: async (endpoint, method, body) => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            rejectedBodies.push(body);
            if (rejectedBodies.length === 1) {
                const error = new Error('bad');
                error.status = 400;
                throw error;
            }
            return session(4);
        },
    });
    const rejected = createController(rejectedDeps);
    await rejected.selectShop(1);
    rejected.seedSession(session());
    await assert.rejects(rejected.addLine({ product_id: 7, quantity: 1, note: '' }));
    await rejected.addLine({ product_id: 7, quantity: 1, note: '' });
    assert.notEqual(rejectedBodies[0].operation_id, rejectedBodies[1].operation_id);
}

async function testLatestRevisionBodies() {
    const calls = [];
    const deps = makeDeps({
        request: async (endpoint, method, body) => {
            if (endpoint.startsWith('/fnb/floor')) return floor(12);
            calls.push({ endpoint, method, body });
            return session(Number(body.expected_revision || 0) + 1);
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    controller.seedSession(session(14));
    await controller.cancelLine(40, 1);
    assert.deepEqual(calls.at(-1).body, {
        line_id: 40,
        quantity: 1,
        expected_line_version: 9,
        expected_revision: 14,
        operation_id: calls.at(-1).body.operation_id,
    });

    controller.seedSession(session(20));
    await controller.moveTable(20, 21);
    assert.equal(calls.at(-1).body.expected_revision, 20);
    assert.equal(calls.at(-1).body.expected_from_state_version, 5);
    assert.equal(calls.at(-1).body.expected_to_state_version, 8);

    controller.seedSession(session(25));
    await controller.mergeTable(21);
    assert.equal(calls.at(-1).body.expected_revision, 25);
    assert.equal(calls.at(-1).body.expected_target_session_revision, 6);

    controller.seedSession(session(30));
    await controller.cancelSession('Khách đổi ý');
    assert.equal(calls.at(-1).body.expected_revision, 30);
}

async function testSetupMutationsAndAccess() {
    const calls = [];
    const deps = makeDeps({
        request: async (endpoint, method, body) => {
            calls.push({ endpoint, method, body });
            if (endpoint.startsWith('/fnb/floor')) return floor(7);
            return { ...body, id: 99, state_version: 5, fnb_revision: 8 };
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    await controller.createArea({ name: 'Sân', sort_order: 2 });
    assert.equal(calls[1].body.expected_revision, 7);
    assert.equal(calls.filter(call => call.endpoint.startsWith('/fnb/floor')).length, 2);

    await controller.createTable({ area_id: 10, name: 'Bàn 3', sort_order: 3 });
    assert.equal(calls.at(-2).body.operation_id.startsWith('operation-'), true);
    await controller.updateTable(20, { name: 'Bàn VIP' });
    assert.equal(calls.at(-2).body.expected_state_version, 4);

    const duplicateDeps = makeDeps({
        request: async endpoint => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            const error = new Error('exists');
            error.status = 409;
            error.code = 'FNB_NAME_EXISTS';
            throw error;
        },
    });
    const duplicate = createController(duplicateDeps);
    await duplicate.selectShop(1);
    const values = { name: 'Trùng', sort_order: 0 };
    await assert.rejects(duplicate.createArea(values));
    assert.deepEqual(duplicateDeps.renders.at(-1).value, values);

    for (const [role, staffRole, allowed] of [
        ['SELLER', null, true],
        ['STAFF', 'MANAGER', true],
        ['STAFF', 'CASHIER', false],
        ['STAFF', 'WAREHOUSE', false],
    ]) {
        const accessDeps = makeDeps({ role, staffRole });
        createController(accessDeps);
        assert.equal(accessDeps.renders[0].allowed, allowed);
    }
}

assert.equal(
    escapeHtml('<img src=x onerror=alert(1)>'),
    '&lt;img src=x onerror=alert(1)&gt;',
);
assert.equal(escapeHtml(`&"'`), '&amp;&quot;&#39;');

Promise.resolve()
    .then(testLateFloorResponseIsIgnoredAfterShopChange)
    .then(testPollingAndLifecycle)
    .then(testSessionAnnouncementsOnlyFollowMutations)
    .then(testConflictKeepsDraftAndUsesAuthoritativeSnapshot)
    .then(testSingleFlightRetryAndDefinitiveFailure)
    .then(testLatestRevisionBodies)
    .then(testSetupMutationsAndAccess)
    .then(() => process.stdout.write('fnb-r1a controller ok\n'));
