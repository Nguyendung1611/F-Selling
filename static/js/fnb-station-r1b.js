(function (global) {
    'use strict';

    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]));

    function createStationController(deps) {
        const state = { shopId: null, station: null, revision: null, tickets: [], pending: null, timer: null, disposed: false };
        let pendingPromise = null;
        const uuid = () => deps.uuid?.() || global?.crypto?.randomUUID?.() || `ticket-${Date.now()}`;
        const delay = () => deps.isHidden?.() ? 10_000 : 2_000;

        async function load(force = false) {
            if (state.disposed || !state.shopId) return;
            if (state.timer !== null) {
                deps.clearTimeoutFn(state.timer);
                state.timer = null;
            }
            const suffix = !force && Number.isInteger(state.revision) ? `&after_revision=${state.revision}` : '';
            try {
                const result = await deps.request(`/fnb/stations/${state.station}/tickets?shop_id=${state.shopId}${suffix}`, 'GET');
                if (result?.changed !== false) {
                    state.revision = Number(result.revision);
                    state.tickets = result.tickets || [];
                    deps.render({ type: 'queue', value: result });
                }
                return result;
            } catch (error) {
                deps.render({ type: 'error', error, hasData: state.tickets.length > 0 });
                throw error;
            } finally {
                if (!state.disposed) state.timer = deps.setTimeoutFn(() => load(false).catch(() => {}), delay());
            }
        }

        async function performPending() {
            if (!state.pending) return;
            if (state.pending.inFlight && pendingPromise) return pendingPromise;
            state.pending.inFlight = true;
            deps.render({ type: 'pending', value: state.pending });
            pendingPromise = (async () => {
                try {
                    const result = await deps.request(state.pending.endpoint, 'POST', state.pending.body);
                    state.pending = null;
                    pendingPromise = null;
                    state.revision = Number(result.revision);
                    state.tickets = state.tickets
                        .map(ticket => Number(ticket.id) === Number(result.id) ? result : ticket)
                        .filter(ticket => !['DONE', 'CANCELLED'].includes(ticket.status));
                    deps.render({ type: 'queue', value: { tickets: state.tickets, revision: state.revision } });
                    return result;
                } catch (error) {
                    if (Number(error?.status) >= 400 && Number(error?.status) < 500) state.pending = null;
                    else if (state.pending) state.pending.inFlight = false;
                    pendingPromise = null;
                    deps.render({ type: 'transition-error', error });
                    throw error;
                }
            })();
            return pendingPromise;
        }

        function transition(ticketId, action, reason = null) {
            if (state.pending) return performPending();
            const ticket = state.tickets.find(row => Number(row.id) === Number(ticketId));
            if (!ticket) return Promise.reject(new Error('Ticket unavailable'));
            state.pending = {
                endpoint: `/fnb/tickets/${Number(ticketId)}/${action}`,
                body: {
                    expected_state_version: Number(ticket.state_version || 0),
                    operation_id: uuid(),
                    ...(reason ? { reason } : {}),
                },
                inFlight: false,
            };
            return performPending();
        }

        async function start(shopId, station) {
            state.shopId = Number(shopId);
            state.station = String(station).toUpperCase();
            state.revision = null;
            state.tickets = [];
            deps.render({ type: 'loading' });
            return load(true);
        }

        function dispose() {
            state.disposed = true;
            deps.clearTimeoutFn(state.timer);
        }

        return { start, load, transition, dispose, getState: () => ({ ...state, tickets: [...state.tickets] }) };
    }

    const api = Object.freeze({ createStationController, escapeHtml });
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (global) global.FnbStationR1B = api;
    if (!global?.document) return;

    function mount() {
        if (!localStorage.getItem('token')) return redirectToLogin();
        const station = location.pathname.split('/').filter(Boolean).at(-1)?.toUpperCase();
        const role = localStorage.getItem('role');
        const staffRole = (localStorage.getItem('staff_role') || 'MANAGER').toUpperCase();
        if (!['KITCHEN', 'BAR'].includes(station)
            || (role === 'STAFF' && !['MANAGER', station].includes(staffRole))) {
            return navigateToPage('/fnb');
        }
        const title = document.getElementById('fnbStationTitle');
        const list = document.getElementById('fnbStationTickets');
        const status = document.getElementById('fnbStationStatus');
        const shopSelect = document.getElementById('fnbStationShop');
        title.textContent = station === 'KITCHEN' ? 'Bếp đang chờ' : 'Bar đang chờ';

        function render(event) {
            if (event.type === 'loading') {
                status.textContent = 'Đang tải phiếu…';
                list.innerHTML = '<div class="fnb-skeleton" aria-hidden="true"></div><div class="fnb-skeleton" aria-hidden="true"></div>';
            } else if (event.type === 'queue') {
                status.textContent = '';
                const tickets = event.value.tickets || [];
                list.innerHTML = tickets.length ? tickets.map(ticket => `<article class="fnb-ticket-card" data-ticket-id="${Number(ticket.id)}"><header><div><span class="fnb-ticket-number">#${Number(ticket.sequence)}</span><h2>${escapeHtml((ticket.tables || []).join(' + '))}</h2></div><span class="fnb-ticket-status">${escapeHtml(ticket.status === 'NEW' ? 'Mới' : 'Đang làm')}</span></header><ul>${(ticket.items || []).map(item => `<li><strong>${Number(item.quantity)} × ${escapeHtml(item.product_name)}</strong>${item.note ? `<span>${escapeHtml(item.note)}</span>` : ''}</li>`).join('')}</ul>${ticket.out_of_stock_reason ? `<p class="fnb-ticket-warning">Hết món: ${escapeHtml(ticket.out_of_stock_reason)}</p>` : ''}<footer>${ticket.status === 'NEW' ? '<button type="button" data-action="start">Nhận làm</button>' : '<button type="button" data-action="done">Xong</button>'}<button type="button" class="fnb-secondary" data-action="out-of-stock">Báo hết món</button></footer></article>`).join('') : '<section class="fnb-empty"><h2>Chưa có phiếu mới</h2><p>Màn hình sẽ tự cập nhật khi quầy gửi món.</p></section>';
            } else if (event.type === 'pending') {
                status.textContent = 'Đang cập nhật phiếu…';
            } else {
                status.textContent = event.error?.message || 'Chưa cập nhật được. Kiểm tra mạng rồi thử lại.';
            }
        }

        const controller = createStationController({
            request: (endpoint, method, body) => apiCall(endpoint, method, body),
            render,
            setTimeoutFn: (callback, wait) => setTimeout(callback, wait),
            clearTimeoutFn: timer => clearTimeout(timer),
            isHidden: () => document.hidden,
        });

        document.addEventListener('click', event => {
            const button = event.target.closest('[data-action]');
            if (!button) return;
            const ticketId = Number(button.closest('[data-ticket-id]')?.dataset.ticketId);
            const action = button.dataset.action;
            let reason = null;
            if (action === 'out-of-stock') {
                reason = global.prompt('Món nào đã hết?');
                if (!reason?.trim()) return;
            }
            controller.transition(ticketId, action, reason?.trim()).catch(() => {});
        });
        shopSelect.addEventListener('change', () => controller.start(Number(shopSelect.value), station).catch(() => {}));
        global.addEventListener('online', () => controller.load(true).catch(() => {}));
        global.addEventListener('offline', () => { status.textContent = 'Đang mất kết nối. Phiếu gần nhất vẫn được giữ.'; });
        global.addEventListener('pagehide', () => controller.dispose(), { once: true });

        apiCall('/shops').then(shops => {
            const available = (shops || []).filter(shop => shop.is_active !== false && shop.fnb_enabled);
            shopSelect.innerHTML = available.map(shop => `<option value="${Number(shop.id)}">${escapeHtml(shop.name)}</option>`).join('');
            const saved = Number(localStorage.getItem('currentShopId'));
            const selected = available.find(shop => Number(shop.id) === saved) || available[0];
            if (!selected) return render({ type: 'error', error: new Error('Chưa có cửa hàng bật bán tại bàn.') });
            shopSelect.value = String(selected.id);
            controller.start(selected.id, station).catch(() => {});
        }).catch(error => render({ type: 'error', error }));
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
    else mount();
})(typeof window === 'undefined' ? null : window);
