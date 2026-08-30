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

    return { createController };
});
