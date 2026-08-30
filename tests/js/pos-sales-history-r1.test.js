'use strict';

const assert = require('assert/strict');
const { createController } = require('../../static/js/pos-sales-history-r1.js');

const row = id => ({ id, status: 'PAID', customer_name: null, total_amount: 12000 });
const page = (orders, number, more = false, searching = false) => ({
    orders, page: number, per_page: 20, has_more: more,
    searching_all_history: searching
});
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
}

(async () => {
    const paths = [];
    const controller = createController({
        getShopId: () => 7,
        request: async path => {
            paths.push(path);
            const number = Number(new URL(`http://local${path}`).searchParams.get('page'));
            return number === 1 ? page([row(3), row(2)], 1, true) : page([row(1)], 2);
        },
        onReceipt() {}
    });
    await controller.open();
    assert.deepEqual(controller.getState().orders.map(item => item.id), [3, 2]);
    assert.match(paths[0], /\/orders\/7\/history\?scope=today&page=1$/);
    await Promise.all([controller.loadMore(), controller.loadMore()]);
    assert.deepEqual(controller.getState().orders.map(item => item.id), [3, 2, 1]);
    assert.equal(paths.length, 2, 'loadMore must not run twice concurrently');

    const oldRequest = deferred();
    const newRequest = deferred();
    const racePaths = [];
    const race = createController({
        getShopId: () => 7,
        request: path => {
            racePaths.push(path);
            return racePaths.length === 1 ? oldRequest.promise : newRequest.promise;
        },
        onReceipt() {}
    });
    const oldRun = race.search('Cô Lan');
    const newRun = race.search('Mai & Bé');
    newRequest.resolve(page([row(9)], 1, false, true));
    await newRun;
    oldRequest.resolve(page([row(8)], 1, false, true));
    await oldRun;
    assert.deepEqual(race.getState().orders.map(item => item.id), [9]);
    assert.equal(new URL(`http://local${racePaths[1]}`).searchParams.get('q'), 'Mai & Bé');

    const pendingClose = deferred();
    const closing = createController({
        getShopId: () => 7,
        request: () => pendingClose.promise,
        onReceipt() {}
    });
    const closingRun = closing.open();
    closing.close();
    pendingClose.resolve(page([row(5)], 1));
    await closingRun;
    assert.equal(closing.getState().open, false);
    assert.deepEqual(closing.getState().orders, []);
    assert.equal(closing.getState().loading, false);

    let shopId = 7;
    const pendingReset = deferred();
    const resetting = createController({
        getShopId: () => shopId,
        request: () => pendingReset.promise,
        onReceipt() {}
    });
    const resetRun = resetting.open();
    shopId = 8;
    resetting.resetForShopChange();
    pendingReset.resolve(page([row(6)], 1));
    await resetRun;
    assert.deepEqual(resetting.getState().orders, []);
    assert.equal(resetting.getState().open, false);

    let receipt = null;
    const detail = createController({
        getShopId: () => 7,
        request: async path => path.endsWith('/detail')
            ? { id: 9, shop_id: 7, status: 'DEBT', items: [] }
            : page([], 1),
        onReceipt: value => { receipt = value; }
    });
    await detail.selectOrder(9);
    assert.equal(receipt.receipt_copy, true);
    assert.equal(detail.getState().detail.id, 9);

    for (const invalid of [
        { id: 10, shop_id: 8, status: 'PAID', expected: 'other_shop' },
        { id: 11, shop_id: 7, status: 'PENDING', expected: 'not_finalized' }
    ]) {
        receipt = null;
        const rejected = createController({
            getShopId: () => 7,
            request: async () => invalid,
            onReceipt: value => { receipt = value; }
        });
        await rejected.selectOrder(invalid.id);
        assert.equal(rejected.getState().detailError, invalid.expected);
        assert.equal(receipt, null);
    }

    const listPending = deferred();
    const detailPending = deferred();
    const parallel = createController({
        getShopId: () => 7,
        request: path => path.endsWith('/detail') ? detailPending.promise : listPending.promise,
        onReceipt() {}
    });
    const listRun = parallel.open();
    const detailRun = parallel.selectOrder(12);
    detailPending.resolve({ id: 12, shop_id: 7, status: 'PAID', items: [] });
    await detailRun;
    parallel.closeDetail();
    listPending.resolve(page([row(12)], 1));
    await listRun;
    assert.equal(parallel.getState().loading, false, 'detail lifecycle must not strand list loading');
    assert.deepEqual(parallel.getState().orders.map(item => item.id), [12]);

    const unavailable = createController({
        getShopId: () => null,
        request: async () => { throw new Error('must not request'); },
        onReceipt() {}
    });
    await unavailable.open();
    assert.equal(unavailable.getState().error, 'select_shop');

    console.log('pos-sales-history-r1 harness: passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
