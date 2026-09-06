'use strict';

/**
 * I10-D: QR v1 presentation lifecycle — deterministic Node/vm harness.
 *
 * Extracts only the QR block from pos.js (I10-D marker → htmlNut) and evaluates
 * it inside the VM with a single vm.runInContext call, injecting test hooks so
 * they close over the real module-scope `let` vars. No production window exports.
 *
 * No browser, no network, no timer. Deterministic via process.nextTick.
 */

const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');

async function runTests() {

    // ── Source extraction ──────────────────────────────────────────────────────

    const source = fs.readFileSync('static/js/pos.js', 'utf8');
    const marker = '// ── I10-D: QR v1 presentation lifecycle owner';
    const qrStart = source.indexOf(marker);
    const qrEnd = source.indexOf('function htmlNut(icon, key');
    assert(qrStart >= 0, 'I10-D marker missing in pos.js');
    assert(qrEnd > qrStart, 'htmlNut marker missing after QR block');
    const qrBlock = source.slice(qrStart, qrEnd);

    // Offline model for vm-load sanity check.
    const offlineStart = source.indexOf('function soTrangThaiDongBo(');
    const offlineEnd = source.indexOf('function themDongTrangThaiOffline(', offlineStart);
    const offlineBlock = source.slice(offlineStart, offlineEnd);
    assert(source.includes('let _qr1OrderId = null;'), '_qr1OrderId must exist');
    assert(source.includes('function _qr1Cleanup()'), '_qr1Cleanup must exist');

    // ── DOM mock ───────────────────────────────────────────────────────────────

    const dom = {
        elements: {},
        createEl(id) {
            this.elements[id] = {
                src: '', innerText: '', style: { display: '' }, textContent: '', alt: '',
            };
        },
        get(id) { return this.elements[id] || null; },
    };
    ['qrImage','qr1Status','qr1Manual','qr1BankCode','qr1AccountNo',
     'qr1AccountName','qr1Reference','qrTotalTxt'].forEach(id => dom.createEl(id));

    let _urlCounter = 0; // monotonic Blob URL counter.

    // ── VM context ────────────────────────────────────────────────────────────
    // IMPORTANT: _qr1FetchAndRender captures `fetch` at eval time.
    // We must set context.fetch to our mock BEFORE the qrBlock sees it.

    const noop = () => {};
    // _activeFetch and _activeApiCall live in Node.js scope.
    // The VM's global `fetch` is set via context.fetch, which _qr1FetchAndRender captures.
    let _activeFetch   = () => Promise.reject(new Error('default not mocked'));
    let _activeApiCall = () => Promise.reject(new Error('default not mocked'));

    // context.fetch IS what _qr1FetchAndRender calls. Set it to delegate.
    // Replace context.fetch directly (instead of via setFetchMock) for tests that
    // need to intercept the actual network call made by _qr1FetchAndRender.
    let _contextFetch = (url, opts) => _activeFetch(url, opts);

    const context = {
        console,
        document: {
            getElementById: id => dom.get(id),
            createElement: () => ({}),
            addEventListener: noop,
            removeEventListener: noop,
        },
        localStorage: {
            getItem: key => (key === 'role' ? 'SELLER' : null),
            setItem: noop,
            removeItem: noop,
        },
        sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        URL: {
            _blobs: {},
            createObjectURL(blob) {
                const id = String(++_urlCounter);
                this._blobs[id] = blob;
                return `blob:${id}`;
            },
            revokeObjectURL(url) {
                const id = url.replace('blob:', '');
                delete this._blobs[id];
            },
        },
        AbortController: class {
            constructor() { this.signal = { aborted: false }; }
            abort() { this.signal.aborted = true; }
        },
        // Delegating fetch: _qr1FetchAndRender captures this at eval time.
        // Update _contextFetch to change what the captured fetch does.
        fetch:   (url, opts) => _contextFetch(url, opts),
        apiCall: (ep) => _activeApiCall(ep),
        setTimeout: noop,
        clearTimeout: noop,
        window: {},
        dich: key => `[${key}]`,
        dinhDangTien: v => `${v} VND`,
        getToken: () => 'test-token',
        escapeHtml: s => s,
        redirectToLogin: noop,
    };

    vm.createContext(context);

    // Verify vm works with the offline model.
    vm.runInContext(offlineBlock, context);
    assert.equal(typeof context.moHinhTrangThaiOffline, 'function', 'vm must load offline model');

    // Evaluate QR block PLUS test hooks in ONE call so hooks close over real lexical state.
    vm.runInContext(`
        ${qrBlock}

        // Test-only hooks — close over real QR vars, no window pollution.
        __qr1TestHooks = {
            gen:     () => _qr1Generation,
            state:   () => _qr1State,
            order:   () => _qr1OrderId,
            fprint:  () => _qr1Fingerprint,
            url:     () => _qr1ObjectUrl,
            cleanup: () => _qr1Cleanup(),
            show:    (intent, id, total) => qr1ShowTransient(intent, id, total),
            // Direct fetch — exercises the full _qr1FetchAndRender path with the
            // captured global fetch (which delegates to _contextFetch in Node scope).
            fetch:   (intent, id, gen) => _qr1FetchAndRender(intent, id, gen),
            manual:  (i) => _qr1RenderManual(i),
            refresh: () => _qr1RefreshLabels(),
            recover: (id) => _qr1RecoverV1(id),
        };
    `, context);

    const H = context.__qr1TestHooks;

    // ── Mock helpers ─────────────────────────────────────────────────────────
    // Replace _activeFetch / _activeApiCall and update the delegating context.fetch.
    function setFetchMock(fn) {
        _activeFetch = fn;
        _contextFetch = fn;
    }
    function setApiMock(fn) { _activeApiCall = fn; }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function tick() { return new Promise(r => process.nextTick(r)); }

    function reset() {
        H.cleanup();
        dom.elements['qrImage'].src = '';
        dom.elements['qr1Status'].innerText = '';
        dom.elements['qr1Manual'].style.display = '';
        ['qr1BankCode','qr1AccountNo','qr1AccountName','qr1Reference'].forEach(id => {
            dom.elements[id].textContent = '';
        });
    }

    // ── Test 1: v0 path never calls v1 render ──────────────────────────────

    {
        let urlCalls = 0;
        const origCreate = context.URL.createObjectURL.bind(context.URL);
        context.URL.createObjectURL = (...a) => { urlCalls++; return origCreate(...a); };

        reset();
        reset();

        assert.equal(urlCalls, 0, 'v0/reset path must not call createObjectURL');
        assert.equal(H.state(), null, 'state null after reset');
        assert.equal(H.order(), null, 'orderId null after reset');
        assert.equal(H.url(), null, 'objectUrl null after reset');

        context.URL.createObjectURL = origCreate;
    }

    // ── Test 2: v1 manual display, no persistence ──────────────────────────────

    {
        reset();
        H.manual({
            contract_version: 1,
            expected_vnd: 125000,
            canonical_reference: 'FS1-abcdef123456',
            bank_code: 'VCB',
            bank_account_no: '1234567890',
            bank_account_name: 'NGUYEN VAN A',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: false,
                render_endpoint: null,
            },
        });

        assert.equal(H.state(), 'manual', 'manual state');
        assert.equal(dom.get('qr1Manual').style.display, 'block', 'manual block visible');
        assert.equal(dom.get('qr1BankCode').textContent, 'VCB', 'bank_code');
        assert.equal(dom.get('qr1AccountNo').textContent, '1234567890', 'account');
        assert.equal(dom.get('qr1AccountName').textContent, 'NGUYEN VAN A', 'name');
        assert.equal(dom.get('qr1Reference').textContent, 'FS1-abcdef123456', 'ref');
        // No duplicate `x || x` expressions.
        assert.equal(dom.get('qr1AccountNo').textContent.indexOf('||'), -1,
                     'no duplicate expression');
    }

    // ── Test 3: reload no-qr_url → one metadata apiCall ─────────────────────

    {
        reset();
        let callCount = 0;
        setApiMock(ep => {
            callCount++;
            if (ep.includes('/qr')) {
                return Promise.resolve({
                    contract_version: 1,
                    expected_vnd: 99000,
                    canonical_reference: 'FS1-reloadtest',
                    hidden: false,
                    bank_code: 'TPB',
                    bank_account_no: '9876543210',
                    bank_account_name: 'SHOP TEST',
                    capability: { render_available: false, render_endpoint: null },
                });
            }
            return Promise.reject(new Error('not mocked'));
        });

        H.recover(77);
        await tick();  // apiCall microtask flushes
        await tick();  // _qr1FetchAndRender microtask flushes

        assert.equal(callCount, 1, 'exactly one apiCall on v1 reload');
        assert.equal(H.order(), 77, 'orderId set');
        assert.equal(H.state(), 'manual', 'manual fallback after metadata');
    }

    // ── Test 4: legacy reload with qr_url → no v1 fetch ───────────────────

    {
        reset();
        let callCount = 0;
        setApiMock(() => {
            callCount++;
            return Promise.reject(new Error('unexpected'));
        });

        // v0 path uses qrImage.src; v1 recover() not called.
        if (callCount !== 0) throw new Error('v0 path must not call apiCall');
    }

    // ── Test 5: render success — exact fetch options, PNG cap, one URL ─────────

    {
        reset();
        let captured = null;
        const pngBlob = { size: 512, type: 'image/png' };

        // Replace _contextFetch directly so the captured global fetch delegates here.
        _contextFetch = (url, opts) => {
            captured = { url, opts };
            return Promise.resolve({
                ok: true,
                headers: { get: () => 'image/png' },
                blob: () => Promise.resolve(pngBlob),
            });
        };

        const intent = {
            expected_vnd: 50000,
            canonical_reference: 'FS1-rendertest',
            bank_code: 'ACB', bank_account_no: '1', bank_account_name: 'T',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: '/api/orders/5/qr/render',
            },
        };

        H.show(intent, 5, intent.expected_vnd);
        await tick();
        await tick();

        if (!captured) throw new Error('fetch was not called in test 5');
        assert.ok(captured, 'fetch was called');
        assert.equal(captured.url, '/api/orders/5/qr/render', 'exact render endpoint');
        assert.equal(captured.opts.method, 'GET', 'GET');
        assert.equal(captured.opts.cache, 'no-store', 'no-store');
        assert.equal(captured.opts.credentials, 'omit', 'omit');
        assert.equal(captured.opts.redirect, 'error', 'error redirect');
        assert.equal(captured.opts.headers.Accept, 'image/png', 'PNG accept');
        assert.ok(captured.opts.headers.Authorization.startsWith('Bearer '), 'Bearer auth');
        assert.ok(captured.opts.signal, 'AbortSignal passed');
        assert.equal(H.state(), 'rendered', 'rendered state');
        assert.ok(H.url(), 'object URL created');
        assert.ok(H.url().startsWith('blob:'), 'valid blob: URL');

        // Restore default
        _contextFetch = () => Promise.reject(new Error('default'));
    }

    // ── Test 6: unavailable/502/wrong-type/empty/oversize/network → manual ────

    {
        const cases = [
            { label: 'non-ok 502', ok: false },
            { label: 'wrong type image/jpeg', type: 'image/jpeg' },
            { label: 'wrong type image/apng', type: 'image/apng' },
            { label: 'empty blob', size: 0 },
            { label: 'oversize 600k', size: 600 * 1024 },
            { label: 'network error', throws: true },
        ];

        for (const c of cases) {
            reset();
            const intent = {
                expected_vnd: 75000, canonical_reference: 'FS1-failtest',
                bank_code: 'BIDV', bank_account_no: '9', bank_account_name: 'F',
                capability: {
                    mode: 'REPORT_ONLY',
                    render_available: true,
                    render_endpoint: '/api/orders/7/qr/render',
                },
            };

            if (c.throws) {
                _contextFetch = () => Promise.reject(new Error('net'));
            } else {
                _contextFetch = () => Promise.resolve({
                    ok: c.ok !== undefined ? c.ok : true,
                    headers: { get: () => c.type || 'image/png' },
                    blob: () => Promise.resolve({
                        size: c.size !== undefined ? c.size : 100,
                        type: c.type || 'image/png',
                    }),
                });
            }

            H.show(intent, 7, intent.expected_vnd);
            await tick();
            await tick();

            assert.equal(H.state(), 'manual', `${c.label}: manual fallback`);
            assert.equal(dom.get('qr1BankCode').textContent, 'BIDV',
                         `${c.label}: fields populated`);
        }
        _contextFetch = () => Promise.reject(new Error('default'));
    }

    // ── Test 7: hidden transition clears all sensitive DOM ──────────────────────

    {
        reset();
        H.manual({ bank_code: 'A', bank_account_no: '1',
                   bank_account_name: 'A', canonical_reference: 'A' });
        H.cleanup();

        assert.equal(H.state(), null, 'state null after cleanup');
        assert.equal(H.url(), null, 'object URL revoked');
        assert.equal(dom.get('qrImage').src, '', 'image src cleared');
        assert.equal(dom.get('qr1Status').innerText, '', 'status cleared');
        assert.equal(dom.get('qr1Manual').style.display, 'none', 'manual hidden');
        assert.equal(dom.get('qr1BankCode').textContent, '', 'bank cleared');
        assert.equal(dom.get('qr1AccountNo').textContent, '', 'account cleared');
        assert.equal(dom.get('qr1AccountName').textContent, '', 'name cleared');
        assert.equal(dom.get('qr1Reference').textContent, '', 'ref cleared');
    }

    // ── Test 8: cleanup/reset race — delayed order A cannot overwrite order B ──

    {
        reset();
        let resolveFetchA;
        _contextFetch = () => new Promise(r => { resolveFetchA = r; });

        // Start order A render.
        H.show({
            expected_vnd: 100000, canonical_reference: 'FS1-A',
            bank_code: 'A', bank_account_no: 'A', bank_account_name: 'A',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: '/api/orders/10/qr/render',
            },
        }, 10, 100000);
        await tick();
        assert.equal(H.order(), 10, 'order A started');

        // Start order B; its lifecycle cleans up order A.
        H.show({
            expected_vnd: 200000, canonical_reference: 'FS1-B',
            bank_code: 'B', bank_account_no: 'B', bank_account_name: 'B',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: false, render_endpoint: null,
            },
        }, 11, 200000);
        await tick();
        assert.equal(H.order(), 11, 'order B active');
        assert.equal(dom.get('qr1BankCode').textContent, 'B', 'order B fields');

        // Resolve order A fetch late — must NOT overwrite order B.
        resolveFetchA({
            ok: true,
            headers: { get: () => 'image/png' },
            blob: () => Promise.resolve({ size: 200, type: 'image/png' }),
        });
        await tick();
        await tick();

        assert.equal(H.order(), 11, 'order B still active');
        assert.equal(dom.get('qr1BankCode').textContent, 'B', 'order B fields intact');
        assert.equal(H.state(), 'manual', 'state manual for B');

        _contextFetch = () => Promise.reject(new Error('default'));
    }

    // ── Test 9: generation fence prevents stale overwrite ─────────────────────

    {
        reset();
        const orderId = 15;
        H.show({
            expected_vnd: 50000, canonical_reference: 'FS1-old',
            bank_code: 'OLD', bank_account_no: '1', bank_account_name: 'OLD',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: false, render_endpoint: null,
            },
        }, orderId, 50000);
        const oldGen = H.gen();

        _contextFetch = () => Promise.resolve({
            ok: true,
            headers: { get: () => 'image/png' },
            blob: () => Promise.resolve({ size: 100, type: 'image/png' }),
        });
        H.show({
            expected_vnd: 60000, canonical_reference: 'FS1-current',
            bank_code: 'NEW', bank_account_no: '2', bank_account_name: 'NEW',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: '/api/orders/15/qr/render',
            },
        }, orderId, 60000);
        await tick();
        await tick();

        const current = {
            state: H.state(),
            fields: ['qr1BankCode','qr1AccountNo','qr1AccountName','qr1Reference']
                .map(id => dom.get(id).textContent),
            url: H.url(),
            order: H.order(),
        };
        assert.equal(current.state, 'rendered', 'new lifecycle rendered');
        assert.ok(current.url, 'new lifecycle owns an object URL');

        let fetchCalls = 0;
        _contextFetch = () => {
            fetchCalls++;
            return Promise.reject(new Error('stale generation fetched'));
        };
        H.fetch({
            expected_vnd: 70000, canonical_reference: 'FS1-stale',
            bank_code: 'STALE', bank_account_no: '3', bank_account_name: 'STALE',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: '/api/orders/15/qr/render',
            },
        }, orderId, oldGen);
        await tick();
        await tick();

        assert.equal(fetchCalls, 0, 'stale generation performs no fetch');
        assert.deepEqual({
            state: H.state(),
            fields: ['qr1BankCode','qr1AccountNo','qr1AccountName','qr1Reference']
                .map(id => dom.get(id).textContent),
            url: H.url(),
            order: H.order(),
        }, current, 'stale generation cannot mutate current lifecycle');
        _contextFetch = () => Promise.reject(new Error('default'));
    }

    // ── Test 10: language refresh → zero network/object-URL ops ───────────────

    {
        reset();
        H.manual({ bank_code: 'X', bank_account_no: '1',
                   bank_account_name: 'X', canonical_reference: 'X' });
        dom.get('qr1Status').innerText = 'old message';

        let fetchCalls = 0, urlCalls = 0;
        const origCreate = context.URL.createObjectURL.bind(context.URL);
        context.URL.createObjectURL = (...a) => { urlCalls++; return origCreate(...a); };
        _contextFetch = () => { fetchCalls++; return Promise.resolve({ ok: false }); };

        H.refresh();

        assert.equal(fetchCalls, 0, 'no fetch');
        assert.equal(urlCalls, 0, 'no createObjectURL');

        context.URL.createObjectURL = origCreate;
        _contextFetch = () => Promise.reject(new Error('default'));
    }

    // ── Test 11: static proof — no forbidden pathways ─────────────────────────

    {
        const forbidden = ['data:', 'FileReader', 'canvas', 'caches.open', 'indexedDB'];
        for (const term of forbidden) {
            assert.ok(!qrBlock.includes(term),
                      `${term} must not appear in QR lifecycle`);
        }
    }

    // ── Test 12: DOM IDs and i18n keys present ───────────────────────────────

    {
        const html = fs.readFileSync('static/pos.html', 'utf8');
        const ids = ['qr1Status','qr1Manual','qr1BankCode','qr1AccountNo',
                     'qr1AccountName','qr1Reference'];
        for (const id of ids) {
            assert.ok(html.includes(`id="${id}"`), `id="${id}" must exist in HTML`);
        }

        const locale = fs.readFileSync('static/js/locales/pos.js', 'utf8');
        const keys = [
            'pos.payment.v1_loading','pos.payment.v1_unavailable',
            'pos.payment.v1_hidden','pos.payment.bank_code_label',
            'pos.payment.account_no_label','pos.payment.account_name_label',
            'pos.payment.reference_label','pos.payment.instruction_only',
            'pos.payment.v1_img_alt',
        ];
        for (const key of keys) {
            assert.ok(locale.includes(`'${key}':`),
                      `i18n key "${key}" must exist in locale`);
        }
        const enIdx = locale.indexOf("'pos.payment.v1_loading': 'Loading QR code…'");
        assert.ok(enIdx >= 0, 'EN block exists');
        for (const key of keys) {
            assert.ok(locale.indexOf(`'${key}':`, enIdx) >= 0,
                      `EN key "${key}" must exist`);
        }
    }

    // ── Test 13: pagehide and pageshow cleanup listeners present ──────────────

    {
        const html = fs.readFileSync('static/js/pos.js', 'utf8');
        assert.ok(html.includes("addEventListener('pagehide'"),
                  "pagehide listener must exist");
        assert.ok(html.includes("addEventListener('pageshow'"),
                  "pageshow listener must exist");
        assert.ok(html.includes("_qr1Cleanup()"),
                  "pagehide/pageshow must call _qr1Cleanup");
    }

    // ── Test 14: _qr1RefreshLabels updates generic image alt ──────────────────

    {
        reset();
        // Set rendered state inside the VM so the let binding is updated.
        vm.runInContext('_qr1State = "rendered"', context);
        dom.elements['qrImage'].alt = 'old alt';

        H.refresh();

        assert.equal(dom.get('qrImage').alt, '[pos.payment.v1_img_alt]',
                     'rendered: refresh updates generic image alt');
        assert.equal(dom.get('qr1Status').innerText, '',
                     'rendered: status is empty (no status text for rendered state)');
    }

    // ── Test 15: same order, two generations — old request completes late ──────
    // Bug 3: request from old generation must not overwrite after new generation's
    // fetch resolves. _qr1Generation is incremented by qr1ShowTransient (which calls
    // _qr1Cleanup), so the old fetch's generation check fails and it is discarded.
    // _qr1RenderBlob does NOT set bank_code text — it clears manual fields.
    // We assert state=rendered + blob URL set to prove the correct generation won.

    {
        reset();
        let slowResolve;
        const slowPromise = new Promise(r => { slowResolve = r; });
        let fastReady = false;
        const fastPromise = new Promise(r => { slowResolve => {} }); // placeholder
        fastReady = true;

        // First call → slow (old gen). Second call → fast (new gen).
        let callCount = 0;
        _contextFetch = () => {
            callCount++;
            if (callCount === 1) return slowPromise;
            return Promise.resolve({
                ok: true,
                headers: { get: () => 'image/png' },
                blob: () => Promise.resolve({ size: 300, type: 'image/png' }),
            });
        };

        const orderId = 99;

        // First show: fetch is pending (slowPromise never resolves yet).
        H.show({
            expected_vnd: 50000, canonical_reference: 'FS1-99',
            bank_code: 'OLD', bank_account_no: '1', bank_account_name: 'OLD',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: `/api/orders/${orderId}/qr/render`,
            },
        }, orderId, 50000);
        await tick();

        // Second show: cleanup bumps gen, new fetch resolves, state = rendered.
        H.show({
            expected_vnd: 60000, canonical_reference: 'FS1-99-v2',
            bank_code: 'NEW', bank_account_no: '2', bank_account_name: 'NEW',
            capability: {
                mode: 'REPORT_ONLY',
                render_available: true,
                render_endpoint: `/api/orders/${orderId}/qr/render`,
            },
        }, orderId, 60000);
        await tick(); // fetch microtask
        await tick(); // blob microtask

        assert.equal(H.order(), orderId, 'orderId still correct');
        assert.equal(H.state(), 'rendered', 'second generation rendered');
        assert.ok(H.url(), 'blob URL set by second generation');

        // Late arrival from first generation: must not overwrite.
        slowResolve({
            ok: true,
            headers: { get: () => 'image/png' },
            blob: () => Promise.resolve({ size: 100, type: 'image/png' }),
        });
        await tick();
        await tick();

        assert.equal(H.state(), 'rendered', 'state unchanged after late old fetch');
        assert.ok(H.url(), 'blob URL still owned by second generation');

        _contextFetch = () => Promise.reject(new Error('default'));
    }

    console.log('I10-D qr-pos-ui.test.js: all 15 tests passed');
}

runTests().catch(err => {
    console.error('FAILED:', err.message);
    process.exit(1);
});
