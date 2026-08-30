(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.FSellingSalesHistoryR1 = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    const finalStatuses = new Set(['PAID', 'DEBT']);

    function errorCode(error) {
        const status = Number(error?.status);
        if (status === 401) return 'session';
        if (status === 403) return 'forbidden';
        if (status === 404) return 'not_found';
        return 'network';
    }

    function createController({ request, getShopId, onReceipt }) {
        let listRequestId = 0;
        let detailRequestId = 0;
        let listener = () => {};
        const state = {
            open: false,
            scope: 'today',
            query: '',
            page: 0,
            orders: [],
            hasMore: false,
            loading: false,
            loadingMore: false,
            error: '',
            searchingAllHistory: false,
            detail: null,
            detailLoading: false,
            detailError: ''
        };
        const snapshot = () => ({
            ...state,
            orders: state.orders.slice(),
            detail: state.detail ? { ...state.detail } : null
        });
        const publish = () => listener(snapshot());

        async function load(page, append) {
            const shopId = Number(getShopId());
            if (!Number.isSafeInteger(shopId) || shopId <= 0) {
                state.loading = false;
                state.loadingMore = false;
                state.error = 'select_shop';
                publish();
                return;
            }
            const token = ++listRequestId;
            if (!append) {
                state.orders = [];
                state.page = 0;
                state.hasMore = false;
            }
            state.loading = !append;
            state.loadingMore = append;
            state.error = '';
            state.searchingAllHistory = Boolean(state.query);
            publish();
            const params = new URLSearchParams({
                scope: state.scope,
                page: String(page)
            });
            if (state.query) params.set('q', state.query);
            try {
                const data = await request(`/orders/${shopId}/history?${params}`);
                if (token !== listRequestId || shopId !== Number(getShopId())) return;
                state.orders = append ? state.orders.concat(data.orders) : data.orders.slice();
                state.page = data.page;
                state.hasMore = Boolean(data.has_more);
                state.searchingAllHistory = Boolean(data.searching_all_history);
            } catch (error) {
                if (token === listRequestId) state.error = errorCode(error);
            } finally {
                if (token === listRequestId) {
                    state.loading = false;
                    state.loadingMore = false;
                    publish();
                }
            }
        }

        function resetState() {
            Object.assign(state, {
                open: false,
                scope: 'today',
                query: '',
                page: 0,
                orders: [],
                hasMore: false,
                loading: false,
                loadingMore: false,
                error: '',
                searchingAllHistory: false,
                detail: null,
                detailLoading: false,
                detailError: ''
            });
        }

        return {
            subscribe(fn) {
                listener = fn;
                publish();
                return () => { listener = () => {}; };
            },
            getState: snapshot,
            async open() {
                listRequestId += 1;
                detailRequestId += 1;
                resetState();
                state.open = true;
                publish();
                await load(1, false);
            },
            close() {
                listRequestId += 1;
                detailRequestId += 1;
                state.open = false;
                state.loading = false;
                state.loadingMore = false;
                state.detailLoading = false;
                publish();
            },
            async setScope(scope) {
                state.scope = scope === '7d' ? '7d' : 'today';
                state.query = '';
                await load(1, false);
            },
            async search(value) {
                state.query = String(value || '').trim();
                await load(1, false);
            },
            async clearSearch() {
                state.query = '';
                await load(1, false);
            },
            async loadMore() {
                if (!state.hasMore || state.loading || state.loadingMore) return;
                await load(state.page + 1, true);
            },
            async retry() {
                const append = state.orders.length > 0 && state.page > 0;
                await load(append ? state.page + 1 : 1, append);
            },
            async selectOrder(orderId) {
                const shopId = Number(getShopId());
                const token = ++detailRequestId;
                state.detail = null;
                state.detailError = '';
                state.detailLoading = true;
                publish();
                try {
                    const data = await request(`/orders/${Number(orderId)}/detail`);
                    if (token !== detailRequestId || shopId !== Number(getShopId())) return;
                    if (Number(data.shop_id) !== shopId) {
                        throw Object.assign(new Error(), { code: 'other_shop' });
                    }
                    if (!finalStatuses.has(data.status)) {
                        throw Object.assign(new Error(), { code: 'not_finalized' });
                    }
                    state.detail = { ...data, receipt_copy: true };
                    onReceipt(state.detail);
                } catch (error) {
                    if (token === detailRequestId) {
                        state.detailError = error?.code || errorCode(error);
                    }
                } finally {
                    if (token === detailRequestId) {
                        state.detailLoading = false;
                        publish();
                    }
                }
            },
            closeDetail() {
                detailRequestId += 1;
                state.detail = null;
                state.detailLoading = false;
                state.detailError = '';
                publish();
            },
            resetForShopChange() {
                listRequestId += 1;
                detailRequestId += 1;
                resetState();
                publish();
            }
        };
    }

    function renderOrderCard(order, ui) {
        const name = order.customer_name || ui.t('pos.sales_history.guest');
        const status = `pos.sales_history.${String(order.status).toLowerCase()}`;
        const payment = `pos.sales_history.${String(order.payment_method).toLowerCase()}`;
        return `<button type="button" class="sales-history-order" data-order-id="${Number(order.id)}">
            <span><strong>#${Number(order.id)}</strong><small>${ui.escapeHtml(ui.dateTime(order.created_at))}</small><em>${ui.escapeHtml(ui.t(status))}</em></span>
            <span><strong>${ui.escapeHtml(name)}</strong><small>${ui.escapeHtml(order.customer_phone_masked || '')}</small></span>
            <span><strong>${ui.escapeHtml(ui.money(order.total_amount))}</strong><small>${ui.escapeHtml(ui.t(payment))}</small></span>
        </button>`;
    }

    function renderDetail(detail, ui) {
        const lines = (detail.items || []).map(item => `<li>
            <span><strong>${ui.escapeHtml(item.product_name || '')}</strong><small>${ui.escapeHtml(ui.money(item.price))} × ${Number(item.quantity) || 0}</small></span>
            <span>${ui.escapeHtml(ui.money(item.line_total))}</span>
        </li>`).join('');
        const customerName = detail.customer?.name || ui.t('pos.sales_history.guest');
        return `<div class="sales-history-detail-head">
            <strong>#${Number(detail.id)}</strong>
            <span>${ui.escapeHtml(ui.dateTime(detail.created_at))}</span>
        </div>
        <p class="sales-history-detail-customer"><span>${ui.escapeHtml(ui.t('pos.sales_history.customer'))}</span><strong>${ui.escapeHtml(customerName)}</strong></p>
        <ul>${lines}</ul>
        <p class="sales-history-detail-total"><span>${ui.escapeHtml(ui.t('pos.sales_history.total'))}</span><strong>${ui.escapeHtml(ui.money(detail.total_amount))}</strong></p>
        <div class="sales-history-detail-actions">
            <button type="button" data-history-action="print">${ui.escapeHtml(ui.t('pos.sales_history.print'))}</button>
            <button type="button" data-history-action="share">${ui.escapeHtml(ui.t('pos.sales_history.share'))}</button>
            <button type="button" data-history-action="close-detail">${ui.escapeHtml(ui.t('pos.sales_history.close'))}</button>
        </div>`;
    }

    function mount(options) {
        const doc = options.document || document;
        const ui = {
            t: options.t,
            escapeHtml: options.escapeHtml,
            money: options.money,
            dateTime: options.dateTime
        };
        const elements = {
            form: doc.getElementById('salesHistoryForm'),
            search: doc.getElementById('salesHistorySearch'),
            submit: doc.getElementById('salesHistorySubmit'),
            today: doc.getElementById('salesHistoryToday'),
            seven: doc.getElementById('salesHistory7d'),
            hint: doc.getElementById('salesHistoryAllHint'),
            status: doc.getElementById('salesHistoryStatus'),
            list: doc.getElementById('salesHistoryList'),
            more: doc.getElementById('salesHistoryLoadMore'),
            detail: doc.getElementById('salesHistoryDetail'),
            close: doc.getElementById('salesHistoryClose'),
            modal: doc.getElementById('salesHistoryModal')
        };
        const controller = createController({
            request: options.request,
            getShopId: options.getShopId,
            onReceipt: options.prepareReceipt
        });
        let current = controller.getState();
        let focusedDetailId = null;

        const actionButton = (action, key) =>
            `<button type="button" data-history-action="${action}">${ui.escapeHtml(ui.t(key))}</button>`;

        function render(state) {
            current = state;
            elements.today.setAttribute('aria-pressed', String(state.scope === 'today'));
            elements.seven.setAttribute('aria-pressed', String(state.scope === '7d'));
            elements.today.disabled = Boolean(state.query);
            elements.seven.disabled = Boolean(state.query);
            elements.hint.hidden = !state.searchingAllHistory;
            elements.submit.disabled = state.loading;
            if (state.loading && state.orders.length === 0) {
                elements.list.innerHTML = '<div class="sales-history-skeleton"></div>'.repeat(3);
                elements.status.textContent = ui.t('pos.sales_history.loading');
            } else {
                elements.list.innerHTML = state.orders.map(order => renderOrderCard(order, ui)).join('');
                if (state.error) {
                    const key = state.error === 'forbidden' ? 'pos.sales_history.permission_error'
                        : state.error === 'session' ? 'pos.sales_history.session_error'
                        : state.error === 'select_shop' ? 'pos.sales_history.select_shop'
                        : 'pos.sales_history.network_error';
                    const action = state.error === 'session'
                        ? actionButton('login', 'pos.sales_history.login_again')
                        : actionButton('retry', 'pos.sales_history.retry');
                    elements.status.innerHTML = `${ui.escapeHtml(ui.t(key))} ${action}`;
                } else if (state.orders.length === 0 && state.query) {
                    elements.status.innerHTML = `${ui.escapeHtml(ui.t('pos.sales_history.no_results'))} ${actionButton('clear', 'pos.sales_history.clear_search')}`;
                } else if (state.orders.length === 0) {
                    const emptyKey = state.scope === '7d'
                        ? 'pos.sales_history.empty_seven_days'
                        : 'pos.sales_history.empty_today';
                    const next = state.scope === 'today'
                        ? actionButton('seven-days', 'pos.sales_history.show_seven_days')
                        : '';
                    elements.status.innerHTML = `${ui.escapeHtml(ui.t(emptyKey))} ${next}`;
                } else {
                    elements.status.textContent = '';
                }
            }
            elements.more.hidden = !state.hasMore;
            elements.more.disabled = state.loadingMore;
            elements.more.textContent = ui.t(state.loadingMore
                ? 'pos.sales_history.loading_more'
                : 'pos.sales_history.load_more');

            elements.detail.hidden = !(state.detailLoading || state.detailError || state.detail);
            if (state.detailLoading) {
                focusedDetailId = null;
                elements.detail.textContent = ui.t('pos.sales_history.loading_detail');
            } else if (state.detailError) {
                const key = `pos.sales_history.detail_${state.detailError}`;
                elements.detail.innerHTML = `${ui.escapeHtml(ui.t(key))} ${actionButton('close-detail', 'pos.sales_history.close')}`;
            } else if (state.detail) {
                elements.detail.innerHTML = renderDetail(state.detail, ui);
                if (focusedDetailId !== state.detail.id) {
                    focusedDetailId = state.detail.id;
                    elements.detail.focus?.({ preventScroll: true });
                    elements.detail.scrollIntoView?.({ block: 'nearest' });
                }
            } else {
                focusedDetailId = null;
                elements.detail.textContent = '';
            }
        }

        controller.subscribe(render);
        elements.form.addEventListener('submit', event => {
            event.preventDefault();
            controller.search(elements.search.value);
        });
        elements.today.addEventListener('click', () => {
            elements.search.value = '';
            controller.setScope('today');
        });
        elements.seven.addEventListener('click', () => {
            elements.search.value = '';
            controller.setScope('7d');
        });
        elements.more.addEventListener('click', () => controller.loadMore());
        elements.close.addEventListener('click', () => api.close());
        elements.list.addEventListener('click', event => {
            const card = event.target.closest('[data-order-id]');
            if (card) controller.selectOrder(Number(card.dataset.orderId));
        });
        elements.status.addEventListener('click', event => {
            const action = event.target.dataset.historyAction;
            if (action === 'retry') controller.retry();
            if (action === 'clear') {
                elements.search.value = '';
                controller.clearSearch();
            }
            if (action === 'seven-days') {
                elements.search.value = '';
                controller.setScope('7d');
            }
            if (action === 'login') options.goToLogin();
        });
        elements.detail.addEventListener('click', async event => {
            const action = event.target.dataset.historyAction;
            if (action === 'close-detail') {
                const orderId = current.detail?.id;
                controller.closeDetail();
                elements.list.querySelector?.(`[data-order-id="${Number(orderId)}"]`)?.focus();
                return;
            }
            if (!current.detail || !['print', 'share'].includes(action)) return;
            event.target.disabled = true;
            try {
                if (action === 'print') options.printReceipt(current.detail);
                else await options.shareReceipt(current.detail);
            } finally {
                event.target.disabled = false;
            }
        });
        elements.modal.addEventListener('keydown', event => {
            if (event.key !== 'Tab') return;
            const focusable = [...elements.modal.querySelectorAll(
                'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )].filter(node => !node.hidden);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && doc.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && doc.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
        doc.addEventListener('fselling:localechange', () => render(current));

        const api = {
            open() {
                elements.search.value = '';
                return controller.open();
            },
            close() {
                controller.close();
                options.closeModal('salesHistoryModal');
            },
            resetForShopChange: () => controller.resetForShopChange(),
            getState: controller.getState
        };
        return api;
    }

    return { createController, renderOrderCard, renderDetail, mount };
});
