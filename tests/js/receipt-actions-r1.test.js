'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('static/js/pos.js', 'utf8');
const start = source.indexOf('// RECEIPT_ACTIONS_R1_START');
const end = source.indexOf('// RECEIPT_ACTIONS_R1_END');
assert(start >= 0 && end > start, 'missing Receipt R1 action block');

{
    const localeContext = { window: {} };
    vm.runInNewContext(
        fs.readFileSync('static/js/locales/pos.js', 'utf8'),
        localeContext
    );
    const resources = localeContext.window.FSELLING_I18N_RESOURCES;
    assert.equal(resources.vi.translation['pos.receipt.print'], 'In hóa đơn');
    assert.equal(resources.vi.translation['pos.receipt.share'], 'Chia sẻ');
    assert.equal(resources.vi.translation['pos.receipt.copy'], 'Sao chép');
    assert.equal(resources.en.translation['pos.receipt.print'], 'Print receipt');
    assert.equal(resources.en.translation['pos.receipt.share'], 'Share');
    assert.equal(resources.en.translation['pos.receipt.copy'], 'Copy');
}

function createContext(overrides = {}) {
    const toMoney = value => `${Math.round(Number(value) || 0).toLocaleString('vi-VN')} ₫`;
    const context = {
        console,
        navigator: {},
        window: { print() {} },
        document: {},
        dich: key => key,
        showToast() {},
        dinhDangSoHoaDon: value => Math.round(Number(value) || 0).toLocaleString('vi-VN'),
        dinhDangTienHoaDon: toMoney,
        dinhDangNgayGioHoaDon: () => '29/08/2026, 10:30:00',
        localStorage: { getItem: () => 'thu-ngan-a' },
        ...overrides
    };
    vm.createContext(context);
    vm.runInContext(`${source.slice(start, end)};
        this.buildReceipt = taoNoiDungHoaDonChiaSe;
        this.setReceipt = value => { duLieuHoaDonHienTai = value; };
        this.shareReceipt = chiaSeHoaDon;
        this.copyReceipt = saoChepHoaDon;
        this.printReceipt = inHoaDon;
    `, context);
    return context;
}

function order(overrides = {}) {
    return {
        id: 42,
        shop_name: 'Tạp hóa An Nhiên',
        created_at: '2026-08-29T03:30:00Z',
        cashier_username: 'thu-ngan-a',
        bank_paid_amount: 0,
        cash_paid_amount: 24000,
        cash_tendered_amount: 30000,
        cash_change_amount: 6000,
        subtotal: 24000,
        discount_amount: 0,
        total_amount: 24000,
        refund_pending: false,
        items: [{
            product_name: 'Nước mắm',
            price: 12000,
            quantity: 2,
            line_total: 24000
        }],
        customer: { name: 'Cô Lan', phone: '0774867057' },
        ...overrides
    };
}

{
    const context = createContext();
    const text = context.buildReceipt(order());
    assert.match(text, /Tạp hóa An Nhiên/);
    assert.match(text, /Nước mắm/);
    assert.match(text, /TỔNG CỘNG: 24\.000 ₫/);
    assert.match(text, /Khách hàng: Cô Lan/);
    assert.doesNotMatch(text, /0774867057/);
    assert.match(
        context.buildReceipt(order({
            payment_method: 'debt',
            cash_paid_amount: 0,
            cash_tendered_amount: null
        })),
        /Thanh toán: Ghi nợ/
    );
}

{
    const receipt = { innerHTML: '' };
    const warning = { style: {}, innerText: '' };
    const renderContext = {
        document: {
            getElementById: id => id === 'hoaDonNoiDung' ? receipt : warning
        },
        navigator: {},
        window: {},
        dich: key => key,
        showToast() {},
        localStorage: { getItem: () => 'thu-ngan-a' },
        escapeHtml: value => String(value ?? ''),
        dinhDangSoHoaDon: value => Math.round(Number(value) || 0).toLocaleString('vi-VN'),
        dinhDangTienHoaDon: value => `${Math.round(Number(value) || 0).toLocaleString('vi-VN')} ₫`,
        dinhDangNgayGioHoaDon: () => '29/08/2026, 10:30:00'
    };
    const renderStart = source.indexOf('function veHoaDon(');
    const renderEnd = source.indexOf('function dongHoaDon(', renderStart);
    assert(renderStart >= 0 && renderEnd > renderStart, 'missing receipt renderer');
    vm.createContext(renderContext);
    vm.runInContext(`${source.slice(start, end)}\n${source.slice(renderStart, renderEnd)}; this.renderReceipt = veHoaDon;`, renderContext);
    renderContext.renderReceipt(order());
    assert.match(receipt.innerHTML, /Khách hàng:<\/b> Cô Lan/);
    assert.doesNotMatch(receipt.innerHTML, /0774867057/);
}

(async () => {
    let payload = null;
    const context = createContext({
        navigator: {
            share: async value => { payload = value; }
        }
    });
    context.setReceipt(order());
    await context.shareReceipt();
    assert.equal(payload.title, 'Hóa đơn #42 · Tạp hóa An Nhiên');
    assert.match(payload.text, /Nước mắm/);
    assert.doesNotMatch(payload.text, /0774867057/);

    let copied = null;
    let toast = null;
    const copyContext = createContext({
        navigator: {
            clipboard: {
                writeText: async text => { copied = text; }
            }
        },
        showToast: message => { toast = message; }
    });
    copyContext.setReceipt(order());
    await copyContext.copyReceipt();
    assert.match(copied, /HÓA ĐƠN BÁN HÀNG/);
    assert.doesNotMatch(copied, /0774867057/);
    assert.equal(toast, 'pos.receipt.copied');

    let legacyField = null;
    let legacySelected = false;
    let legacyRemoved = false;
    let legacyToast = null;
    const legacyContext = createContext({
        document: {
            body: { appendChild: field => { legacyField = field; } },
            createElement: () => ({
                value: '',
                style: {},
                setAttribute() {},
                focus() {},
                select() { legacySelected = true; },
                remove() { legacyRemoved = true; }
            }),
            execCommand: command => command === 'copy'
        },
        showToast: message => { legacyToast = message; }
    });
    legacyContext.setReceipt(order());
    await legacyContext.copyReceipt();
    assert.match(legacyField.value, /Nước mắm/);
    assert.equal(legacySelected, true);
    assert.equal(legacyRemoved, true);
    assert.equal(legacyToast, 'pos.receipt.copied');

    let rejectedFallbackUsed = false;
    const rejectedClipboardContext = createContext({
        navigator: {
            clipboard: {
                writeText: async () => { throw new Error('permission denied'); }
            }
        },
        document: {
            body: { appendChild() {} },
            createElement: () => ({
                value: '',
                style: {},
                setAttribute() {},
                focus() {},
                select() {},
                remove() {}
            }),
            execCommand: command => {
                rejectedFallbackUsed = command === 'copy';
                return rejectedFallbackUsed;
            }
        }
    });
    rejectedClipboardContext.setReceipt(order());
    await rejectedClipboardContext.copyReceipt();
    assert.equal(rejectedFallbackUsed, true);

    let fallbackShareText = null;
    let fallbackShareToast = null;
    const fallbackShareContext = createContext({
        navigator: {
            clipboard: {
                writeText: async text => { fallbackShareText = text; }
            }
        },
        showToast: message => { fallbackShareToast = message; }
    });
    fallbackShareContext.setReceipt(order());
    await fallbackShareContext.shareReceipt();
    assert.match(fallbackShareText, /HÓA ĐƠN BÁN HÀNG/);
    assert.equal(fallbackShareToast, 'pos.receipt.copied_for_share');

    let printCount = 0;
    const printContext = createContext({
        window: { print: () => { printCount += 1; } }
    });
    printContext.setReceipt(order());
    printContext.printReceipt();
    assert.equal(printCount, 1);

    let openedPayload = null;
    const openedContext = createContext({
        navigator: { share: async value => { openedPayload = value; } },
        document: {
            getElementById: () => ({ style: {} })
        }
    });
    openedContext.apiCall = async () => order();
    openedContext.resetPOS = () => {};
    openedContext.veHoaDon = () => {};
    openedContext.showFirstRunSaleSuccess = () => {};
    const openStart = source.indexOf('async function hienHoaDon(');
    const openEnd = source.indexOf('function showFirstRunSaleSuccess(', openStart);
    assert(openStart >= 0 && openEnd > openStart, 'missing receipt opening flow');
    vm.runInContext(`${source.slice(openStart, openEnd)}; this.openReceipt = hienHoaDon;`, openedContext);
    await openedContext.openReceipt(42);
    await openedContext.shareReceipt();
    assert.equal(openedPayload.title, 'Hóa đơn #42 · Tạp hóa An Nhiên');

    openedPayload = null;
    openedContext.dismissFirstRunSaleSuccess = () => {};
    const closeStart = source.indexOf('function dongHoaDon(');
    const closeEnd = source.indexOf('function resetPOS(', closeStart);
    assert(closeStart >= 0 && closeEnd > closeStart, 'missing receipt close flow');
    vm.runInContext(`${source.slice(closeStart, closeEnd)}; this.closeReceipt = dongHoaDon;`, openedContext);
    openedContext.closeReceipt();
    await openedContext.shareReceipt();
    assert.equal(openedPayload, null);

    console.log('receipt-actions-r1 harness: 11 passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
