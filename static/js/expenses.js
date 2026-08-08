// K1: chi phí vận hành, lợi nhuận ròng và dòng tiền thực.
//
// Nạp SAU seller.js nên dùng đúng helper thật của trang: apiCall, escapeHtml,
// showToast, showCustomConfirm, dinhDangTienDoiSoat, dinhDangNhanNgayBieuDo, t.
//
// Nguyên tắc chữ nghĩa của màn này: KHÔNG dùng từ kế toán. Chủ shop bán lẻ
// không đọc "dồn tích", "phân bổ chi phí trả trước", "ghi nhận theo kỳ". Mọi
// câu giải thích phải nói thẳng bằng tiền và bằng tháng:
//   "Còn 20.000.000đ tiền nhà bạn đã trả trước, sẽ được tính dần cho 2 tháng sau."
(function (global) {
    'use strict';

    const CASHFLOW_UI_ROLES = Object.freeze(new Set(['SELLER', 'ADMIN']));
    const MAX_VND = 9_000_000_000_000_000;
    // Mã thao tác đang chờ: mất mạng giữa chừng thì lần bấm sau phải gửi lại
    // ĐÚNG mã cũ, nếu không server coi là khoản chi thứ hai và trừ két hai lần.
    const PENDING_KEY_PREFIX = 'fselling.expense.pending.v1';

    const state = {
        shopId: null,
        categories: [],
        templates: [],
        report: null,
        expenses: [],
        from: null,
        to: null,
        months: null,
        busy: false,
        pendingExpense: null,
        editingTemplateId: null,
        lastReminders: [],
        chart: null
    };

    const $ = id => document.getElementById(id);

    function canUse() {
        return CASHFLOW_UI_ROLES.has(MY_ROLE);
    }

    // ADMIN thao tác trên shop của người khác thì không có ca thu ngân ở đó, và
    // càng không nên rút tiền khỏi két của họ. Cùng luật với màn Nhập Hàng, và
    // cố ý lặp lại ở đây thay vì dựa vào purchasing.js đã chạy hay chưa.
    function availableMethods() {
        return MY_ROLE === 'ADMIN'
            ? ['TRANSFER', 'OUTSIDE']
            : ['CASH_SHIFT', 'TRANSFER', 'OUTSIDE'];
    }

    function applyPaymentMethodRoleVisibility() {
        const hideCash = MY_ROLE === 'ADMIN';
        const select = $('cfExpMethod');
        if (!select) return;
        select.querySelectorAll('[data-owner-cash]').forEach(option => {
            option.hidden = hideCash;
            option.disabled = hideCash;
            option.setAttribute('aria-hidden', hideCash ? 'true' : 'false');
        });
        if (hideCash && select.value === 'CASH_SHIFT') select.value = 'TRANSFER';
    }

    function selectedShopId() {
        const value = Number(typeof currentShopId === 'undefined' ? null : currentShopId);
        return Number.isInteger(value) && value > 0 ? value : null;
    }

    function money(value) {
        return dinhDangTienDoiSoat(Number(value) || 0);
    }

    // --- Ngày tháng ---------------------------------------------------------

    function todayISO() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    function parseISO(value) {
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
        if (!m) return null;
        return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    }

    function toISO(date) {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }

    // Cùng quy tắc với `expense_service.cong_thang` phía server: cùng ngày ở N
    // tháng sau, tháng thiếu ngày thì lùi về ngày cuối tháng. Bản JS này CHỈ để
    // hiện xem trước cho người dùng nhìn thấy mà bắt lỗi — con số được lưu luôn
    // do server tự tính lại từ số tháng, nên hai bên không thể lệch nhau.
    function addMonths(date, months) {
        const total = date.getMonth() + months;
        const year = date.getFullYear() + Math.floor(total / 12);
        const month = ((total % 12) + 12) % 12;
        const lastDay = new Date(year, month + 1, 0).getDate();
        return new Date(year, month, Math.min(date.getDate(), lastDay));
    }

    function prepaidEnd(startISO, months) {
        const start = parseISO(startISO);
        if (!start || !months) return null;
        const end = addMonths(start, months);
        end.setDate(end.getDate() - 1);
        return toISO(end);
    }

    function thangDep(value) {
        const m = /^(\d{4})-(\d{2})$/.exec(String(value || ''));
        return m ? `${Number(m[2])}/${m[1]}` : String(value || '');
    }

    function ngayDep(value) {
        const date = parseISO(value);
        if (!date) return String(value || '');
        return new Intl.DateTimeFormat(
            window.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
            { day: '2-digit', month: '2-digit', year: 'numeric' }
        ).format(date);
    }

    // --- Số tiền ------------------------------------------------------------

    function parseAmount(raw) {
        const digits = String(raw || '').replace(/[^\d]/g, '');
        if (!digits) return null;
        const value = Number(digits);
        if (!Number.isSafeInteger(value) || value <= 0 || value > MAX_VND) return null;
        return value;
    }

    // --- Mã thao tác chờ ----------------------------------------------------

    function pendingStorageKey() {
        return `${PENDING_KEY_PREFIX}.${state.shopId || 0}`;
    }

    function loadPending() {
        try {
            const raw = localStorage.getItem(pendingStorageKey());
            state.pendingExpense = raw ? JSON.parse(raw) : null;
        } catch (error) {
            state.pendingExpense = null;
        }
    }

    function savePending(payload) {
        state.pendingExpense = payload;
        try {
            if (payload) {
                localStorage.setItem(pendingStorageKey(), JSON.stringify(payload));
            } else {
                localStorage.removeItem(pendingStorageKey());
            }
        } catch (error) {
            /* localStorage đầy hoặc bị chặn: vẫn giữ được trong RAM của tab này */
        }
    }

    function newOperationId() {
        if (global.crypto?.randomUUID) return global.crypto.randomUUID().replace(/-/g, '');
        return `exp${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
    }

    // --- Nạp dữ liệu --------------------------------------------------------

    async function load() {
        if (!canUse()) return;
        const shopId = selectedShopId();
        if (!shopId) return;
        state.shopId = shopId;
        loadPending();
        if (!state.from && !state.to) applyQuickRange('this_month', { silent: true });
        await Promise.all([loadCategories(), loadTemplates()]);
        await Promise.all([loadReport(), loadExpenses(), loadReminders()]);
    }

    function rangeParams() {
        const parts = [];
        if (state.from) parts.push(`tu_ngay=${state.from}`);
        if (state.to) parts.push(`den_ngay=${state.to}`);
        return parts.length ? `?${parts.join('&')}` : '';
    }

    async function loadCategories() {
        try {
            const data = await apiCall(`/expense-categories/${state.shopId}`);
            state.categories = data.categories || [];
            renderCategoryOptions();
        } catch (error) {
            showToast(error.message);
        }
    }

    async function loadTemplates() {
        try {
            const data = await apiCall(`/expense-templates/${state.shopId}`);
            state.templates = data.templates || [];
            renderTemplates();
        } catch (error) {
            showToast(error.message);
        }
    }

    async function loadReport() {
        try {
            state.report = await apiCall(`/reports/cashflow/${state.shopId}${rangeParams()}`);
            renderReport();
        } catch (error) {
            showToast(error.message);
        }
    }

    async function loadExpenses() {
        try {
            const data = await apiCall(`/expenses/${state.shopId}${rangeParams()}`);
            state.expenses = data.expenses || [];
            renderExpenses();
        } catch (error) {
            showToast(error.message);
        }
    }

    async function loadReminders() {
        try {
            const data = await apiCall(`/expense-reminders/${state.shopId}`);
            renderReminders(data);
        } catch (error) {
            /* Nhắc nhở hỏng không được chặn cả màn hình */
        }
    }

    // --- Vẽ báo cáo ---------------------------------------------------------

    function lineItem(label, amount, extraClass = '') {
        return `<li class="${extraClass}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(money(amount))}</strong></li>`;
    }

    function renderReport() {
        const r = state.report;
        if (!r) return;

        const netProfit = $('cfNetProfit');
        if (netProfit) {
            netProfit.innerText = money(r.net_profit);
            netProfit.classList.toggle('cf-negative', Number(r.net_profit) < 0);
        }
        const netCash = $('cfNetCash');
        if (netCash) {
            const value = Number(r.net_cashflow) || 0;
            netCash.innerText = `${value > 0 ? '+' : ''}${money(value)}`;
            netCash.classList.toggle('cf-negative', value < 0);
        }

        const profitLines = $('cfProfitLines');
        if (profitLines) {
            const rows = [
                lineItem(t('seller.cashflow.line_gross_profit'), r.gross_profit)
            ];
            (r.expense_by_category || []).slice(0, 5).forEach(c => {
                rows.push(lineItem(
                    `− ${c.category_name || t('seller.cashflow.other_expense')}`,
                    c.amount,
                    'cf-line-out'
                ));
            });
            const shown = (r.expense_by_category || []).slice(0, 5)
                .reduce((sum, c) => sum + Number(c.amount || 0), 0);
            const rest = Number(r.operating_expense_total || 0) - shown;
            if (rest > 0) {
                rows.push(lineItem(`− ${t('seller.cashflow.other_expense')}`, rest, 'cf-line-out'));
            }
            profitLines.innerHTML = rows.join('');
        }

        // Trả trước còn lại. Không có dòng này thì tháng đóng tiền nhà 3 tháng
        // một lần, chủ shop thấy lãi đẹp và quên mất két đã bay 30 triệu.
        const prepaid = $('cfPrepaidNote');
        if (prepaid) {
            const remaining = Number(r.prepaid_remaining) || 0;
            if (remaining > 0) {
                const dau = (r.prepaid_details || [])[0];
                prepaid.innerHTML = escapeHtml(t('seller.cashflow.prepaid_note', {
                    amount: money(remaining),
                    name: (dau?.category_name || t('seller.cashflow.other_expense')).toLowerCase()
                }));
                prepaid.style.display = '';
            } else {
                prepaid.style.display = 'none';
            }
        }

        const inList = $('cfInLines');
        if (inList) {
            inList.innerHTML = (r.cash_in_breakdown || []).length
                ? (r.cash_in_breakdown || []).map(x => lineItem(x.label, x.amount)).join('')
                : `<li class="cf-empty-line">${escapeHtml(t('seller.cashflow.no_money_in'))}</li>`;
        }
        const outList = $('cfOutLines');
        if (outList) {
            outList.innerHTML = (r.cash_out_breakdown || []).length
                ? (r.cash_out_breakdown || []).map(x => lineItem(x.label, x.amount, 'cf-line-out')).join('')
                : `<li class="cf-empty-line">${escapeHtml(t('seller.cashflow.no_money_out'))}</li>`;
        }

        renderWhyDifferent(r);
        renderChart(r.chart || {});
    }

    // Câu giải thích vì sao lãi ròng khác dòng tiền. CỐ Ý không phải phép cân
    // đối khép kín — chỉ đọc ra các nguyên nhân lớn, mỗi con số đều tra ngược
    // về chứng từ được. Chỉ hiện khi hai con số thật sự lệch đáng kể.
    function renderWhyDifferent(r) {
        const box = $('cfWhyDifferent');
        if (!box) return;
        const profit = Number(r.net_profit) || 0;
        const cash = Number(r.net_cashflow) || 0;
        const notes = r.difference_notes || [];
        if (!notes.length || Math.abs(profit - cash) < 1000) {
            box.style.display = 'none';
            return;
        }
        const ly_do = notes
            .map(n => t('seller.cashflow.reason_line', {
                amount: money(n.amount),
                reason: n.label
            }))
            .join('; ');
        // "bạn lãi -3.881.347đ" là câu không ai nói. Số âm phải đổi thành TỪ
        // ("lỗ", "hụt đi") chứ không để dấu trừ đứng giữa câu văn xuôi.
        box.innerText = t('seller.cashflow.why_different', {
            profit: t(
                profit < 0 ? 'seller.cashflow.phrase_loss' : 'seller.cashflow.phrase_profit',
                { amount: money(Math.abs(profit)) }
            ),
            cash: t(
                cash < 0 ? 'seller.cashflow.phrase_cash_down' : 'seller.cashflow.phrase_cash_up',
                { amount: money(Math.abs(cash)) }
            ),
            reasons: ly_do
        });
        box.style.display = '';
    }

    function renderChart(chart) {
        const canvas = $('cashflowChart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (state.chart) state.chart.destroy();
        const labels = (chart.labels || []).map(dinhDangNhanNgayBieuDo);
        state.chart = new Chart(canvas.getContext('2d'), {
            data: {
                labels,
                datasets: [
                    {
                        type: 'bar',
                        label: t('seller.cashflow.money_in'),
                        data: chart.cash_in || [],
                        backgroundColor: 'rgba(34, 197, 94, 0.75)',
                        borderRadius: 4
                    },
                    {
                        type: 'bar',
                        label: t('seller.cashflow.money_out'),
                        data: chart.cash_out || [],
                        backgroundColor: 'rgba(239, 68, 68, 0.75)',
                        borderRadius: 4
                    },
                    {
                        type: 'line',
                        label: t('seller.cashflow.cumulative'),
                        data: chart.cumulative || [],
                        borderColor: '#3B82F6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        pointRadius: 2,
                        fill: false
                    }
                ]
            },
            options: {
                locale: window.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ${money(ctx.parsed.y)}`
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: value => dinhDangSoSeller(value, { notation: 'compact' })
                        }
                    }
                }
            }
        });
    }

    function renderReminders(data) {
        const box = $('cfReminders');
        const items = data?.items || [];
        // Giữ lại để nút "Ghi nhận" dựng sẵn form với đúng số còn thiếu.
        state.lastReminders = items;
        if (!box) return;
        if (!items.length) {
            box.style.display = 'none';
            return;
        }
        const rows = items.map(item => {
            const daTra = Number(item.paid_amount) || 0;
            const mo_ta = daTra > 0
                ? t('seller.cashflow.reminder_partial', {
                    name: item.name,
                    paid: money(daTra),
                    expected: money(item.expected_amount),
                    missing: money(item.missing_amount)
                })
                : t('seller.cashflow.reminder_full', {
                    name: item.name,
                    amount: money(item.missing_amount)
                });
            return `<li>
                <span>${escapeHtml(mo_ta)}</span>
                <button type="button" onclick="cfRecordTemplate(${item.template_id})">
                    <i class="ph ph-check"></i> ${escapeHtml(t('seller.cashflow.record_now'))}
                </button>
            </li>`;
        }).join('');
        box.innerHTML = `
            <h4><i class="ph ph-bell-ringing"></i> ${escapeHtml(t('seller.cashflow.reminder_title', { month: thangDep(data.month) }))}</h4>
            <ul>${rows}</ul>`;
        box.style.display = '';
    }

    function renderExpenses() {
        const body = $('cfExpenseRows');
        const empty = $('cfExpenseEmpty');
        if (!body) return;
        if (!state.expenses.length) {
            body.innerHTML = '';
            if (empty) empty.style.display = '';
            return;
        }
        if (empty) empty.style.display = 'none';
        body.innerHTML = state.expenses.map(e => {
            const nguon = t(`seller.cashflow.method_${String(e.method || '').toLowerCase()}`);
            const traTruoc = e.is_amortized
                ? `<div class="cf-muted">${escapeHtml(t('seller.cashflow.spread_note', {
                    from: ngayDep(e.amortize_start_date),
                    to: ngayDep(e.amortize_end_date)
                }))}</div>`
                : '';
            const nutGo = e.can_void
                ? `<button class="btn-outline" type="button" onclick="cfVoidExpense(${e.id})"><i class="ph ph-trash"></i></button>`
                : `<span class="cf-muted" title="${escapeHtml(t('seller.cashflow.cannot_void_hint'))}">${escapeHtml(t('seller.cashflow.cannot_void'))}</span>`;
            return `<tr>
                <td>${escapeHtml(ngayDep(e.expense_date))}</td>
                <td>${escapeHtml(e.category_name || '')}${traTruoc}</td>
                <td>${escapeHtml(money(e.amount))}</td>
                <td>${escapeHtml(nguon)}</td>
                <td>${escapeHtml(e.note || '')}</td>
                <td>${nutGo}</td>
            </tr>`;
        }).join('');
    }

    function renderCategoryOptions() {
        const dangDung = state.categories.filter(c => c.is_active);
        ['cfExpCategory', 'cfTplCategory'].forEach(id => {
            const select = $(id);
            if (!select) return;
            const cu = select.value;
            select.innerHTML = dangDung
                .map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
                .join('');
            if (cu && dangDung.some(c => String(c.id) === cu)) select.value = cu;
        });
        const chips = $('cfCategoryChips');
        if (chips) {
            chips.innerHTML = state.categories.map(c => `
                <span class="cf-chip ${c.is_active ? '' : 'cf-chip-off'}">
                    ${escapeHtml(c.name)}
                    <button type="button" onclick="cfToggleCategory(${c.id})" title="${escapeHtml(
                        c.is_active ? t('seller.cashflow.hide_category') : t('seller.cashflow.show_category')
                    )}"><i class="ph ${c.is_active ? 'ph-eye-slash' : 'ph-eye'}"></i></button>
                </span>`).join('');
        }
    }

    function renderTemplates() {
        const body = $('cfTemplateRows');
        if (!body) return;
        body.innerHTML = state.templates.map(tpl => `
            <tr class="${tpl.is_active ? '' : 'cf-row-off'}">
                <td>${escapeHtml(tpl.name)}</td>
                <td>${escapeHtml(tpl.category_name || '')}</td>
                <td>${escapeHtml(money(tpl.amount))}</td>
                <td>${escapeHtml(t('seller.cashflow.day_of_month', { day: tpl.day_of_month }))}</td>
                <td><button class="btn-outline" type="button" onclick="cfToggleTemplate(${tpl.id})">
                    ${escapeHtml(tpl.is_active ? t('seller.cashflow.stop') : t('seller.cashflow.resume'))}
                </button></td>
            </tr>`).join('');
    }

    // --- Bộ lọc kỳ ----------------------------------------------------------

    function applyQuickRange(kind, options = {}) {
        const now = new Date();
        let from;
        let to;
        if (kind === 'this_month') {
            from = new Date(now.getFullYear(), now.getMonth(), 1);
            to = new Date(now.getFullYear(), now.getMonth() + 1, 0);
        } else if (kind === 'last_month') {
            from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            to = new Date(now.getFullYear(), now.getMonth(), 0);
        } else {
            to = new Date(now);
            from = new Date(now);
            from.setDate(from.getDate() - 29);
        }
        state.from = toISO(from);
        state.to = toISO(to);
        if ($('cfFrom')) $('cfFrom').value = state.from;
        if ($('cfTo')) $('cfTo').value = state.to;
        if (!options.silent) refresh();
    }

    function applyRange() {
        const from = $('cfFrom')?.value || null;
        const to = $('cfTo')?.value || null;
        if (from && to && from > to) {
            showToast(t('seller.cashflow.bad_range'));
            return;
        }
        state.from = from;
        state.to = to;
        refresh();
    }

    async function refresh() {
        if (!state.shopId) return;
        await Promise.all([loadReport(), loadExpenses(), loadReminders()]);
    }

    // --- Form ghi chi phí ---------------------------------------------------

    function openExpenseForm(template = null) {
        if (!state.shopId) {
            showToast(t('seller.cashflow.choose_shop_first'));
            return;
        }
        if ($('cfExpAmount')) $('cfExpAmount').value = template ? String(template.missing_amount || '') : '';
        if ($('cfExpDate')) $('cfExpDate').value = todayISO();
        if ($('cfExpStart')) $('cfExpStart').value = todayISO();
        if ($('cfExpNote')) $('cfExpNote').value = '';
        if ($('cfExpPrepaid')) $('cfExpPrepaid').checked = false;
        state.months = null;
        state.editingTemplateId = template ? template.template_id : null;
        if (template && $('cfExpCategory')) $('cfExpCategory').value = String(template.category_id);
        const title = $('cfExpenseTitle');
        if (title) {
            title.innerText = template
                ? t('seller.cashflow.record_template', { name: template.name })
                : t('seller.cashflow.add_expense');
        }
        // Còn mã thao tác chờ từ lần mất mạng trước: phải gửi lại đúng mã đó.
        const notice = $('cfExpenseRetryNotice');
        if (notice) notice.style.display = state.pendingExpense ? '' : 'none';
        applyPaymentMethodRoleVisibility();
        updatePreview();
        if ($('cfExpenseModal')) $('cfExpenseModal').style.display = 'flex';
    }

    function closeExpenseForm() {
        if ($('cfExpenseModal')) $('cfExpenseModal').style.display = 'none';
        state.editingTemplateId = null;
    }

    function setMonths(months) {
        state.months = months;
        if ($('cfExpPrepaid')) $('cfExpPrepaid').checked = true;
        document.querySelectorAll('[data-cf-months]').forEach(btn => {
            btn.classList.toggle('cf-month-active', Number(btn.dataset.cfMonths) === months);
        });
        updatePreview();
    }

    function updatePreview() {
        const bat = $('cfExpPrepaid')?.checked === true;
        const box = $('cfExpPrepaidBox');
        if (box) box.style.display = bat ? '' : 'none';
        if (bat && !state.months) setMonthsSilently(1);

        const amount = parseAmount($('cfExpAmount')?.value);
        const words = $('cfExpAmountWords');
        if (words) {
            words.innerText = amount ? money(amount) : '';
        }

        const method = $('cfExpMethod')?.value;
        const hint = $('cfExpMethodHint');
        if (hint) hint.innerText = t(`seller.cashflow.method_hint_${String(method || '').toLowerCase()}`);
        const noteHint = $('cfExpNoteHint');
        if (noteHint) {
            noteHint.innerText = method === 'OUTSIDE'
                ? t('seller.cashflow.note_required')
                : '';
        }

        const preview = $('cfExpPrepaidPreview');
        if (!preview) return;
        if (!bat || !state.months) {
            preview.innerText = '';
            return;
        }
        const start = $('cfExpStart')?.value || $('cfExpDate')?.value || todayISO();
        const end = prepaidEnd(start, state.months);
        if (!end) {
            preview.innerText = '';
            return;
        }
        const perMonth = amount ? Math.round(amount / state.months) : 0;
        preview.innerText = t('seller.cashflow.prepaid_preview', {
            from: ngayDep(start),
            to: ngayDep(end),
            perMonth: money(perMonth)
        });
    }

    function setMonthsSilently(months) {
        state.months = months;
        document.querySelectorAll('[data-cf-months]').forEach(btn => {
            btn.classList.toggle('cf-month-active', Number(btn.dataset.cfMonths) === months);
        });
    }

    async function submitExpense() {
        if (state.busy) return;
        const amount = parseAmount($('cfExpAmount')?.value);
        if (!amount) {
            showToast(t('seller.cashflow.bad_amount'));
            return;
        }
        const method = $('cfExpMethod')?.value;
        if (!availableMethods().includes(method)) {
            applyPaymentMethodRoleVisibility();
            showToast(t('seller.cashflow.method_not_allowed'));
            return;
        }
        const note = ($('cfExpNote')?.value || '').trim();
        if (method === 'OUTSIDE' && !note) {
            showToast(t('seller.cashflow.note_required'));
            return;
        }
        const categoryId = Number($('cfExpCategory')?.value);
        if (!Number.isInteger(categoryId) || categoryId <= 0) {
            showToast(t('seller.cashflow.choose_category'));
            return;
        }

        const prepaid = $('cfExpPrepaid')?.checked === true;
        const payload = {
            category_id: categoryId,
            amount,
            expense_date: $('cfExpDate')?.value || todayISO(),
            method,
            note: note || null,
            // Mã thao tác giữ nguyên khi thử lại: đây là thứ chặn "bấm hai lần
            // trừ két hai lần" khi mạng chập chờn.
            operation_id: state.pendingExpense?.operation_id || newOperationId()
        };
        if (state.editingTemplateId) payload.template_id = state.editingTemplateId;
        if (prepaid && state.months) {
            payload.amortize_months = state.months;
            const start = $('cfExpStart')?.value;
            if (start) payload.amortize_start_date = start;
        }

        state.busy = true;
        const button = $('cfExpenseSubmit');
        if (button) button.disabled = true;
        savePending({ operation_id: payload.operation_id });
        try {
            await apiCall(`/expenses/${state.shopId}`, 'POST', payload);
            savePending(null);
            closeExpenseForm();
            showToast(t('seller.cashflow.saved'));
            await refresh();
        } catch (error) {
            showToast(error.message);
            const notice = $('cfExpenseRetryNotice');
            if (notice) notice.style.display = '';
        } finally {
            state.busy = false;
            if (button) button.disabled = false;
        }
    }

    function recordTemplate(templateId) {
        const item = (state.lastReminders || []).find(r => r.template_id === templateId);
        openExpenseForm(item || null);
    }

    async function voidExpense(expenseId) {
        const khoan = state.expenses.find(e => e.id === expenseId);
        if (!khoan) return;
        showCustomConfirm(
            t('seller.cashflow.void_title'),
            t('seller.cashflow.void_message', {
                amount: money(khoan.amount),
                date: ngayDep(khoan.expense_date)
            }),
            async () => {
                try {
                    await apiCall(`/expenses/${state.shopId}/${expenseId}/void`, 'POST');
                    showToast(t('seller.cashflow.voided'));
                    await refresh();
                } catch (error) {
                    showToast(error.message);
                }
            },
            t('seller.cashflow.void_confirm')
        );
    }

    // --- Cài đặt: mẫu + danh mục -------------------------------------------

    function openSettings() {
        if (!state.shopId) {
            showToast(t('seller.cashflow.choose_shop_first'));
            return;
        }
        if ($('cfSettingsModal')) $('cfSettingsModal').style.display = 'flex';
    }

    function closeSettings() {
        if ($('cfSettingsModal')) $('cfSettingsModal').style.display = 'none';
    }

    async function addTemplate() {
        const name = ($('cfTplName')?.value || '').trim();
        const amount = parseAmount($('cfTplAmount')?.value);
        const categoryId = Number($('cfTplCategory')?.value);
        const day = Number($('cfTplDay')?.value || 1);
        if (!amount) {
            showToast(t('seller.cashflow.bad_amount'));
            return;
        }
        if (!Number.isInteger(categoryId) || categoryId <= 0) {
            showToast(t('seller.cashflow.choose_category'));
            return;
        }
        try {
            await apiCall(`/expense-templates/${state.shopId}`, 'POST', {
                category_id: categoryId,
                name: name || null,
                amount,
                day_of_month: Math.min(Math.max(day, 1), 31)
            });
            if ($('cfTplName')) $('cfTplName').value = '';
            if ($('cfTplAmount')) $('cfTplAmount').value = '';
            await loadTemplates();
            await loadReminders();
            showToast(t('seller.cashflow.template_added'));
        } catch (error) {
            showToast(error.message);
        }
    }

    async function toggleTemplate(templateId) {
        const tpl = state.templates.find(x => x.id === templateId);
        if (!tpl) return;
        try {
            await apiCall(`/expense-templates/${state.shopId}/${templateId}`, 'PUT', {
                is_active: !tpl.is_active
            });
            await loadTemplates();
            await loadReminders();
        } catch (error) {
            showToast(error.message);
        }
    }

    async function addCategory() {
        const name = ($('cfNewCategory')?.value || '').trim();
        if (!name) return;
        try {
            await apiCall(`/expense-categories/${state.shopId}`, 'POST', { name });
            if ($('cfNewCategory')) $('cfNewCategory').value = '';
            await loadCategories();
            showToast(t('seller.cashflow.category_added'));
        } catch (error) {
            showToast(error.message);
        }
    }

    async function toggleCategory(categoryId) {
        const cat = state.categories.find(c => c.id === categoryId);
        if (!cat) return;
        try {
            await apiCall(`/expense-categories/${state.shopId}/${categoryId}`, 'PUT', {
                is_active: !cat.is_active
            });
            await loadCategories();
        } catch (error) {
            showToast(error.message);
        }
    }

    function resetForShopChange() {
        state.shopId = null;
        state.categories = [];
        state.templates = [];
        state.expenses = [];
        state.report = null;
        state.lastReminders = [];
        if (state.chart) {
            state.chart.destroy();
            state.chart = null;
        }
    }

    Object.assign(global, {
        cfApplyRange: applyRange,
        cfQuickRange: applyQuickRange,
        cfOpenExpenseForm: () => openExpenseForm(null),
        cfCloseExpenseForm: closeExpenseForm,
        cfSetMonths: setMonths,
        cfUpdatePreview: updatePreview,
        cfSubmitExpense: submitExpense,
        cfVoidExpense: voidExpense,
        cfRecordTemplate: recordTemplate,
        cfOpenSettings: openSettings,
        cfCloseSettings: closeSettings,
        cfAddTemplate: addTemplate,
        cfToggleTemplate: toggleTemplate,
        cfAddCategory: addCategory,
        cfToggleCategory: toggleCategory
    });

    global.FSellingExpenses = Object.freeze({
        load,
        resetForShopChange
    });
})(window);
