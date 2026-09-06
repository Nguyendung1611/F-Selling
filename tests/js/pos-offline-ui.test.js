'use strict';

// Chạy view-model UI bằng Node, không cần trình duyệt hay dữ liệu thật. DOM thật
// được kiểm ở browser gate; harness này khóa mapping state -> thông điệp/nút.
const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('static/js/pos.js', 'utf8');
const start = source.indexOf('function soTrangThaiDongBo(');
const end = source.indexOf('function themDongTrangThaiOffline(', start);
assert(start >= 0 && end > start, 'missing offline UI view-model');
const context = { console };
vm.createContext(context);
vm.runInContext(`${source.slice(start, end)}; this.model = moHinhTrangThaiOffline;`, context);

function summary(overrides = {}) {
    return {
        paused: false,
        pause_kind: null,
        retry_at: null,
        error: null,
        catalog_saved_at: '2026-08-13 08:00:00.000000',
        lease_expires_at: '2026-08-13 20:00:00.000000',
        state_counts: {
            DRAFT: 0, READY: 0, SYNCING: 0, ACKED: 0, RETRYABLE: 0,
            BLOCKED_RECOVERABLE: 0, QUARANTINED: 0
        },
        ...overrides
    };
}

const waiting = context.model(2, 0, summary({ state_counts: { ...summary().state_counts, READY: 3 } }), false);
assert.equal(waiting.pending, 5);
assert.equal(waiting.messageKey, 'pos.offline.panel_waiting');

const retry = context.model(0, 0, summary({
    paused: true, pause_kind: 'TRANSIENT', retry_at: '2026-08-13 09:00:00.000000',
    error: { code: 'SYNC_SERVER_ERROR', http_status: 500 },
    state_counts: { ...summary().state_counts, RETRYABLE: 1 }
}), false);
assert.equal(retry.transient, true);
assert.equal(retry.messageKey, 'pos.offline.panel_retry');
assert.equal(retry.errorCode, 'SYNC_SERVER_ERROR');

const login = context.model(0, 0, summary({
    paused: true, pause_kind: 'HARD', error: { code: 'SYNC_LOGIN_REQUIRED', http_status: 401 }
}), false);
assert.equal(login.hard, true);
assert.equal(login.messageKey, 'pos.offline.panel_login');

const owner = context.model(0, 0, summary({
    paused: true, pause_kind: 'HARD', error: { code: 'SYNC_HTTP_403', http_status: 403 }
}), false);
assert.equal(owner.messageKey, 'pos.offline.panel_owner');

const attention = context.model(0, 1, summary({
    state_counts: { ...summary().state_counts, BLOCKED_RECOVERABLE: 1, QUARANTINED: 1 }
}), false);
assert.equal(attention.messageKey, 'pos.offline.panel_attention');
assert.equal(attention.blocked + attention.quarantined + attention.v0Loi, 3);

const offline = context.model(0, 0, summary(), true);
assert.equal(offline.messageKey, 'pos.offline.panel_offline');

console.log('pos-offline-ui harness: 1 passed');
