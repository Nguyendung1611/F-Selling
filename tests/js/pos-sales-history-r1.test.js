'use strict';

const assert = require('assert/strict');
const {
    createController,
    renderOrderCard,
    renderDetail,
    mount
} = require('../../static/js/pos-sales-history-r1.js');

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

function fakeDocument() {
    const ids = [
        'salesHistoryForm', 'salesHistorySearch', 'salesHistorySubmit',
        'salesHistoryToday', 'salesHistory7d', 'salesHistoryAllHint',
        'salesHistoryStatus', 'salesHistoryList', 'salesHistoryLoadMore',
        'salesHistoryDetail', 'salesHistoryClose', 'salesHistoryModal'
    ];
    const elements = Object.fromEntries(ids.map(id => [id, {
        id,
        value: '',
        hidden: false,
        disabled: false,
        innerHTML: '',
        textContent: '',
        dataset: {},
        attributes: {},
        listeners: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, fn) { this.listeners[name] = fn; },
        emit(name, event = {}) { return this.listeners[name]?.(event); },
        querySelectorAll() { return []; }
    }]));
    return {
        elements,
        activeElement: null,
        listeners: {},
        getElementById: id => elements[id],
        addEventListener(name, fn) { this.listeners[name] = fn; }
    };
}

const tick = async () => {
    await Promise.resolve();
    await Promise.resolve();
};

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

    const ui = {
        escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
        t: key => key,
        money: value => `${value} ₫`,
        dateTime: value => value
    };
    const escapedCard = renderOrderCard({
        id: 1,
        created_at: '2026-08-30T03:00:00Z',
        status: 'PAID',
        payment_method: 'cash',
        total_amount: 12000,
        customer_name: '<img src=x onerror=alert(1)>',
        customer_phone_masked: '090 *** 0001'
    }, ui);
    assert.doesNotMatch(escapedCard, /<img/);
    assert.match(escapedCard, /&lt;img/);
    const escapedDetail = renderDetail({
        id: 1,
        created_at: '2026-08-30T03:00:00Z',
        total_amount: 12000,
        items: [{ product_name: '<script>alert(1)</script>', quantity: 1, line_total: 12000 }]
    }, ui);
    assert.doesNotMatch(escapedDetail, /<script>/);
    assert.match(escapedDetail, /&lt;script&gt;/);

    const firstDom = fakeDocument();
    const firstRequests = [];
    const firstMount = mount({
        document: firstDom,
        request: path => {
            const pending = deferred();
            firstRequests.push({ path, ...pending });
            return pending.promise;
        },
        getShopId: () => 7,
        prepareReceipt() {},
        closeModal() {},
        goToLogin() {},
        printReceipt() {},
        shareReceipt() {},
        ...ui
    });
    const opening = firstMount.open();
    assert.match(firstDom.elements.salesHistoryList.innerHTML, /sales-history-skeleton/);
    firstRequests[0].resolve(page([], 1));
    await opening;
    assert.match(firstDom.elements.salesHistoryStatus.innerHTML, /pos\.sales_history\.empty_today/);
    assert.match(firstDom.elements.salesHistoryStatus.innerHTML, /seven-days/);

    firstDom.elements.salesHistorySearch.value = 'Cô Lan';
    firstDom.elements.salesHistoryForm.emit('submit', { preventDefault() {} });
    assert.equal(new URL(`http://local${firstRequests[1].path}`).searchParams.get('q'), 'Cô Lan');
    firstRequests[1].resolve(page([], 1, false, true));
    await tick();
    assert.match(firstDom.elements.salesHistoryStatus.innerHTML, /pos\.sales_history\.no_results/);
    assert.equal(firstDom.elements.salesHistoryToday.disabled, true);
    firstDom.elements.salesHistoryStatus.emit('click', {
        target: { dataset: { historyAction: 'clear' } }
    });
    assert.equal(firstDom.elements.salesHistorySearch.value, '');
    assert.equal(new URL(`http://local${firstRequests[2].path}`).searchParams.has('q'), false);
    firstRequests[2].resolve(page([], 1));
    await tick();
    assert.equal(firstDom.elements.salesHistoryToday.disabled, false);
    firstDom.elements.salesHistoryStatus.emit('click', {
        target: { dataset: { historyAction: 'seven-days' } }
    });
    firstRequests[3].resolve(page([], 1));
    await tick();
    assert.equal(firstMount.getState().scope, '7d');
    assert.equal(firstDom.elements.salesHistory7d.attributes['aria-pressed'], 'true');

    let listCall = 0;
    const listDom = fakeDocument();
    const listMount = mount({
        document: listDom,
        request: async () => {
            listCall += 1;
            if (listCall === 1) return page([row(3)], 1, true);
            if (listCall === 2) throw { status: 500 };
            return page([], 1);
        },
        getShopId: () => 7,
        prepareReceipt() {},
        closeModal() {},
        goToLogin() {},
        printReceipt() {},
        shareReceipt() {},
        ...ui
    });
    await listMount.open();
    listDom.elements.salesHistoryLoadMore.emit('click');
    await tick();
    assert.deepEqual(listMount.getState().orders.map(item => item.id), [3]);
    assert.equal(listMount.getState().error, 'network');
    listDom.elements.salesHistory7d.emit('click');
    await tick();
    assert.equal(listDom.elements.salesHistory7d.attributes['aria-pressed'], 'true');

    const detailDom = fakeDocument();
    let printed = 0;
    let shared = 0;
    const sharePending = deferred();
    const detailMount = mount({
        document: detailDom,
        request: async path => path.endsWith('/detail')
            ? { id: 9, shop_id: 7, status: 'PAID', created_at: '', total_amount: 12000, items: [] }
            : page([row(9)], 1),
        getShopId: () => 7,
        prepareReceipt() {},
        closeModal() {},
        goToLogin() {},
        printReceipt: () => { printed += 1; },
        shareReceipt: async () => { shared += 1; await sharePending.promise; },
        ...ui
    });
    await detailMount.open();
    detailDom.elements.salesHistoryList.emit('click', {
        target: { closest: () => ({ dataset: { orderId: '9' } }) }
    });
    await tick();
    assert.match(detailDom.elements.salesHistoryDetail.innerHTML, /data-history-action="print"/);
    const printButton = { dataset: { historyAction: 'print' }, disabled: false };
    await detailDom.elements.salesHistoryDetail.emit('click', { target: printButton });
    assert.equal(printed, 1);
    const shareButton = { dataset: { historyAction: 'share' }, disabled: false };
    const sharing = detailDom.elements.salesHistoryDetail.emit('click', { target: shareButton });
    assert.equal(shareButton.disabled, true);
    sharePending.resolve();
    await sharing;
    assert.equal(shared, 1);
    assert.equal(shareButton.disabled, false);

    console.log('pos-sales-history-r1 harness: passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
