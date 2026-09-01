(function (global) {
    'use strict';

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[character]));
    }

    function clone(value) {
        return typeof structuredClone === 'function'
            ? structuredClone(value)
            : JSON.parse(JSON.stringify(value));
    }

    function createController(deps) {
        const state = {
            shopId: null,
            floorRevision: null,
            floor: { areas: [] },
            setupFloor: { areas: [] },
            session: null,
            requestEpoch: 0,
            pendingMutation: null,
            recoverableDraft: null,
            pollTimer: null,
            disposed: false,
        };
        let pendingPromise = null;
        const canManageSetup = deps.role === 'SELLER'
            || (deps.role === 'STAFF' && deps.staffRole === 'MANAGER');
        const pollDelay = () => deps.isHidden?.() ? 10_000 : 2_000;
        const uuid = () => deps.uuid?.()
            || global?.crypto?.randomUUID?.()
            || `fnb-${Date.now()}-${Math.random().toString(16).slice(2)}`;

        deps.render({ type: 'setup-access', allowed: canManageSetup });

        function findTable(tableId, source = state.floor) {
            for (const area of source.areas || []) {
                const table = (area.tables || []).find(row => Number(row.id) === Number(tableId));
                if (table) return table;
            }
            return null;
        }

        function draftKey() {
            return `fnb.draft:${deps.username || 'anonymous'}:${state.shopId}:${state.session?.id || 'none'}`;
        }

        function saveDraft(value) {
            if (!state.session?.id) return;
            deps.storage?.set?.(draftKey(), JSON.stringify(value));
        }

        function clearDraft() {
            if (!state.session?.id) return;
            deps.storage?.delete?.(draftKey());
            deps.storage?.removeItem?.(draftKey());
        }

        function getDraft() {
            if (!state.session?.id) return null;
            const raw = deps.storage?.get?.(draftKey()) ?? deps.storage?.getItem?.(draftKey());
            if (!raw) return null;
            try { return JSON.parse(raw); } catch (error) { return null; }
        }

        async function loadSession(sessionId) {
            const expectedShop = state.shopId;
            const result = await deps.request(`/fnb/sessions/${Number(sessionId)}`, 'GET');
            if (!result || state.disposed || expectedShop !== state.shopId) return;
            state.session = result;
            deps.render({ type: 'session', value: result, draft: getDraft(), saved: false });
            return result;
        }

        async function refreshOpenSessionFromFloor() {
            if (!state.session || state.pendingMutation) return;
            const summaries = (state.floor.areas || []).flatMap(area =>
                (area.tables || []).map(table => table.session).filter(Boolean)
            );
            const summary = summaries.find(row => Number(row.id) === Number(state.session.id));
            if (!summary) {
                state.session = null;
                clearDraft();
                deps.render({ type: 'session-closed' });
            } else if (Number(summary.revision) !== Number(state.session.revision)) {
                await loadSession(summary.id);
            }
        }

        async function loadFloor(force = false) {
            const shopId = Number(state.shopId);
            if (!Number.isSafeInteger(shopId) || state.disposed) return;
            const epoch = ++state.requestEpoch;
            const suffix = !force && Number.isInteger(state.floorRevision)
                ? `&after_revision=${state.floorRevision}` : '';
            try {
                const result = await deps.request(`/fnb/floor?shop_id=${shopId}${suffix}`, 'GET');
                if (!result || state.disposed || epoch !== state.requestEpoch || shopId !== state.shopId) return;
                if (result.changed !== false) {
                    state.floor = result;
                    state.floorRevision = Number(result.fnb_revision);
                    deps.render({ type: 'floor', value: result });
                    await refreshOpenSessionFromFloor();
                }
            } catch (error) {
                if (!state.disposed && epoch === state.requestEpoch && shopId === state.shopId) {
                    if ((error.code || error.detail?.code) === 'FNB_DISABLED') {
                        dispose();
                        state.floor = { areas: [] };
                        state.session = null;
                        deps.render({ type: 'feature-disabled', error });
                    } else {
                        deps.render({
                            type: 'floor-error',
                            error,
                            hasData: state.floor.areas.length > 0,
                        });
                    }
                }
            } finally {
                if (!state.disposed && epoch === state.requestEpoch && shopId === state.shopId) {
                    state.pollTimer = deps.setTimeoutFn(() => loadFloor(false), pollDelay());
                }
            }
        }

        async function loadSetup() {
            if (!canManageSetup || !Number.isSafeInteger(Number(state.shopId))) return;
            deps.render({ type: 'setup-loading' });
            try {
                const result = await deps.request(
                    `/fnb/floor?shop_id=${Number(state.shopId)}&include_inactive=true`,
                    'GET',
                );
                if (!result || state.disposed) return;
                state.setupFloor = result;
                state.floorRevision = Number(result.fnb_revision);
                deps.render({ type: 'setup', value: result });
                return result;
            } catch (error) {
                deps.render({ type: 'setup-error', error });
                throw error;
            }
        }

        async function selectShop(shopId) {
            deps.clearTimeoutFn(state.pollTimer);
            state.requestEpoch += 1;
            state.shopId = Number(shopId);
            state.floorRevision = null;
            state.floor = { areas: [] };
            state.setupFloor = { areas: [] };
            state.session = null;
            state.recoverableDraft = null;
            state.pendingMutation = null;
            pendingPromise = null;
            deps.render({ type: 'loading' });
            return loadFloor(true);
        }

        function clearPending() {
            state.pendingMutation = null;
            pendingPromise = null;
        }

        function isDefinitive4xx(error) {
            const status = Number(error?.status);
            return status >= 400 && status < 500;
        }

        function performPending() {
            if (!state.pendingMutation) return Promise.resolve();
            if (state.pendingMutation.inFlight && pendingPromise) return pendingPromise;
            state.pendingMutation.inFlight = true;
            deps.render({ type: 'mutation-pending', value: clone(state.pendingMutation) });
            const mutation = state.pendingMutation;
            pendingPromise = (async () => {
                try {
                    const result = await deps.request(
                        mutation.endpoint,
                        mutation.method,
                        mutation.body,
                    );
                    clearPending();
                    state.recoverableDraft = null;
                    if (mutation.scope === 'session') {
                        clearDraft();
                        if (result?.status === 'CANCELLED') {
                            state.session = null;
                            deps.render({ type: 'session-cancelled', value: result });
                        } else {
                            state.session = result;
                            deps.render({ type: 'session', value: result, draft: null, saved: true });
                        }
                    } else {
                        if (Number.isInteger(Number(result?.fnb_revision))) {
                            state.floorRevision = Number(result.fnb_revision);
                        }
                        deps.render({ type: 'setup-success', value: result });
                    }
                    await loadFloor(true);
                    return result;
                } catch (error) {
                    const code = error?.code || error?.detail?.code;
                    if (
                        (code === 'FNB_SESSION_CHANGED' || code === 'FNB_LINE_CHANGED')
                        && error?.detail?.snapshot
                    ) {
                        state.session = error.detail.snapshot;
                        state.recoverableDraft = clone(mutation.attempt);
                        saveDraft(state.recoverableDraft);
                        deps.render({
                            type: 'conflict',
                            value: state.session,
                            draft: state.recoverableDraft,
                        });
                    } else if (code === 'FNB_FLOOR_CHANGED') {
                        await loadFloor(true);
                        deps.render({
                            type: 'setup-error',
                            error,
                            value: clone(mutation.attempt),
                        });
                    } else if (code === 'FNB_DISABLED') {
                        dispose();
                        state.floor = { areas: [] };
                        state.session = null;
                        deps.render({ type: 'feature-disabled', error });
                    } else if (mutation.scope === 'setup') {
                        deps.render({
                            type: 'setup-error',
                            error,
                            value: clone(mutation.attempt),
                        });
                    } else {
                        state.recoverableDraft = clone(mutation.attempt);
                        saveDraft(state.recoverableDraft);
                        deps.render({
                            type: 'mutation-error',
                            error,
                            draft: state.recoverableDraft,
                        });
                    }
                    if (isDefinitive4xx(error)) {
                        clearPending();
                    } else if (state.pendingMutation) {
                        state.pendingMutation.inFlight = false;
                        pendingPromise = null;
                    }
                    throw error;
                }
            })();
            return pendingPromise;
        }

        function startMutation(action, endpoint, method, body, attempt, scope) {
            if (state.pendingMutation) return performPending();
            const operationId = uuid();
            state.pendingMutation = {
                action,
                endpoint,
                method,
                body: { ...body, operation_id: operationId },
                operationId,
                attempt: clone(attempt),
                scope,
                inFlight: false,
            };
            return performPending();
        }

        function createArea(values) {
            return startMutation('create-area', '/fnb/areas', 'POST', {
                shop_id: Number(state.shopId),
                name: values.name,
                sort_order: Number(values.sort_order || 0),
                expected_revision: Number(state.floorRevision),
            }, values, 'setup');
        }

        function updateArea(areaId, values) {
            return startMutation('update-area', `/fnb/areas/${Number(areaId)}`, 'PATCH', {
                ...values,
                ...(values.sort_order === undefined ? {} : { sort_order: Number(values.sort_order) }),
                expected_revision: Number(state.floorRevision),
            }, values, 'setup');
        }

        function createTable(values) {
            return startMutation('create-table', '/fnb/tables', 'POST', {
                shop_id: Number(state.shopId),
                area_id: Number(values.area_id),
                name: values.name,
                sort_order: Number(values.sort_order || 0),
                expected_revision: Number(state.floorRevision),
            }, values, 'setup');
        }

        function updateTable(tableId, values) {
            const setupTable = findTable(tableId, state.setupFloor);
            const liveTable = findTable(tableId);
            const table = Number(liveTable?.state_version) > Number(setupTable?.state_version)
                ? liveTable : (setupTable || liveTable);
            return startMutation('update-table', `/fnb/tables/${Number(tableId)}`, 'PATCH', {
                ...values,
                ...(values.area_id === undefined ? {} : { area_id: Number(values.area_id) }),
                ...(values.sort_order === undefined ? {} : { sort_order: Number(values.sort_order) }),
                expected_revision: Number(state.floorRevision),
                expected_state_version: Number(table?.state_version || 0),
            }, values, 'setup');
        }

        function openTable(tableId) {
            const table = findTable(tableId);
            if (!table) return Promise.reject(new Error('Table unavailable'));
            if (table.session?.id) return loadSession(table.session.id);
            return startMutation('open-table', '/fnb/sessions', 'POST', {
                shop_id: Number(state.shopId),
                table_id: Number(table.id),
                expected_revision: Number(state.floorRevision),
                expected_table_version: Number(table.state_version),
            }, { table_id: Number(table.id) }, 'session');
        }

        function addLine(draft) {
            const attempt = { product_id: Number(draft.product_id), quantity: Number(draft.quantity), note: draft.note || '' };
            return startMutation('add-line', `/fnb/sessions/${Number(state.session.id)}/lines`, 'POST', {
                ...attempt,
                expected_revision: Number(state.session.revision),
            }, attempt, 'session');
        }

        function updateLine(lineId, draft) {
            const line = (state.session?.lines || []).find(row => Number(row.id) === Number(lineId));
            const attempt = { line_id: Number(lineId), quantity: Number(draft.quantity), note: draft.note || '' };
            return startMutation('update-line', `/fnb/lines/${Number(lineId)}`, 'PATCH', {
                quantity: attempt.quantity,
                note: attempt.note,
                expected_line_version: Number(line?.state_version || 0),
                expected_revision: Number(state.session.revision),
            }, attempt, 'session');
        }

        function cancelLine(lineId, quantity) {
            const line = (state.session?.lines || []).find(row => Number(row.id) === Number(lineId));
            const attempt = { line_id: Number(lineId), quantity: Number(quantity) };
            return startMutation('cancel-line', `/fnb/sessions/${Number(state.session.id)}/cancel-line`, 'POST', {
                ...attempt,
                expected_line_version: Number(line?.state_version || 0),
                expected_revision: Number(state.session.revision),
            }, attempt, 'session');
        }

        function moveTable(fromTableId, toTableId) {
            const source = (state.session?.tables || []).find(row => Number(row.id) === Number(fromTableId));
            const target = findTable(toTableId);
            const attempt = { from_table_id: Number(fromTableId), to_table_id: Number(toTableId) };
            return startMutation('move-table', `/fnb/sessions/${Number(state.session.id)}/move-table`, 'POST', {
                ...attempt,
                expected_revision: Number(state.session.revision),
                expected_from_state_version: Number(source?.state_version || 0),
                expected_to_state_version: Number(target?.state_version || 0),
            }, attempt, 'session');
        }

        function mergeTable(targetTableId) {
            const target = findTable(targetTableId);
            const attempt = { target_table_id: Number(targetTableId) };
            return startMutation('merge-table', `/fnb/sessions/${Number(state.session.id)}/merge-table`, 'POST', {
                ...attempt,
                expected_revision: Number(state.session.revision),
                expected_target_session_revision: target?.session
                    ? Number(target.session.revision) : null,
                expected_target_table_version: Number(target?.state_version || 0),
            }, attempt, 'session');
        }

        function cancelSession(reason = '') {
            const attempt = { reason };
            return startMutation('cancel-session', `/fnb/sessions/${Number(state.session.id)}/cancel`, 'POST', {
                expected_revision: Number(state.session.revision),
                reason,
            }, attempt, 'session');
        }

        function dispose() {
            state.disposed = true;
            deps.clearTimeoutFn(state.pollTimer);
        }

        return {
            selectShop,
            loadFloor,
            loadSetup,
            loadSession,
            getState: () => clone(state),
            seedSession: sessionValue => { state.session = clone(sessionValue); },
            saveDraft,
            getDraft,
            clearDraft,
            dispose,
            createArea,
            updateArea,
            createTable,
            updateTable,
            openTable,
            addLine,
            updateLine,
            cancelLine,
            moveTable,
            mergeTable,
            cancelSession,
        };
    }

    const api = Object.freeze({ createController, escapeHtml });
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (global) global.FnbR1A = api;

    if (!global?.document) return;

    function mount() {
        const role = localStorage.getItem('role');
        const staffRole = (localStorage.getItem('staff_role') || 'MANAGER').toUpperCase();
        if (!localStorage.getItem('token')) return redirectToLogin();
        if (role === 'STAFF' && staffRole === 'WAREHOUSE') {
            nhanSangTrangSau(t('fnb.auth.warehouse'));
            return navigateToPage('/pos');
        }
        if (!['SELLER', 'STAFF'].includes(role)) {
            nhanSangTrangSau(t('fnb.auth.no_access'));
            return navigateToPage('/pos');
        }

        const elements = Object.fromEntries([
            'fnbShopSelect', 'fnbFloor', 'fnbAreaTabs', 'fnbLiveStatus', 'fnbRetry', 'fnbRefreshNote',
            'fnbSetupOpen', 'fnbSetupDialog', 'fnbSetupAreas', 'fnbSetupStatus',
            'fnbAreaForm', 'fnbAreaName', 'fnbTableForm', 'fnbTableArea', 'fnbTableName',
            'fnbSessionPanel', 'fnbSessionBackdrop', 'fnbSessionClose', 'fnbSessionTitle',
            'fnbProductSearch', 'fnbProductGrid', 'fnbDraftLines', 'fnbSubtotal',
            'fnbConflict', 'fnbSessionStatus', 'fnbTableActions', 'fnbTargetTable',
            'fnbCancelSession'
        ].map(id => [id, document.getElementById(id)]));
        let shops = [];
        let products = [];
        let selectedAreaId = null;
        let lastTableTrigger = null;
        let setupAllowed = false;

        const storage = {
            get: key => sessionStorage.getItem(key),
            set: (key, value) => sessionStorage.setItem(key, value),
            delete: key => sessionStorage.removeItem(key),
        };

        function money(value) {
            return global.FSellingI18n?.formatMoney?.(value)
                || `${Number(value || 0).toLocaleString('vi-VN')} ₫`;
        }

        function live(key, options) {
            elements.fnbLiveStatus.textContent = key ? t(key, options) : '';
        }

        function setupStatus(message) {
            elements.fnbSetupStatus.textContent = message || '';
        }

        function sessionStatus(message) {
            elements.fnbSessionStatus.textContent = message || '';
        }

        function skeletons() {
            elements.fnbFloor.innerHTML = Array.from(
                { length: 6 },
                () => '<div class="fnb-skeleton" aria-hidden="true"></div>',
            ).join('');
            live('fnb.state.loading');
        }

        function emptyPanel(titleKey, bodyKey, action) {
            elements.fnbFloor.innerHTML = `<section class="fnb-empty"><h3>${escapeHtml(t(titleKey))}</h3><p>${escapeHtml(t(bodyKey))}</p>${action || ''}</section>`;
        }

        function floorTables(value) {
            return (value.areas || []).flatMap(area => area.tables || []);
        }

        function renderFloor(value) {
            const nonemptyAreas = (value.areas || []).filter(area => (area.tables || []).length);
            if (!nonemptyAreas.length) {
                elements.fnbAreaTabs.innerHTML = '';
                const ownerAction = setupAllowed
                    ? `<button type="button" data-action="open-setup">${escapeHtml(t('fnb.setup.open'))}</button>`
                    : '';
                emptyPanel(
                    'fnb.state.no_tables',
                    setupAllowed ? 'fnb.state.no_tables_owner' : 'fnb.state.no_tables_staff',
                    ownerAction,
                );
                live('fnb.state.no_tables');
                return;
            }
            if (!nonemptyAreas.some(area => Number(area.id) === Number(selectedAreaId))) {
                selectedAreaId = nonemptyAreas[0].id;
            }
            elements.fnbAreaTabs.innerHTML = nonemptyAreas.map(area =>
                `<button type="button" data-action="select-area" data-id="${Number(area.id)}" aria-current="${Number(area.id) === Number(selectedAreaId)}">${escapeHtml(area.name)}</button>`
            ).join('');
            const area = nonemptyAreas.find(row => Number(row.id) === Number(selectedAreaId));
            elements.fnbFloor.innerHTML = (area.tables || []).map(table => {
                const serving = table.state === 'SERVING';
                const opened = table.session?.opened_at ? new Date(table.session.opened_at).getTime() : Date.now();
                const minutes = Math.max(0, Math.floor((Date.now() - opened) / 60000));
                return `<button type="button" class="fnb-table-card${serving ? ' is-serving' : ''}" data-action="open-table" data-id="${Number(table.id)}"><strong>${escapeHtml(table.name)}</strong><span class="fnb-table-state">${escapeHtml(t(serving ? 'fnb.table.serving' : 'fnb.table.empty'))}</span>${serving ? `<span class="fnb-table-meta"><span>${escapeHtml(t('fnb.table.elapsed', { minutes }))}</span><span>${escapeHtml(money(table.session?.subtotal_vnd || 0))}</span><span>${escapeHtml(t('fnb.table.unsent', { count: Number(table.session?.unsent_quantity || 0) }))}</span></span>` : ''}</button>`;
            }).join('');
            elements.fnbRetry.hidden = true;
            elements.fnbRefreshNote.hidden = true;
            live('');
        }

        function renderProducts() {
            const query = elements.fnbProductSearch.value.trim().toLocaleLowerCase();
            const matches = products.filter(product =>
                String(product.name || '').toLocaleLowerCase().includes(query)
            );
            elements.fnbProductGrid.innerHTML = matches.length
                ? matches.map(product => `<button type="button" data-action="add-product" data-id="${Number(product.id)}"><strong>${escapeHtml(product.name)}</strong><small>${escapeHtml(money(product.price))}</small></button>`).join('')
                : `<p>${escapeHtml(t('fnb.menu.empty'))}</p>`;
        }

        function renderTargets() {
            const state = controller.getState();
            const attached = new Set((state.session?.tables || []).map(table => Number(table.id)));
            const tables = floorTables(state.floor).filter(table => !attached.has(Number(table.id)));
            elements.fnbTargetTable.innerHTML = `<option value="">${escapeHtml(t('fnb.table_actions.select'))}</option>${tables.map(table => `<option value="${Number(table.id)}">${escapeHtml(table.name)} — ${escapeHtml(t(table.state === 'SERVING' ? 'fnb.table.serving' : 'fnb.table.empty'))}</option>`).join('')}`;
        }

        function renderSession(value, draft) {
            if (!value) return;
            elements.fnbSessionPanel.hidden = false;
            elements.fnbSessionPanel.inert = false;
            elements.fnbSessionBackdrop.hidden = false;
            elements.fnbSessionTitle.textContent = (value.tables || []).map(table => table.name).join(' + ');
            const pending = controller.getState().pendingMutation;
            const serverLines = (value.lines || []).map(line => {
                    const saved = draft?.line_id === line.id ? draft : null;
                    const unsynced = pending?.attempt?.line_id === line.id || saved;
                    return `<article class="fnb-draft-row" data-line-id="${Number(line.id)}"><header><strong>${escapeHtml(line.product_name || `#${line.product_id}`)}</strong>${unsynced ? `<span class="fnb-unsynced">${escapeHtml(t('fnb.state.unsynced'))}</span>` : ''}</header><div class="fnb-draft-edit"><label><span class="sr-only">${escapeHtml(t('fnb.draft.quantity'))}</span><input data-field="quantity" type="number" min="1" inputmode="numeric" value="${Number(saved?.quantity ?? line.quantity)}" aria-label="${escapeHtml(t('fnb.draft.quantity'))}"></label><label><span class="sr-only">${escapeHtml(t('fnb.draft.note'))}</span><input data-field="note" maxlength="500" value="${escapeHtml(saved?.note ?? line.note ?? '')}" placeholder="${escapeHtml(t('fnb.draft.note_placeholder'))}" aria-label="${escapeHtml(t('fnb.draft.note'))}"></label><button type="button" class="fnb-secondary" data-action="save-line" data-id="${Number(line.id)}">${escapeHtml(t('fnb.action.save'))}</button></div><button type="button" class="fnb-secondary" data-action="cancel-line" data-id="${Number(line.id)}">${escapeHtml(t('fnb.action.cancel_quantity'))}</button></article>`;
                }).join('');
            const localProduct = draft?.product_id && !draft.line_id
                ? products.find(product => Number(product.id) === Number(draft.product_id))
                : null;
            const localLine = localProduct
                ? `<article class="fnb-draft-row"><header><strong>${escapeHtml(localProduct.name)}</strong><span class="fnb-unsynced">${escapeHtml(t('fnb.state.unsynced'))}</span></header><div class="fnb-draft-edit"><input type="number" min="1" inputmode="numeric" value="${Number(draft.quantity)}" disabled aria-label="${escapeHtml(t('fnb.draft.quantity'))}"><input value="${escapeHtml(draft.note || '')}" disabled aria-label="${escapeHtml(t('fnb.draft.note'))}"><button type="button" data-action="reapply">${escapeHtml(t('fnb.action.retry'))}</button></div></article>`
                : '';
            elements.fnbDraftLines.innerHTML = serverLines || localLine
                ? serverLines + localLine
                : `<p>${escapeHtml(t('fnb.draft.empty'))}</p>`;
            elements.fnbSubtotal.textContent = t('fnb.session.total', { amount: money(value.subtotal_vnd) });
            elements.fnbTableActions.hidden = !setupAllowed;
            elements.fnbCancelSession.disabled = Number(value.unsent_quantity || 0) > 0;
            renderTargets();
            renderProducts();
        }

        function closeSession() {
            elements.fnbSessionPanel.hidden = true;
            elements.fnbSessionPanel.inert = true;
            elements.fnbSessionBackdrop.hidden = true;
            elements.fnbConflict.hidden = true;
            lastTableTrigger?.focus();
        }

        function renderSetup(value) {
            const areas = value.areas || [];
            const areaOptions = areas.filter(area => area.active !== false).map(area =>
                `<option value="${Number(area.id)}">${escapeHtml(area.name)}</option>`
            ).join('');
            elements.fnbTableArea.innerHTML = areaOptions;
            elements.fnbSetupAreas.innerHTML = areas.length ? areas.map(area => {
                const areaState = area.active === false ? 'fnb.setup.inactive' : 'fnb.setup.active';
                const tables = (area.tables || []).map(table => {
                    const occupied = table.state === 'SERVING';
                    return `<div class="fnb-setup-row" data-kind="table" data-id="${Number(table.id)}"><input data-field="name" maxlength="100" value="${escapeHtml(table.name)}" aria-label="${escapeHtml(t('fnb.setup.table_name'))}"><input data-field="sort_order" type="number" min="0" value="${Number(table.sort_order || 0)}" aria-label="${escapeHtml(t('fnb.setup.sort_order'))}"><button type="button" class="fnb-secondary" data-action="save-table">${escapeHtml(t('fnb.action.save'))}</button><button type="button" class="fnb-secondary" data-action="toggle-table" data-active="${table.active !== false}" ${occupied ? 'disabled' : ''}>${escapeHtml(t(table.active === false ? 'fnb.action.restore' : 'fnb.action.hide'))}</button>${occupied ? `<small>${escapeHtml(t('fnb.setup.occupied'))}</small>` : ''}</div>`;
                }).join('');
                return `<article class="fnb-setup-area${area.active === false ? ' is-inactive' : ''}" data-kind="area" data-id="${Number(area.id)}"><h3>${escapeHtml(area.name)} · ${escapeHtml(t(areaState))}</h3><div class="fnb-setup-row"><input data-field="name" maxlength="100" value="${escapeHtml(area.name)}" aria-label="${escapeHtml(t('fnb.setup.area_name'))}"><input data-field="sort_order" type="number" min="0" value="${Number(area.sort_order || 0)}" aria-label="${escapeHtml(t('fnb.setup.sort_order'))}"><button type="button" class="fnb-secondary" data-action="save-area">${escapeHtml(t('fnb.action.save'))}</button><button type="button" class="fnb-secondary" data-action="toggle-area" data-active="${area.active !== false}">${escapeHtml(t(area.active === false ? 'fnb.action.restore' : 'fnb.action.hide'))}</button></div>${tables}</article>`;
            }).join('') : `<p>${escapeHtml(t('fnb.state.no_tables'))}</p>`;
            setupStatus('');
        }

        function renderer(event) {
            if (event.type === 'setup-access') {
                setupAllowed = event.allowed;
                elements.fnbSetupOpen.hidden = !(setupAllowed && shops.length);
            } else if (event.type === 'loading') {
                skeletons();
            } else if (event.type === 'floor') {
                renderFloor(event.value);
            } else if (event.type === 'floor-error') {
                if (Number(event.error?.status) === 403) {
                    controller.dispose();
                    elements.fnbFloor.innerHTML = '';
                    nhanSangTrangSau(t('fnb.state.permission_lost'));
                    return navigateToPage('/pos');
                }
                elements.fnbRetry.hidden = false;
                elements.fnbRefreshNote.hidden = false;
                elements.fnbRefreshNote.textContent = t('fnb.state.poll_error');
                if (!event.hasData) {
                    emptyPanel('fnb.state.poll_error', 'fnb.state.poll_error_empty');
                }
                live('fnb.state.poll_error');
            } else if (event.type === 'session') {
                renderSession(event.value, event.draft);
                sessionStatus(event.saved ? t('fnb.session.saved') : '');
            } else if (event.type === 'session-closed' || event.type === 'session-cancelled') {
                closeSession();
                if (event.type === 'session-cancelled') showToast(t('fnb.session.cancelled'));
            } else if (event.type === 'mutation-pending') {
                sessionStatus(t('fnb.state.pending'));
                const mutation = event.value;
                const affected = mutation.action === 'open-table'
                    ? document.querySelector(`[data-action="open-table"][data-id="${Number(mutation.attempt.table_id)}"]`)
                    : mutation.attempt?.line_id
                        ? elements.fnbDraftLines.querySelector(`[data-line-id="${Number(mutation.attempt.line_id)}"]`)
                        : mutation.attempt?.product_id
                            ? elements.fnbProductGrid.querySelector(`[data-action="add-product"][data-id="${Number(mutation.attempt.product_id)}"]`)
                            : null;
                if (affected?.matches?.('button')) affected.disabled = true;
                affected?.querySelectorAll?.('button, input, select').forEach(control => { control.disabled = true; });
            } else if (event.type === 'mutation-error') {
                sessionStatus(`${t('fnb.state.unsynced')}. ${event.error?.message || t('fnb.action.retry')}`);
                renderSession(controller.getState().session, event.draft);
            } else if (event.type === 'conflict') {
                renderSession(event.value, event.draft);
                elements.fnbConflict.hidden = false;
                elements.fnbConflict.innerHTML = `<p>${escapeHtml(t('fnb.state.conflict'))}</p><button type="button" data-action="reapply">${escapeHtml(t('fnb.action.reapply'))}</button>`;
            } else if (event.type === 'setup-loading') {
                setupStatus(t('fnb.setup.loading'));
            } else if (event.type === 'setup') {
                renderSetup(event.value);
            } else if (event.type === 'setup-success') {
                setupStatus(t('fnb.setup.saved'));
                controller.loadSetup().catch(() => {});
            } else if (event.type === 'setup-error') {
                const code = event.error?.code || event.error?.detail?.code;
                setupStatus(t(code === 'FNB_NAME_EXISTS' ? 'fnb.setup.duplicate' : code === 'FNB_FLOOR_CHANGED' ? 'fnb.setup.changed' : 'fnb.state.poll_error'));
            } else if (event.type === 'feature-disabled') {
                elements.fnbFloor.innerHTML = '';
                closeSession();
                nhanSangTrangSau(t('fnb.auth.feature_disabled'));
                navigateToPage('/pos');
            }
        }

        const controller = createController({
            request: (endpoint, method, body) => apiCall(endpoint, method, body),
            render: renderer,
            setTimeoutFn: (callback, delay) => setTimeout(callback, delay),
            clearTimeoutFn: timer => clearTimeout(timer),
            isHidden: () => document.hidden,
            storage,
            now: () => Date.now(),
            username: localStorage.getItem('username') || 'anonymous',
            role,
            staffRole,
        });

        async function loadProducts() {
            const shopId = Number(elements.fnbShopSelect.value);
            try {
                const result = await apiCall(`/products/${shopId}`);
                products = (result || []).filter(product => product.is_active !== false && product.category_is_active !== false);
                renderProducts();
            } catch (error) {
                products = [];
                renderProducts();
            }
        }

        async function chooseShop(shopId) {
            localStorage.setItem('currentShopId', String(shopId));
            products = [];
            await Promise.all([controller.selectShop(Number(shopId)), loadProducts()]);
        }

        async function loadShops() {
            const result = await apiCall('/shops');
            shops = (result || []).filter(shop => shop.is_active !== false && shop.fnb_enabled);
            elements.fnbSetupOpen.hidden = !(setupAllowed && shops.length);
            elements.fnbShopSelect.innerHTML = shops.map(shop =>
                `<option value="${Number(shop.id)}">${escapeHtml(shop.name)}</option>`
            ).join('');
            if (!shops.length) {
                elements.fnbShopSelect.disabled = true;
                const owner = role === 'SELLER';
                emptyPanel(
                    'fnb.state.no_shops',
                    owner ? 'fnb.state.no_shops_owner' : 'fnb.state.no_shops_staff',
                    owner ? `<a class="fnb-back" href="/seller?setup=fnb">${escapeHtml(t('fnb.setup.open'))}</a>` : '',
                );
                live('fnb.state.no_shops');
                return;
            }
            const stored = Number(localStorage.getItem('currentShopId'));
            const selected = shops.find(shop => Number(shop.id) === stored) || shops[0];
            elements.fnbShopSelect.value = String(selected.id);
            await chooseShop(selected.id);
        }

        document.addEventListener('click', event => {
            const button = event.target.closest('[data-action]');
            if (!button) return;
            const action = button.dataset.action;
            const id = Number(button.dataset.id || button.closest('[data-id]')?.dataset.id);
            if (action === 'select-area') {
                selectedAreaId = id;
                renderFloor(controller.getState().floor);
            } else if (action === 'open-table') {
                lastTableTrigger = button;
                sessionStatus(t('fnb.session.loading'));
                controller.openTable(id).catch(error => sessionStatus(error.message));
            } else if (action === 'open-setup') {
                elements.fnbSetupDialog.showModal();
                controller.loadSetup().catch(() => {});
            } else if (action === 'add-product') {
                controller.addLine({ product_id: id, quantity: 1, note: '' }).catch(() => {});
            } else if (action === 'save-line') {
                const row = button.closest('[data-line-id]');
                controller.updateLine(id, {
                    quantity: Number(row.querySelector('[data-field="quantity"]').value),
                    note: row.querySelector('[data-field="note"]').value,
                }).catch(() => {});
            } else if (action === 'cancel-line') {
                controller.cancelLine(id, 1).catch(() => {});
            } else if (action === 'reapply') {
                const draft = controller.getState().recoverableDraft;
                if (!draft) return;
                const promise = draft.line_id
                    ? controller.updateLine(draft.line_id, draft)
                    : controller.addLine(draft);
                promise.catch(() => {});
            } else if (action === 'move-table' || action === 'merge-table') {
                const targetId = Number(elements.fnbTargetTable.value);
                if (!targetId) return;
                const sourceId = controller.getState().session?.tables?.[0]?.id;
                const promise = action === 'move-table'
                    ? controller.moveTable(sourceId, targetId)
                    : controller.mergeTable(targetId);
                promise.then(() => sessionStatus(t('fnb.table_actions.done'))).catch(error => sessionStatus(error.message));
            } else if (['save-area', 'toggle-area', 'save-table', 'toggle-table'].includes(action)) {
                const row = button.closest('[data-kind]');
                const isArea = row.dataset.kind === 'area';
                const values = action.startsWith('toggle-')
                    ? { active: button.dataset.active !== 'true' }
                    : {
                        name: row.querySelector('[data-field="name"]').value,
                        sort_order: Number(row.querySelector('[data-field="sort_order"]').value),
                    };
                const promise = isArea
                    ? controller.updateArea(Number(row.dataset.id), values)
                    : controller.updateTable(Number(row.dataset.id), values);
                promise.catch(() => {});
            }
        });

        elements.fnbRetry.addEventListener('click', () => controller.loadFloor(true));
        elements.fnbSetupOpen.addEventListener('click', () => {
            elements.fnbSetupDialog.showModal();
            controller.loadSetup().catch(() => {});
        });
        elements.fnbSessionClose.addEventListener('click', closeSession);
        elements.fnbSessionBackdrop.addEventListener('click', closeSession);
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !elements.fnbSessionPanel.hidden && !elements.fnbSetupDialog.open) {
                closeSession();
            }
        });
        elements.fnbProductSearch.addEventListener('input', renderProducts);
        elements.fnbShopSelect.addEventListener('change', event => chooseShop(Number(event.target.value)));
        elements.fnbCancelSession.addEventListener('click', () => controller.cancelSession().catch(error => sessionStatus(error.message)));
        elements.fnbAreaForm.addEventListener('submit', event => {
            event.preventDefault();
            controller.createArea({ name: elements.fnbAreaName.value, sort_order: 0 })
                .then(() => { elements.fnbAreaName.value = ''; })
                .catch(() => {});
        });
        elements.fnbTableForm.addEventListener('submit', event => {
            event.preventDefault();
            controller.createTable({
                area_id: Number(elements.fnbTableArea.value),
                name: elements.fnbTableName.value,
                sort_order: 0,
            }).then(() => { elements.fnbTableName.value = ''; }).catch(() => {});
        });
        elements.fnbDraftLines.addEventListener('input', event => {
            const row = event.target.closest('[data-line-id]');
            if (!row) return;
            controller.saveDraft({
                line_id: Number(row.dataset.lineId),
                quantity: Number(row.querySelector('[data-field="quantity"]').value),
                note: row.querySelector('[data-field="note"]').value,
            });
        });
        elements.fnbSetupDialog.addEventListener('close', () => elements.fnbSetupOpen.focus());
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) controller.loadFloor(false);
        });
        global.addEventListener('offline', () => live('fnb.state.offline'));
        global.addEventListener('online', () => controller.loadFloor(true));
        global.addEventListener('pagehide', () => controller.dispose(), { once: true });
        document.addEventListener('fselling:localechange', () => {
            renderFloor(controller.getState().floor);
            if (controller.getState().session) renderSession(controller.getState().session, controller.getDraft());
        });

        skeletons();
        loadShops().catch(error => {
            emptyPanel('fnb.state.poll_error', 'fnb.state.poll_error_empty');
            live('fnb.state.poll_error');
            showToast(error.message);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
        mount();
    }
})(typeof window === 'undefined' ? null : window);
