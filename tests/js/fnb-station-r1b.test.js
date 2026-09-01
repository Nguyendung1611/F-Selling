const assert = require('node:assert/strict');
const { createStationController } = require('../../static/js/fnb-station-r1b.js');

function queue(revision = 3) {
    return { changed: true, station: 'KITCHEN', revision, tickets: [
        { id: 7, status: 'NEW', state_version: 0, tables: ['Bàn 1'], items: [] },
    ] };
}

async function run() {
    const calls = [];
    const renders = [];
    const clearedTimers = [];
    let operation = 0;
    const controller = createStationController({
        request: async (endpoint, method, body) => {
            calls.push({ endpoint, method, body });
            if (method === 'POST') return { ...queue(4).tickets[0], status: 'IN_PROGRESS', state_version: 1, revision: 4 };
            return queue();
        },
        render: event => renders.push(event),
        uuid: () => `queue-op-${++operation}`,
        setTimeoutFn: () => 1,
        clearTimeoutFn: timer => clearedTimers.push(timer),
        isHidden: () => false,
    });
    await controller.start(1, 'KITCHEN');
    assert.equal(renders.at(-1).type, 'queue');
    await controller.transition(7, 'start');
    assert.equal(calls[1].endpoint, '/fnb/tickets/7/start');
    assert.equal(calls[1].body.expected_state_version, 0);
    assert.match(calls[1].body.operation_id, /^queue-op-/);
    await controller.load(false);
    assert.match(calls.at(-1).endpoint, /after_revision=4/);
    assert.deepEqual(clearedTimers, [1], 'manual reload must replace the scheduled poll');

    let attempts = 0;
    const bodies = [];
    const retry = createStationController({
        request: async (endpoint, method, body) => {
            if (method !== 'POST') return queue();
            bodies.push(body);
            attempts += 1;
            if (attempts === 1) throw new Error('offline');
            return { ...queue().tickets[0], status: 'IN_PROGRESS', state_version: 1, revision: 4 };
        },
        render: () => {}, uuid: () => 'same-operation',
        setTimeoutFn: () => 1, clearTimeoutFn: () => {}, isHidden: () => false,
    });
    await retry.start(1, 'KITCHEN');
    await assert.rejects(retry.transition(7, 'start'));
    await retry.transition(7, 'start');
    assert.equal(bodies[0].operation_id, bodies[1].operation_id);
}

run().then(() => process.stdout.write('fnb station controller ok\n'));
