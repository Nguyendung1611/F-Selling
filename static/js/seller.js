// Chủ shop (SELLER) và nhân viên (STAFF) đều dùng trang này. Vai trò quyết định
// những gì được hiển thị (xem applyRoleUI ở cuối file).
const MY_ROLE = localStorage.getItem('role');
if(MY_ROLE !== 'SELLER' && MY_ROLE !== 'STAFF') redirectToLogin();
const MY_STAFF_ROLE = MY_ROLE === 'STAFF'
    ? (localStorage.getItem('staff_role') || 'MANAGER').toUpperCase()
    : null;
const STAFF_UI_PERMISSIONS = Object.freeze({
    CASHIER: new Set(['SALE', 'CUSTOMER']),
    WAREHOUSE: new Set(['INVENTORY']),
    MANAGER: new Set(['SALE', 'INVENTORY', 'CUSTOMER', 'REPORT', 'VOUCHER', 'RECONCILIATION'])
});

function coQuyenNhanVien(permission) {
    if (MY_ROLE !== 'STAFF') return true;
    return STAFF_UI_PERMISSIONS[MY_STAFF_ROLE]?.has(permission) === true;
}

// Giá vốn và lãi chỉ dành cho chủ cửa hàng, kể cả nhân viên MANAGER (đang xem
// được doanh thu) cũng không thấy. Đây CHỈ là lớp giao diện cho gọn mắt - server
// mới là chỗ chặn thật (has_cost_visibility trong dependencies.py). Đừng bao giờ
// coi cờ này là biện pháp bảo mật: sửa localStorage là qua được.
const XEM_DUOC_GIA_VON = MY_ROLE === 'SELLER';

// Giá vốn theo product_id, nạp riêng qua endpoint chỉ chủ shop gọi được. Danh
// sách sản phẩm mở cho cả nhân viên nên KHÔNG kèm giá vốn - phải ghép ở đây.
let giaVonTheoSanPham = {};
let soSanPhamChuaKhaiGiaVon = 0;

const BANKS = [
    { code: 'VCB', label: 'Vietcombank (VCB)' },
    { code: 'ACB', label: 'ACB' },
    { code: 'BIDV', label: 'BIDV' },
    { code: 'CTG', label: 'VietinBank (CTG)' },
    { code: 'MB', label: 'MBBank (MB)' },
    { code: 'TCB', label: 'Techcombank (TCB)' },
    { code: 'TPB', label: 'TPBank (TPB)' },
    { code: 'VPB', label: 'VPBank (VPB)' },
    { code: 'HDB', label: 'HDBank (HDB)' },
    { code: 'VIB', label: 'VIB' },
    { code: 'OCB', label: 'OCB' },
    { code: 'SCB', label: 'SCB' },
    { code: 'SHB', label: 'SHB' },
    { code: 'EIB', label: 'Eximbank (EIB)' },
    { code: 'MSB', label: 'MSB' },
    { code: 'NCB', label: 'NCB' },
    { code: 'ABB', label: 'ABBank (ABB)' },
    { code: 'STB', label: 'Sacombank (STB)' }
];

let allShops = [];
let currentShopId = null;
let editShopId = null; // null = create mode, id = edit mode
let dashboardShopId = null;
let chartInstance = null;
let pieChartInstance = null;
let doiSoatShopId = null;
let trangDoiSoat = 1;
const DOI_SOAT_MOI_TRANG = 50;
let doiSoatRequestId = 0;
let doiSoatBadgeCount = 0;
let refundOrderId = null;
let refundDueAmount = 0;
let refundOperationId = null;
let dangLuuHoanTien = false;
let refundReason = null;
let currentCategories = [];
let currentCategoriesShopId = null;
let currentProductsShopId = null;
let currentVouchersShopId = null;
let currentStaff = [];
let currentStaffShopId = null;
let openOrderDetailId = null;
let openCustomerHistoryId = null;
let currentCustomersShopId = null;
let currentCustomersQuery = '';
let dashboardOrdersCache = null;
let dashboardStatsCache = null;
let shiftHistoryCache = null;
let reconciliationCache = null;
let orderDetailCache = null;
let customerHistoryCache = null;
let customerHistoryShopId = null;
let currentShopGeneration = 0;
let loadedCurrentShopId = null;
let categoriesRequestId = 0;
let productsRequestId = 0;
let vouchersRequestId = 0;
let dashboardRequestId = 0;
let shiftHistoryRequestId = 0;
let doiSoatBadgeRequestId = 0;
let staffRequestId = 0;
let customersRequestId = 0;
let customerHistoryRequestId = 0;

function dinhDangSoSeller(value, options = {}) {
    return window.FSellingI18n?.formatNumber(value, options)
        ?? Number(value || 0).toLocaleString('vi-VN', options);
}

function dinhDangNhanNgayBieuDo(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    if (!match) return String(value || '');
    const date = new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3])
    );
    return new Intl.DateTimeFormat(
        window.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
        { day: '2-digit', month: 'short' }
    ).format(date);
}

function capNhatNhanNut(selector, key) {
    const label = document.querySelector(selector);
    if (label) label.textContent = t(key);
}

function cacheThuocShop(cacheShopId, shopId) {
    return Number.isInteger(Number(shopId))
        && Number(cacheShopId) === Number(shopId);
}

function damBaoCacheShopHienTai(cacheShopId) {
    if (cacheThuocShop(cacheShopId, currentShopId)) return true;
    showToast(t('common.loading'));
    return false;
}

function shopDangChon(selectorId) {
    const value = Number(document.getElementById(selectorId)?.value);
    return Number.isInteger(value) && value > 0 ? value : null;
}

function damBaoCacheShopTrongSelector(cacheShopId, selectorId) {
    const selectedShopId = shopDangChon(selectorId);
    if (selectedShopId && cacheThuocShop(cacheShopId, selectedShopId)) {
        return selectedShopId;
    }
    showToast(t('common.loading'));
    return null;
}

function xoaDuLieuShopCuKhoiGiaoDien() {
    currentCategories = [];
    currentCategoriesShopId = null;
    currentProducts = [];
    currentProductsShopId = null;
    currentVouchers = [];
    currentVouchersShopId = null;
    categoriesRequestId += 1;
    productsRequestId += 1;
    vouchersRequestId += 1;

    cancelEditCategory();
    cancelEditProduct();
    cancelEditVoucher();
    kkXoaHet();

    const catSelect = document.getElementById('catSelect');
    if (catSelect) catSelect.innerHTML = '';
    const filterCatSelect = document.getElementById('filterCatSelect');
    if (filterCatSelect) {
        filterCatSelect.innerHTML = `<option value="">${escapeHtml(t('seller.filters.all'))}</option>`;
    }
    const categoryTableBody = document.getElementById('categoryTableBody');
    if (categoryTableBody) categoryTableBody.innerHTML = '';
    const productList = document.getElementById('prodList');
    if (productList) productList.innerHTML = '';
    const voucherList = document.getElementById('voucherList');
    if (voucherList) voucherList.innerHTML = '';
}

function batDauDungShopHienTai() {
    const shopId = Number(currentShopId);
    if (!Number.isInteger(shopId) || shopId <= 0) return false;
    if (loadedCurrentShopId !== shopId) {
        loadedCurrentShopId = shopId;
        currentShopGeneration += 1;
        xoaDuLieuShopCuKhoiGiaoDien();
    }
    return true;
}

function renderBankOptions() {
    const bankSelect = document.getElementById('bankCode');
    if (!bankSelect) return;
    const selected = bankSelect.value;
    bankSelect.innerHTML = `<option value="" disabled>${escapeHtml(t('seller.shops.choose_bank'))}</option>` +
        BANKS.map(bank => `<option value="${bank.code}">${bank.label}</option>`).join('');
    bankSelect.value = BANKS.some(bank => bank.code === selected) ? selected : '';
}

function switchTab(tabId, buttonEl = null) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn[data-main-tab]').forEach(el => el.classList.remove('active'));
    const tab = document.getElementById(tabId);
    if (!tab) return;
    tab.classList.add('active');
    const nutTab = buttonEl || document.querySelector(`.tab-btn[data-main-tab="${tabId}"]`);
    if (nutTab) nutTab.classList.add('active');
    if (tabId === 'reconciliation') loadDoiSoat();
}

// Live Preview Logic
document.getElementById('shopName').addEventListener('input', e => {
    document.getElementById('previewCardName').innerText =
        e.target.value || t('seller.shops.preview_name');
});
document.getElementById('shopTaxCode').addEventListener('input', e => {
    document.getElementById('previewCardTaxCode').innerText =
        e.target.value || t('seller.shops.preview_empty');
});
document.getElementById('shopAddress').addEventListener('input', e => {
    document.getElementById('previewCardAddress').innerText =
        e.target.value || t('seller.shops.preview_empty');
});

async function init() {
    try {
        allShops = await apiCall('/shops');
        renderShopsList(); // Cho phần cài đặt
        // Danh sách nhân viên chỉ dành cho chủ shop (nhân viên gọi sẽ bị 404).
        if (MY_ROLE !== 'STAFF') renderStaffShopOptions();
        if (coQuyenNhanVien('CUSTOMER')) renderCustomerShopOptions();

        if(allShops.length === 0) {
            document.getElementById('dashboardContent').style.display = 'none';
            document.getElementById('noShopMsg').style.display = 'block';
            if (MY_ROLE !== 'STAFF') openCreateShopForm();
        } else {
            // Mặc định nạp dữ liệu cho shop đầu tiên nếu có currentShopId
            let savedId = localStorage.getItem('currentShopId');
            if(savedId && allShops.find(s => s.id == savedId)) {
                currentShopId = parseInt(savedId);
            } else {
                currentShopId = allShops[0].id;
                localStorage.setItem('currentShopId', currentShopId);
            }
            dashboardShopId = currentShopId; // Initialize dashboardShopId
            renderShopSelectors(); // Call AFTER currentShopId and dashboardShopId are set
            loadDataForCurrentShop();
        }
    } catch(e) {
        showToast(e instanceof TypeError ? t('common.network_error') : e.message);
    }

    renderBankOptions();
}

function renderShopSelectors() {
    const dashList = document.getElementById('dashShopList');
    const whList = document.getElementById('whShopList');
    const vouList = document.getElementById('vouShopList');
    const posList = document.getElementById('posShopList');
    const doiSoatSelect = document.getElementById('doiSoatShopSelect');
    
    dashList.innerHTML = '';
    if(whList) whList.innerHTML = '';
    if(vouList) vouList.innerHTML = '';
    if(posList) posList.innerHTML = '';

    if (doiSoatSelect) {
        if (!doiSoatShopId || !allShops.some(s => s.id === doiSoatShopId)) {
            doiSoatShopId = currentShopId || allShops[0]?.id || null;
        }
        doiSoatSelect.innerHTML = allShops.map(s =>
            `<option value="${s.id}">${escapeHtml(s.name)}</option>`
        ).join('');
        if (doiSoatShopId) doiSoatSelect.value = String(doiSoatShopId);
    }
    
    allShops.forEach(s => {
        // Dashboard (Thống Kê)
        const btn1 = document.createElement('button');
        btn1.className = dashboardShopId === s.id ? 'btn-primary' : 'btn-outline';
        btn1.innerText = s.name;
        btn1.onclick = () => loadDashboardShop(s.id);
        dashList.appendChild(btn1);

        // Warehouse
        if(whList) {
            const btn2 = document.createElement('button');
            btn2.className = currentShopId === s.id ? 'btn-primary' : 'btn-outline';
            btn2.innerText = s.name;
            btn2.onclick = () => changeShop(s.id);
            whList.appendChild(btn2);
        }

        // Kiểm kê
        const kkList = document.getElementById('kkShopList');
        if(kkList) {
            const btnKK = document.createElement('button');
            btnKK.className = currentShopId === s.id ? 'btn-primary' : 'btn-outline';
            btnKK.innerText = s.name;
            btnKK.onclick = () => changeShop(s.id);
            kkList.appendChild(btnKK);
        }

        // Voucher
        if(vouList) {
            const btn3 = document.createElement('button');
            btn3.className = currentShopId === s.id ? 'btn-primary' : 'btn-outline';
            btn3.innerText = s.name;
            btn3.onclick = () => changeShop(s.id);
            vouList.appendChild(btn3);
        }
        
        // POS
        if(posList) {
            posList.innerHTML += `<button style="width: 100%; padding: 1rem; text-align: left; display: flex; align-items: center; gap: 0.5rem;" onclick="goToPOS(${s.id})"><i class="ph ph-storefront"></i> ${escapeHtml(s.name)}</button>`;
        }
    });
}

function openPosShopSelector() {
    if(allShops.length === 0) return showToast(t('seller.shops.create_first'));
    document.getElementById('posModal').style.display = 'flex';
}

function renderDashboardOrders(id, res) {
    const shop = allShops.find(s => s.id === id);
    document.getElementById('currentShopName').innerText = shop ? shop.name : '';

    const tbody = document.getElementById('orderList');
    tbody.innerHTML = '';
    (res.orders || []).forEach(o => {
        const hienThi = window.moTaTrangThaiDon(o.status);
        const dt = dinhDangNgayGio(o.date);
        tbody.innerHTML += `<tr>
            <td><strong>#${o.id}</strong></td>
            <td>${dt}</td>
            <td>${escapeHtml(o.cashier_username || '—')}${o.shift_id ? `<br><small style="color:var(--text-muted);">${escapeHtml(t('seller.dashboard.shift_number', { id: o.shift_id }))}</small>` : ''}</td>
            <td>${dinhDangTienDoiSoat(o.total)}</td>
            <td style="color: ${hienThi.color}; font-weight: 600;">${escapeHtml(hienThi.label)}</td>
            <td><button class="btn-outline" style="padding: 0.25rem 0.6rem; font-size: 0.8rem;" onclick="xemChiTietDon(${o.id})">${escapeHtml(t('seller.actions.view'))}</button></td>
        </tr>`;
    });
    capNhatDieuKhienTrang(res);

    const dashList = document.getElementById('dashShopList');
    if (dashList) {
        Array.from(dashList.children).forEach(btn => {
            btn.className = shop && btn.innerText === shop.name
                ? 'btn-primary'
                : 'btn-outline';
        });
    }
    document.getElementById('dashboardContent').style.display = 'block';
}

/** Thẻ lãi gộp trên dashboard.
 *
 *  Server BỎ HẲN nhóm field này khi người gọi không được xem, nên điều kiện là
 *  "field có mặt hay không" chứ không phải giá trị của nó - lãi bằng 0 là một
 *  con số hợp lệ (bán đúng bằng giá vốn) và vẫn phải hiện ra.
 *
 *  Phần đơn chưa đủ giá vốn LUÔN được nói ra khi có. Im lặng ở đây nghĩa là
 *  chủ shop nhìn một con số lãi thấp hơn thực tế mà tưởng đó là toàn bộ. */
function veTheLaiGop(stats) {
    const card = document.getElementById('statProfitCard');
    if (!card) return;
    if (stats.gross_profit === undefined) {
        card.style.display = 'none';
        return;
    }
    card.style.display = '';
    document.getElementById('statProfit').innerText =
        dinhDangTienDoiSoat(stats.gross_profit);

    const ghiChu = document.getElementById('statProfitNote');
    if (!ghiChu) return;
    const phan = [];
    if (stats.gross_margin !== null && stats.gross_margin !== undefined) {
        phan.push(t('seller.dashboard.gross_margin', {
            percent: dinhDangSoSeller(stats.gross_margin, {
                maximumFractionDigits: 1
            })
        }));
    }
    if (stats.orders_missing_cost) {
        phan.push(t('seller.dashboard.orders_missing_cost', {
            count: stats.orders_missing_cost,
            formattedCount: dinhDangSoSeller(stats.orders_missing_cost),
            amount: dinhDangTienDoiSoat(stats.revenue_missing_cost || 0)
        }));
    }
    ghiChu.innerText = phan.join(' · ');
    ghiChu.style.color = stats.orders_missing_cost ? '#B45309' : '#64748B';
}

function renderDashboardStats(stats) {
    document.getElementById('statRev').innerText = dinhDangTienDoiSoat(stats.total_revenue);
    document.getElementById('statOrders').innerText = dinhDangSoSeller(stats.total_orders);
    document.getElementById('statSold').innerText = dinhDangSoSeller(stats.total_sold);
    veTheLaiGop(stats);

    const pieCtx = document.getElementById('productPieChart').getContext('2d');
    if (pieChartInstance) pieChartInstance.destroy();

    const pieLabels = (stats.top_products || []).map(p => p.name);
    const pieData = (stats.top_products || []).map(p => p.qty);
    const pieColors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];

    pieChartInstance = new Chart(pieCtx, {
        type: 'doughnut',
        data: {
            labels: pieLabels.length ? pieLabels : [t('seller.dashboard.no_chart_data')],
            datasets: [{
                data: pieData.length ? pieData : [1],
                backgroundColor: pieData.length ? pieColors : ['#E2E8F0'],
                borderWidth: 0
            }]
        },
        options: {
            locale: window.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { boxWidth: 12 } }
            }
        }
    });

    const ctx = document.getElementById('revenueChart').getContext('2d');
    if (chartInstance) chartInstance.destroy();
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: (stats.trend_labels || []).map(dinhDangNhanNgayBieuDo),
            datasets: [{
                label: t('seller.dashboard.revenue_vnd'),
                data: stats.trend_data || [],
                borderColor: '#3B82F6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            locale: window.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
}

function khoaDashboardOrders(shopId, query) {
    return `${shopId}|${query}`;
}

function khoaDashboardStats(shopId, query) {
    return `${shopId}|${query}`;
}

async function loadDashboardShop(id) {
    const shopId = Number(id);
    if (!Number.isInteger(shopId) || !allShops.some(shop => shop.id === shopId)) return;
    dashboardShopId = shopId;
    const ordersQuery = chuoiThamSoDon();
    const statsQuery = chuoiThamSoNgay();
    const ordersKey = khoaDashboardOrders(shopId, ordersQuery);
    const statsKey = khoaDashboardStats(shopId, statsQuery);
    const requestId = ++dashboardRequestId;
    // Hủy ngay cả request lịch sử ca cũ trước khi request dashboard mới hoàn tất.
    shiftHistoryRequestId += 1;
    try {
        const res = await apiCall(`/dashboard/seller/${shopId}${ordersQuery}`);
        if (
            requestId !== dashboardRequestId
            || shopId !== dashboardShopId
            || ordersKey !== khoaDashboardOrders(shopId, chuoiThamSoDon())
        ) return;
        if (!doiSoatShopId) doiSoatShopId = shopId;
        if (doiSoatShopId === shopId) {
            doiSoatBadgeRequestId += 1;
            capNhatBadgeDoiSoat(res.reconciliation_count || 0);
        }
        dashboardOrdersCache = { shopId, key: ordersKey, data: res };
        renderDashboardOrders(shopId, res);
        loadShiftHistory(shopId);

        const stats = await apiCall(`/shops/${shopId}/stats${statsQuery}`);
        if (
            requestId !== dashboardRequestId
            || shopId !== dashboardShopId
            || statsKey !== khoaDashboardStats(shopId, chuoiThamSoNgay())
        ) return;
        dashboardStatsCache = { shopId, key: statsKey, data: stats };
        renderDashboardStats(stats);
    } catch(e) {
        if (requestId === dashboardRequestId && shopId === dashboardShopId) {
            showToast(e.message);
        }
    }
}

function renderShiftHistory(data) {
    const tbody = document.getElementById('shiftHistoryList');
    if (!tbody) return;
    if (!data.items.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="color:var(--text-muted);">${escapeHtml(t('seller.shifts.empty'))}</td></tr>`;
        return;
    }
    tbody.innerHTML = data.items.map(shift => {
        const dangMo = shift.status === 'OPEN';
        const variance = Number(shift.variance_amount);
        const varianceText = dangMo || !Number.isFinite(variance)
            ? '—'
            : `${variance > 0 ? '+' : ''}${dinhDangTienDoiSoat(variance)}`;
        const varianceColor = variance < 0
            ? '#EF4444'
            : (variance > 0 ? '#F59E0B' : 'var(--success)');
        return `<tr>
            <td><strong>#${shift.id}</strong><br><small style="color:${dangMo ? '#10B981' : 'var(--text-muted)'};">${escapeHtml(t(dangMo ? 'seller.status.open' : 'seller.status.closed'))}</small></td>
            <td>${escapeHtml(shift.opened_by_username || '—')}</td>
            <td>${dinhDangNgayGio(shift.opened_at)}</td>
            <td>${dangMo ? '—' : dinhDangNgayGio(shift.closed_at)}</td>
            <td>${dinhDangTienDoiSoat(shift.expected_cash_amount || 0)}</td>
            <td>${dangMo || shift.counted_cash_amount == null ? '—' : dinhDangTienDoiSoat(shift.counted_cash_amount)}</td>
            <td style="font-weight:700; color:${varianceColor};">${varianceText}</td>
        </tr>`;
    }).join('');
}

async function loadShiftHistory(shopId) {
    const tbody = document.getElementById('shiftHistoryList');
    if (!tbody || !shopId) return;
    const requestId = ++shiftHistoryRequestId;
    tbody.innerHTML = `<tr><td colspan="7" style="color:var(--text-muted);">${escapeHtml(t('common.loading'))}</td></tr>`;
    try {
        const data = await apiCall(`/shifts/history/${shopId}?page=1&per_page=10`);
        // Dashboard và kho có thể đang chọn hai shop khác nhau. Chỉ bỏ response
        // cũ khi người dùng đã chuyển shop thống kê trong lúc request đang chạy.
        if (shopId !== dashboardShopId) return;
        if (requestId !== shiftHistoryRequestId) return;
        shiftHistoryCache = { shopId, data };
        renderShiftHistory(data);
    } catch (e) {
        if (requestId === shiftHistoryRequestId && shopId === dashboardShopId) {
            tbody.innerHTML = `<tr><td colspan="7" style="color:#EF4444;">${escapeHtml(e.message || t('seller.shifts.load_error'))}</td></tr>`;
        }
    }
}

// ===== D4: danh sách đơn cần đối soát =====

function dinhDangTienDoiSoat(value) {
    return window.FSellingI18n?.formatMoney(value)
        ?? `${Math.round(Number(value) || 0).toLocaleString('vi-VN')} ₫`;
}

function thongTinLoaiDoiSoat(reason) {
    const loai = {
        UNDERPAID: {
            title: t('seller.reconciliation.underpaid_title'),
            cardClass: 'underpaid',
            stateClass: 'waiting',
            stateLabel: t('seller.reconciliation.underpaid_state'),
            note: t('seller.reconciliation.underpaid_note')
        },
        OVERPAID: {
            title: t('seller.reconciliation.overpaid_title'),
            cardClass: 'overpaid',
            stateClass: 'invoice',
            stateLabel: t('seller.reconciliation.overpaid_state'),
            note: t('seller.reconciliation.overpaid_note')
        },
        LATE_PAYMENT: {
            title: t('seller.reconciliation.late_title'),
            cardClass: 'late-payment',
            stateClass: 'cancelled',
            stateLabel: t('seller.reconciliation.late_state'),
            note: t('seller.reconciliation.late_note')
        },
        LEGACY_REVIEW: {
            title: t('seller.reconciliation.legacy_title'),
            cardClass: 'legacy-review',
            stateClass: 'review',
            stateLabel: t('seller.reconciliation.review_state'),
            note: t('seller.reconciliation.legacy_note')
        }
    };
    return loai[reason] || {
        title: reason
            ? t('seller.reconciliation.unknown_title_reason', { reason })
            : t('seller.reconciliation.unknown_title'),
        cardClass: 'legacy-review',
        stateClass: 'review',
        stateLabel: t('seller.reconciliation.review_state'),
        note: t('seller.reconciliation.unknown_note')
    };
}

function capNhatBadgeDoiSoat(count) {
    const badge = document.getElementById('doiSoatBadge');
    if (!badge) return;
    const soLuong = Math.max(0, Number.parseInt(count, 10) || 0);
    doiSoatBadgeCount = soLuong;
    badge.innerText = soLuong > 99 ? '99+' : String(soLuong);
    badge.style.display = soLuong > 0 ? 'inline-flex' : 'none';
    badge.title = t('seller.reconciliation.badge_title', {
        count: soLuong,
        formattedCount: dinhDangSoSeller(soLuong)
    });
}

function chonShopDoiSoat(value) {
    const id = Number.parseInt(value, 10);
    if (!Number.isInteger(id) || !allShops.some(s => s.id === id)) return;
    doiSoatShopId = id;
    doiSoatBadgeRequestId += 1;
    trangDoiSoat = 1;
    loadDoiSoat();
}

function renderDoiSoatKhongCoShop() {
    const list = document.getElementById('doiSoatList');
    const loading = document.getElementById('doiSoatLoading');
    const empty = document.getElementById('doiSoatEmpty');
    if (!list || !loading || !empty) return;
    capNhatBadgeDoiSoat(0);
    document.getElementById('doiSoatCount').innerText =
        t('seller.reconciliation.waiting_cases', {
            count: 0,
            formattedCount: dinhDangSoSeller(0)
        });
    list.innerHTML = '';
    loading.style.display = 'none';
    empty.style.display = 'block';
    empty.innerHTML = `<i class="ph ph-storefront" style="display:block; margin-bottom:0.5rem; font-size:2.2rem;"></i>${escapeHtml(t('seller.reconciliation.no_shop'))}`;
}

function renderDoiSoatResponse(res, capNhatBadge = true) {
    const tongDangChoRaw = Number(res.reconciliation_count ?? res.total_orders ?? 0);
    const tongDangCho = Number.isFinite(tongDangChoRaw)
        ? Math.max(0, tongDangChoRaw)
        : 0;
    if (capNhatBadge) capNhatBadgeDoiSoat(tongDangCho);
    document.getElementById('doiSoatCount').innerText =
        t('seller.reconciliation.waiting_cases', {
            count: tongDangCho,
            formattedCount: dinhDangSoSeller(tongDangCho)
        });
    renderDoiSoat(res.orders || []);
    capNhatPhanTrangDoiSoat(res);
}

async function loadDoiSoat() {
    const shopId = doiSoatShopId || currentShopId || dashboardShopId;
    const list = document.getElementById('doiSoatList');
    const loading = document.getElementById('doiSoatLoading');
    const empty = document.getElementById('doiSoatEmpty');
    const reloadButton = document.getElementById('btnTaiLaiDoiSoat');
    if (!list || !loading || !empty) return;

    if (!shopId) {
        renderDoiSoatKhongCoShop();
        return;
    }

    doiSoatShopId = shopId;
    const select = document.getElementById('doiSoatShopSelect');
    if (select) select.value = String(shopId);

    const requestId = ++doiSoatRequestId;
    const badgeRequestId = ++doiSoatBadgeRequestId;
    loading.style.display = 'block';
    empty.style.display = 'none';
    if (reloadButton) reloadButton.disabled = true;

    try {
        const params = new URLSearchParams({
            page: String(trangDoiSoat),
            per_page: String(DOI_SOAT_MOI_TRANG),
            reconciliation_only: 'true'
        });
        const res = await apiCall(`/dashboard/seller/${shopId}?${params.toString()}`);
        if (requestId !== doiSoatRequestId || shopId !== doiSoatShopId) return;

        if ((!res.orders || res.orders.length === 0) && trangDoiSoat > 1 && res.total_orders > 0) {
            trangDoiSoat -= 1;
            return loadDoiSoat();
        }

        reconciliationCache = { shopId, data: res };
        renderDoiSoatResponse(res, badgeRequestId === doiSoatBadgeRequestId);
    } catch (e) {
        if (requestId !== doiSoatRequestId || shopId !== doiSoatShopId) return;
        list.innerHTML = '';
        empty.style.display = 'block';
        empty.innerHTML = `<i class="ph ph-warning-circle" style="display:block; margin-bottom:0.5rem; color:#DC2626; font-size:2.2rem;"></i>${escapeHtml(e.message)}`;
        showToast(e.message);
    } finally {
        if (requestId === doiSoatRequestId && shopId === doiSoatShopId) {
            loading.style.display = 'none';
            if (reloadButton) reloadButton.disabled = false;
        }
    }
}

async function lamMoiBadgeDoiSoatNen() {
    if (document.hidden || !doiSoatShopId) return;
    const tabDangMo = document.getElementById('reconciliation')?.classList.contains('active');
    if (tabDangMo) return loadDoiSoat();
    const shopId = doiSoatShopId;
    const requestId = ++doiSoatBadgeRequestId;
    try {
        const params = new URLSearchParams({
            page: '1',
            per_page: '1',
            reconciliation_only: 'true'
        });
        const res = await apiCall(
            `/dashboard/seller/${shopId}?${params.toString()}`
        );
        if (requestId !== doiSoatBadgeRequestId || shopId !== doiSoatShopId) return;
        capNhatBadgeDoiSoat(res.reconciliation_count ?? res.total_orders ?? 0);
    } catch (e) {
        // Làm mới nền không chen toast vào công việc đang làm.
        console.debug('Chưa làm mới được badge đối soát:', e.message);
    }
}

function renderDoiSoat(orders) {
    const list = document.getElementById('doiSoatList');
    const empty = document.getElementById('doiSoatEmpty');
    const hopLe = (orders || []).filter(o => Number.isInteger(Number(o.id)));
    list.innerHTML = hopLe.map(taoTheDoiSoat).join('');
    empty.style.display = hopLe.length ? 'none' : 'block';
    if (!hopLe.length) {
        empty.innerHTML = `<i class="ph ph-check-circle" style="display:block; margin-bottom:0.5rem; color:var(--success); font-size:2.2rem;"></i>${escapeHtml(t('seller.reconciliation.empty'))}`;
    }
}

function taoTheDoiSoat(order) {
    const orderId = Number(order.id);
    const reason = String(order.reconciliation_reason || 'LEGACY_REVIEW');
    const meta = thongTinLoaiDoiSoat(reason);
    const tongDon = Number(order.total) || 0;
    const tienNganHang = Number(order.bank_paid_amount) || 0;
    const tienMat = Number(order.cash_paid_amount) || 0;
    const daNhan = Number(order.received_amount) || 0;
    const conThieu = Math.max(Number(order.remaining_amount) || 0, 0);
    const canHoan = Math.max(Number(order.refund_due_amount) || 0, 0);
    const ngay = dinhDangNgayGio(order.date);

    let nhanChenhLech = t('seller.reconciliation.received');
    let tienChenhLech = daNhan;
    if (reason === 'UNDERPAID') {
        nhanChenhLech = t('seller.reconciliation.remaining');
        tienChenhLech = conThieu;
    } else if (reason === 'OVERPAID') {
        nhanChenhLech = t('seller.reconciliation.refund_customer');
        tienChenhLech = canHoan;
    } else if (reason === 'LATE_PAYMENT') {
        nhanChenhLech = t('seller.reconciliation.refund_all');
        tienChenhLech = canHoan;
    }

    let nutXuLy = '';
    if (reason === 'UNDERPAID' && conThieu > 0) {
        nutXuLy = `
            <button id="btnBuTienMat-${orderId}" onclick="thuBuTienMatDoiSoat(${orderId}, ${conThieu})">
                <i class="ph ph-money"></i> ${escapeHtml(t('seller.reconciliation.collect_topup', { amount: dinhDangTienDoiSoat(conThieu) }))}
            </button>`;
    } else if (
        (reason === 'OVERPAID' || reason === 'LATE_PAYMENT')
        && order.refund_pending
        && canHoan > 0
    ) {
        nutXuLy = `
            <button id="btnDaHoan-${orderId}" onclick="moModalHoanTien(${orderId}, ${canHoan}, '${reason}')">
                <i class="ph ph-arrow-u-up-left"></i> ${escapeHtml(t('seller.reconciliation.mark_refunded'))}
            </button>`;
    }

    return `
        <article class="doi-soat-card ${meta.cardClass}" id="doiSoatCard-${orderId}">
            <div class="doi-soat-card-head">
                <div>
                    <h4 class="doi-soat-card-title">${escapeHtml(t('seller.reconciliation.order_title', { id: orderId, title: meta.title }))}</h4>
                    <div class="doi-soat-card-time">${escapeHtml(ngay)}</div>
                </div>
                <span class="doi-soat-state ${meta.stateClass}">${escapeHtml(meta.stateLabel)}</span>
            </div>
            <div class="doi-soat-money-grid">
                <div class="doi-soat-money">
                    <span>${escapeHtml(t('seller.reconciliation.order_total'))}</span>
                    <strong>${dinhDangTienDoiSoat(tongDon)}</strong>
                </div>
                <div class="doi-soat-money">
                    <span>${escapeHtml(t('seller.reconciliation.bank_amount'))}</span>
                    <strong>${dinhDangTienDoiSoat(tienNganHang)}</strong>
                </div>
                <div class="doi-soat-money">
                    <span>${escapeHtml(t('seller.reconciliation.cash_topup'))}</span>
                    <strong>${dinhDangTienDoiSoat(tienMat)}</strong>
                </div>
                <div class="doi-soat-money highlight">
                    <span>${escapeHtml(nhanChenhLech)}</span>
                    <strong>${dinhDangTienDoiSoat(tienChenhLech)}</strong>
                </div>
            </div>
            <p class="doi-soat-note">${escapeHtml(meta.note)}</p>
            <div class="doi-soat-actions">
                <button class="btn-outline" onclick="xemChiTietDon(${orderId})">
                    <i class="ph ph-receipt"></i> ${escapeHtml(t('seller.actions.view_detail'))}
                </button>
                ${nutXuLy}
            </div>
        </article>`;
}

function capNhatPhanTrangDoiSoat(res) {
    const box = document.getElementById('doiSoatPagination');
    const info = document.getElementById('doiSoatThongTinTrang');
    const truoc = document.getElementById('doiSoatTrangTruoc');
    const sau = document.getElementById('doiSoatTrangSau');
    const tong = Number(res.total_orders) || 0;
    if (!box || !info || !truoc || !sau) return;

    box.style.display = tong > DOI_SOAT_MOI_TRANG ? 'flex' : 'none';
    if (tong > 0) {
        const dau = (res.page - 1) * res.per_page + 1;
        const cuoi = Math.min(res.page * res.per_page, tong);
        info.innerText = t('seller.pagination.showing_cases', {
            from: dinhDangSoSeller(dau),
            to: dinhDangSoSeller(cuoi),
            total: dinhDangSoSeller(tong)
        });
    } else {
        info.innerText = '';
    }
    truoc.disabled = res.page <= 1;
    sau.disabled = !res.has_more;
}

function doiTrangDoiSoat(buoc) {
    const trangMoi = trangDoiSoat + buoc;
    if (trangMoi < 1) return;
    trangDoiSoat = trangMoi;
    loadDoiSoat();
}

async function coCaTienMatDangMo() {
    const shopId = doiSoatShopId || dashboardShopId || currentShopId;
    if (!shopId) {
        showToast(t('seller.reconciliation.choose_shop_first'));
        return false;
    }
    try {
        const res = await apiCall(`/shifts/current/${shopId}`);
        if (res?.shift) return true;
        showToast(t('seller.shifts.open_required'));
        return false;
    } catch (e) {
        showToast(e.message || t('seller.shifts.check_error'));
        return false;
    }
}

async function thuBuTienMatDoiSoat(orderId, conThieu) {
    const id = Number(orderId);
    const soTien = Number(conThieu);
    if (!Number.isInteger(id) || !Number.isFinite(soTien) || soTien <= 0) return;
    if (!await coCaTienMatDangMo()) return;

    showCustomConfirm(
        t('seller.reconciliation.topup_title', { id }),
        t('seller.reconciliation.topup_confirm', {
            amount: dinhDangTienDoiSoat(soTien)
        }),
        async () => {
            const button = document.getElementById(`btnBuTienMat-${id}`);
            if (button) button.disabled = true;
            try {
                const res = await apiCall(`/orders/${id}/cash-topup`, 'POST', {});
                showToast(res.msg || t('seller.reconciliation.topup_done'));
                await loadDoiSoat();
            } catch (e) {
                showToast(e.message);
                await loadDoiSoat();
            } finally {
                const currentButton = document.getElementById(`btnBuTienMat-${id}`);
                if (currentButton) currentButton.disabled = false;
            }
        },
        t('seller.reconciliation.money_received')
    );
}

function taoOperationIdHoanTien() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
        return globalThis.crypto.randomUUID();
    }
    return `refund-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function moModalHoanTien(orderId, amount, reason) {
    const id = Number(orderId);
    const soTien = Number(amount);
    if (!Number.isInteger(id) || !Number.isFinite(soTien) || soTien <= 0) return;

    refundOrderId = id;
    refundDueAmount = soTien;
    refundOperationId = taoOperationIdHoanTien();
    refundReason = reason;
    document.getElementById('refundOrderLabel').innerText =
        reason === 'LATE_PAYMENT'
            ? t('seller.refund.cancelled_order', { id })
            : t('seller.refund.completed_order', { id });
    document.getElementById('refundAmount').innerText = dinhDangTienDoiSoat(soTien);
    document.getElementById('refundMethod').value = 'cash';
    document.getElementById('refundReference').value = '';
    document.getElementById('refundNote').value = '';
    capNhatFormHoanTien();
    document.getElementById('refundModal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
    document.getElementById('refundMethod').focus();
}

function capNhatFormHoanTien() {
    const method = document.getElementById('refundMethod')?.value;
    const group = document.getElementById('refundReferenceGroup');
    if (group) group.style.display = method === 'transfer' ? 'block' : 'none';
}

function dongModalHoanTien() {
    if (dangLuuHoanTien) return;
    const modal = document.getElementById('refundModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
    refundOrderId = null;
    refundDueAmount = 0;
    refundOperationId = null;
    refundReason = null;
}

async function xacNhanDaHoanTien() {
    if (
        dangLuuHoanTien
        || !refundOrderId
        || refundDueAmount <= 0
        || !refundOperationId
    ) return;
    const method = document.getElementById('refundMethod').value;
    if (method !== 'cash' && method !== 'transfer') {
        return showToast(t('seller.refund.choose_method'));
    }
    if (method === 'cash' && !await coCaTienMatDangMo()) return;

    const note = document.getElementById('refundNote').value.trim();
    const reference = method === 'transfer'
        ? document.getElementById('refundReference').value.trim()
        : '';
    const payload = { method, operation_id: refundOperationId };
    if (note) payload.note = note;
    if (reference) payload.reference = reference;

    const orderId = refundOrderId;
    const button = document.getElementById('btnSubmitRefund');
    dangLuuHoanTien = true;
    button.disabled = true;
    button.innerHTML = `<i class="ph ph-spinner-gap"></i> <span data-seller-action-label="refund-submit">${escapeHtml(t('seller.refund.saving'))}</span>`;
    try {
        const res = await apiCall(`/orders/${orderId}/refund-complete`, 'POST', payload);
        showToast(res.msg || t('seller.refund.success'));
        dangLuuHoanTien = false;
        dongModalHoanTien();
        await loadDoiSoat();
    } catch (e) {
        showToast(e.message);
        await loadDoiSoat();
    } finally {
        dangLuuHoanTien = false;
        button.disabled = false;
        button.innerHTML = `<i class="ph ph-check-circle"></i> <span data-seller-action-label="refund-submit">${escapeHtml(t('seller.reconciliation.mark_refunded'))}</span>`;
    }
}

function goToPOS(id) {
    localStorage.setItem('currentShopId', id);
    navigateToPage('/pos');
}

function changeShop(id) {
    const shopId = Number.parseInt(id, 10);
    if (!Number.isInteger(shopId) || !allShops.some(shop => shop.id === shopId)) return;
    currentShopId = shopId;
    localStorage.setItem('currentShopId', currentShopId);
    loadDataForCurrentShop();
    const shop = allShops.find(s => s.id === currentShopId);
    showToast(t('seller.shops.loaded', { name: shop?.name || '' }));
}

function loadDataForCurrentShop() {
    if(allShops.length === 0 || !batDauDungShopHienTai()) return;
    const canReport = coQuyenNhanVien('REPORT');
    const canInventory = coQuyenNhanVien('INVENTORY');
    const canVoucher = coQuyenNhanVien('VOUCHER');
    document.getElementById('dashboardContent').style.display = canReport ? 'block' : 'none';
    document.getElementById('warehouseContent').style.display = canInventory ? 'grid' : 'none';
    document.getElementById('voucherContent').style.display = canVoucher ? 'grid' : 'none';
    document.getElementById('kkContent').style.display = canInventory ? 'block' : 'none';
    document.getElementById('noShopMsg').style.display = 'none';
    
    const shop = allShops.find(s => s.id === currentShopId);
    if (canReport) {
        document.getElementById('currentShopName').innerText = shop.name;
        loadDashboardShop(currentShopId);
    }
    if (canInventory) {
        document.getElementById('whShopName').innerText = shop.name;
        document.getElementById('kkShopName').innerText = shop.name;
        kkXoaHet();   // đổi shop thì phiếu đếm của shop cũ không còn nghĩa lý gì

        // Clear inputs for new shop
        document.getElementById('prodCode').value = '';
        document.getElementById('prodBarcode').value = '';
        document.getElementById('prodName').value = '';
        document.getElementById('prodPrice').value = '';
        document.getElementById('prodImage').value = '';
        document.getElementById('catNameInput').value = '';

        loadCategories();
        loadProducts();
    }
    if (canVoucher) {
        document.getElementById('vcShopName').innerText = shop.name;
        loadVouchers();
    }
}

// Settings List Render
function renderShopsList() {
    const listDiv = document.getElementById('myShopsList');
    listDiv.innerHTML = '';
    if(allShops.length === 0) {
        listDiv.innerHTML = `<p>${escapeHtml(t('seller.shops.no_shops'))}</p>`;
        return;
    }
    allShops.forEach(s => {
        const activeBadge = s.is_active
            ? `<span style="color:var(--success); font-size: 0.8rem; margin-left: 0.5rem; padding: 2px 6px; background: rgba(16,185,129,0.1); border-radius: 4px;">${escapeHtml(t('seller.status.active'))}</span>`
            : `<span style="color:#ef4444; font-size: 0.8rem; margin-left: 0.5rem; padding: 2px 6px; background: rgba(239,68,68,0.1); border-radius: 4px;">${escapeHtml(t('seller.status.inactive'))}</span>`;
        const toggleBtn = `<button class="btn-outline" onclick="toggleShopStatus(${s.id})" style="padding: 0.5rem 1rem; margin-right: 0.5rem;" title="${escapeHtml(t('seller.actions.change_status'))}" aria-label="${escapeHtml(t('seller.actions.change_status'))}"><i class="ph ph-power"></i></button>`;
        const deleteBtn = `<button class="btn-outline" onclick="deleteShop(${s.id})" style="padding: 0.5rem 1rem; color: #ef4444; margin-left: 0.5rem;" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}"><i class="ph ph-trash"></i></button>`;
        
        listDiv.innerHTML += `
            <div class="shop-list-card">
                <div>
                    <h4 style="display:flex; align-items:center;">${escapeHtml(s.name)} ${activeBadge}</h4>
                    <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.3rem;"><i class="ph ph-map-pin"></i> ${escapeHtml(s.business_address || t('seller.shops.not_updated'))}</div>
                </div>
                <div style="display: flex;">
                    ${toggleBtn}
                    <button class="btn-outline" onclick="openEditShopForm(${s.id})" style="padding: 0.5rem 1rem;"><i class="ph ph-pencil"></i> ${escapeHtml(t('seller.actions.edit'))}</button>
                    ${deleteBtn}
                </div>
            </div>
        `;
    });
}

async function toggleShopStatus(id) {
    try {
        await apiCall(`/shops/${id}/status`, 'PUT');
        showToast(t('seller.shops.updated_status'));
        init();
    } catch(e) { showToast(e.message); }
}

function deleteShop(id) {
    showCustomConfirm(
        t('seller.shops.delete_title'),
        t('seller.shops.delete_confirm'),
        async () => {
            try {
                await apiCall(`/shops/${id}`, 'DELETE');
                showToast(t('seller.shops.deleted'));
                // Clear selected shop if it was the one deleted
                if (currentShopId === id) {
                    currentShopId = null;
                    localStorage.removeItem('currentShopId');
                    loadedCurrentShopId = null;
                    currentShopGeneration += 1;
                    xoaDuLieuShopCuKhoiGiaoDien();
                }
                init();
            } catch(e) { showToast(e.message); }
        }
    );
}

function openCreateShopForm() {
    if(allShops.length >= 3) return showToast(t('seller.shops.limit_reached'));
    editShopId = null;
    document.getElementById('formTitle').innerHTML = `<i class="ph ph-storefront" style="color: var(--primary);"></i> <span data-seller-action-label="shop-form-title">${escapeHtml(t('seller.shops.create_title'))}</span>`;
    document.getElementById('btnSaveShop').innerHTML = `<i class="ph ph-plus-circle"></i> <span data-seller-action-label="shop-save">${escapeHtml(t('seller.shops.create_confirm'))}</span>`;
    
    renderBankOptions();
    // Clear form
    document.getElementById('shopName').value = '';
    document.getElementById('shopAddress').value = '';
    document.getElementById('shopTaxCode').value = '';
    document.getElementById('shopPhone').value = '';
    document.getElementById('shopEmail').value = '';
    document.getElementById('bankCode').value = '';
    document.getElementById('bankAcc').value = '';
    document.getElementById('bankAccName').value = '';
    
    triggerPreview();
    
    document.getElementById('shopFormContainer').style.display = 'grid';
    document.getElementById('shopFormDivider').style.display = 'block';
}

function openEditShopForm(id) {
    editShopId = id;
    const shop = allShops.find(s => s.id === id);
    document.getElementById('formTitle').innerHTML = `<i class="ph ph-storefront" style="color: var(--primary);"></i> <span data-seller-action-label="shop-form-title">${escapeHtml(t('seller.shops.edit_title', { name: shop.name }))}</span>`;
    document.getElementById('btnSaveShop').innerHTML = `<i class="ph ph-check-circle"></i> <span data-seller-action-label="shop-save">${escapeHtml(t('seller.shops.save_update'))}</span>`;
    
    renderBankOptions();
    // Fill Settings Form
    document.getElementById('shopName').value = shop.name;
    document.getElementById('shopAddress').value = shop.business_address || '';
    document.getElementById('shopTaxCode').value = shop.tax_code || '';
    document.getElementById('shopPhone').value = shop.phone || '';
    document.getElementById('shopEmail').value = shop.email || '';
    document.getElementById('bankCode').value = shop.bank_code;
    document.getElementById('bankAcc').value = shop.bank_account_no;
    document.getElementById('bankAccName').value = shop.bank_account_name || '';
    
    triggerPreview();
    
    document.getElementById('shopFormContainer').style.display = 'grid';
    document.getElementById('shopFormDivider').style.display = 'block';
}

function triggerPreview() {
    document.getElementById('shopName').dispatchEvent(new Event('input'));
    document.getElementById('shopTaxCode').dispatchEvent(new Event('input'));
    document.getElementById('shopAddress').dispatchEvent(new Event('input'));
}

function closeShopForm() {
    document.getElementById('shopFormContainer').style.display = 'none';
    document.getElementById('shopFormDivider').style.display = 'none';
}

async function saveShop() {
    const name = document.getElementById('shopName').value.trim();
    const address = document.getElementById('shopAddress').value.trim();
    const taxCode = document.getElementById('shopTaxCode').value.trim();
    const phone = document.getElementById('shopPhone').value.trim();
    const email = document.getElementById('shopEmail').value.trim();
    const bankAcc = document.getElementById('bankAcc').value.trim();
    const bankAccName = document.getElementById('bankAccName').value.trim();
    const bankCode = document.getElementById('bankCode').value;

    if (!name) return showToast(t('seller.shops.name_required_error'));
    if (!address) return showToast(t('seller.shops.address_required_error'));
    if (!taxCode) return showToast(t('seller.shops.tax_required_error'));
    if (!phone) return showToast(t('seller.shops.phone_required_error'));
    if (!email) return showToast(t('seller.shops.email_required_error'));
    if (!bankCode) return showToast(t('seller.shops.bank_required_error'));
    if (!bankAcc) return showToast(t('seller.shops.account_required_error'));
    if (!bankAccName) return showToast(t('seller.shops.account_name_required_error'));

    const body = {
        name,
        business_address: address,
        tax_code: taxCode,
        phone,
        email,
        bank_account_no: bankAcc,
        bank_account_name: bankAccName,
        bank_code: bankCode
    };
    
    try {
        if(editShopId) {
            await apiCall(`/shops/${editShopId}`, 'PUT', body);
            showToast(t('seller.shops.updated'));
        } else {
            await apiCall('/shops', 'POST', body);
            showToast(t('seller.shops.created'));
        }
        setTimeout(() => location.reload(), 1000);
    } catch(e) { showToast(e.message); }
}

// --- DASHBOARD / DATA LOGIC ---

function switchWarehouseSubTab(subTab) {
    const nut = {
        products: 'whSubTabProds',
        categories: 'whSubTabCats',
        expiry: 'whSubTabExpiry'
    };
    const khoi = {
        products: ['warehouseProductsSection', 'grid'],
        categories: ['warehouseCategoriesSection', 'grid'],
        expiry: ['warehouseExpirySection', 'block']
    };
    if (!khoi[subTab]) subTab = 'products';

    Object.entries(nut).forEach(([ten, id]) => {
        document.getElementById(id)?.classList.toggle('active', ten === subTab);
    });
    Object.entries(khoi).forEach(([ten, [id, kieu]]) => {
        const el = document.getElementById(id);
        if (el) el.style.display = ten === subTab ? kieu : 'none';
    });

    if (subTab === 'expiry') loadHanSuDung();
}

// ===== F5: hàng sắp hết hạn và đã hết hạn =====

let hanSuDungRequestId = 0;

async function loadHanSuDung() {
    const shopId = currentShopId;
    if (!shopId) return;
    const soNgay = Number(document.getElementById('expiryDays')?.value) || 30;
    const requestId = ++hanSuDungRequestId;
    const generation = currentShopGeneration;
    try {
        const d = await apiCall(`/products/${shopId}/batches?days=${soNgay}`);
        // Đổi shop giữa chừng thì kết quả cũ không được ghi đè lên màn mới.
        if (requestId !== hanSuDungRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId) return;
        veHanSuDung(d);
    } catch (e) {
        if (requestId === hanSuDungRequestId && currentShopId === shopId) {
            showToast(e.message);
        }
    }
}

function veHanSuDung(d) {
    const soHetHan = Number(d.expired_quantity || 0);
    const soSapHet = Number(d.expiring_soon_quantity || 0);
    document.getElementById('expiredQty').innerText = dinhDangSoSeller(soHetHan);
    document.getElementById('soonQty').innerText = dinhDangSoSeller(soSapHet);

    // Giá trị tồn chỉ có mặt khi người gọi được xem giá vốn; không có thì để
    // trống chứ không hiện 0 - 0 ở đây đọc ra là "hàng không đáng tiền nào".
    const veTien = (id, gia_tri) => {
        const el = document.getElementById(id);
        el.innerText = (gia_tri === undefined || gia_tri === null)
            ? ''
            : t('seller.expiry.value', { amount: dinhDangTienDoiSoat(gia_tri) });
    };
    veTien('expiredValue', d.expired_value);
    veTien('soonValue', d.expiring_soon_value);

    // Badge trên tab con: chỉ đếm hàng ĐÃ hỏng, đó mới là thứ phải xử lý ngay.
    const badge = document.getElementById('expiryBadge');
    if (badge) {
        badge.innerText = soHetHan > 99 ? '99+' : String(soHetHan);
        badge.style.display = soHetHan > 0 ? 'inline-block' : 'none';
    }

    const tbody = document.getElementById('expiryList');
    tbody.innerHTML = '';
    const dong = [
        ...(d.expired || []).map(r => ({ ...r, hong: true })),
        ...(d.expiring_soon || []).map(r => ({ ...r, hong: false }))
    ];
    if (!dong.length) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: var(--text-muted);">`
            + `${escapeHtml(t('seller.expiry.empty'))}</td></tr>`;
        return;
    }
    dong.forEach(r => {
        const nhan = r.hong
            ? `<span style="color:#B91C1C; font-weight:700;">${escapeHtml(t('seller.expiry.expired'))}</span>`
            : `<span style="color:#B45309; font-weight:600;">${escapeHtml(t('seller.expiry.soon'))}</span>`;
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(r.product_name || '')}</td>
            <td style="white-space:nowrap;">${escapeHtml(r.expiry_date || '')}</td>
            <td>${escapeHtml(dinhDangSoSeller(r.quantity))}</td>
            <td>${nhan}</td>
        </tr>`;
    });
}

function renderCategories(cats) {
    const sel = document.getElementById('catSelect');
    if (sel) {
        const previousCategory = sel.value;
        sel.innerHTML = '';
        const activeCats = cats.filter(c => c.is_active !== false);
        activeCats.forEach(c => sel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)}</option>`);
        if (activeCats.some(c => String(c.id) === previousCategory)) {
            sel.value = previousCategory;
        }
    }

    const filterSel = document.getElementById('filterCatSelect');
    if (filterSel) {
        const prevVal = filterSel.value;
        filterSel.innerHTML = `<option value="">${escapeHtml(t('seller.filters.all'))}</option>`;
        cats.forEach(c => {
            const suffix = c.is_active === false ? t('seller.filters.hidden_suffix') : '';
            filterSel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)}${suffix}</option>`;
        });
        if (cats.find(c => c.id == prevVal)) {
            filterSel.value = prevVal;
        }
    }

    renderCategoriesTable(cats);
}

async function loadCategories() {
    if(!currentShopId) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const requestId = ++categoriesRequestId;
    try {
        const cats = await apiCall(`/categories/${shopId}`);
        if (
            requestId !== categoriesRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId
        ) return;
        currentCategories = cats;
        currentCategoriesShopId = shopId;
        renderCategories(cats);
    } catch(e) {
        if (
            requestId === categoriesRequestId
            && generation === currentShopGeneration
            && currentShopId === shopId
        ) {
            console.error("Error loading categories:", e);
        }
    }
}

let editingCategoryId = null;

function renderCategoriesTable(cats) {
    const tbody = document.getElementById('categoryTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    cats.forEach(c => {
        const activeText = c.is_active !== false
            ? `<span style="color:var(--success); font-weight:600; font-size: 0.8rem;">${escapeHtml(t('seller.status.active'))}</span>`
            : `<span style="color:#ef4444; font-weight:600; font-size: 0.8rem;">${escapeHtml(t('seller.status.inactive'))}</span>`;
        const categoryId = Number(c.id);
        if (!Number.isInteger(categoryId)) return;
            
        tbody.innerHTML += `<tr>
            <td>${categoryId}</td>
            <td><strong>${escapeHtml(c.name)}</strong></td>
            <td>${activeText}</td>
            <td>
                <button type="button" class="btn-outline" data-category-edit-id="${categoryId}" style="padding: 0.2rem 0.5rem;" title="${escapeHtml(t('seller.actions.edit'))}" aria-label="${escapeHtml(t('seller.actions.edit'))}"><i class="ph ph-pencil"></i></button>
            </td>
        </tr>`;
    });
    tbody.querySelectorAll('[data-category-edit-id]').forEach(button => {
        button.addEventListener('click', () => {
            editCategory(Number(button.dataset.categoryEditId));
        });
    });
}

function editCategory(id) {
    if (!damBaoCacheShopHienTai(currentCategoriesShopId)) return;
    const category = currentCategories.find(item => Number(item.id) === Number(id));
    if (!category) return;
    editingCategoryId = id;
    document.getElementById('editingCatId').value = id;
    document.getElementById('catNameInput').value = category.name;
    document.getElementById('catStatusSelect').value =
        category.is_active !== false ? 'active' : 'inactive';
    
    document.getElementById('catFormTitle').innerText = t('seller.categories.edit_title');
    document.getElementById('btnSaveCategory').innerHTML = `<i class="ph ph-check-circle"></i> <span data-seller-action-label="category-save">${escapeHtml(t('seller.categories.update'))}</span>`;
    document.getElementById('btnCancelEditCategory').style.display = 'block';
}

function cancelEditCategory() {
    editingCategoryId = null;
    document.getElementById('editingCatId').value = '';
    document.getElementById('catNameInput').value = '';
    document.getElementById('catStatusSelect').value = 'active';
    
    document.getElementById('catFormTitle').innerText = t('seller.categories.add_title');
    document.getElementById('btnSaveCategory').innerHTML = `<i class="ph ph-plus-circle"></i> <span data-seller-action-label="category-save">${escapeHtml(t('seller.categories.save'))}</span>`;
    document.getElementById('btnCancelEditCategory').style.display = 'none';
}

async function saveCategory() {
    if(!currentShopId) return;
    if (!damBaoCacheShopHienTai(currentCategoriesShopId)) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const categoryId = editingCategoryId;
    const isEditing = categoryId !== null;
    const name = document.getElementById('catNameInput').value.trim();
    const status = document.getElementById('catStatusSelect').value;
    
    if(!name) {
        return showToast(t('seller.categories.name_required_error'));
    }
    
    try {
        if(isEditing) {
            const body = {
                name: name,
                is_active: status === 'active'
            };
            await apiCall(`/categories/${categoryId}`, 'PUT', body);
        } else {
            await apiCall(`/categories?name=${encodeURIComponent(name)}&shop_id=${shopId}`, 'POST');
        }
        if (generation !== currentShopGeneration || currentShopId !== shopId) {
            return;
        }
        showToast(t(isEditing ? 'seller.categories.updated' : 'seller.categories.created'));
        cancelEditCategory();
        loadCategories();
        loadProducts();
    } catch(e) {
        if (generation === currentShopGeneration && currentShopId === shopId) {
            showToast(e.message);
        }
    }
}

let currentProducts = [];
let editingProductId = null;

async function loadProducts() {
    if(!currentShopId) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const requestId = ++productsRequestId;
    try {
        const products = await apiCall(`/products/${shopId}`);
        if (
            requestId !== productsRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId
        ) return;
        currentProducts = products;
        currentProductsShopId = shopId;
        await napGiaVon(shopId, generation, requestId);
        if (
            requestId !== productsRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId
        ) return;
        filterProducts();
    } catch (e) {
        if (
            requestId === productsRequestId
            && generation === currentShopGeneration
            && currentShopId === shopId
        ) showToast(e.message);
    }
}

/** Nạp giá vốn cho shop đang xem. Nhân viên không gọi, và lỗi thì bỏ qua im
 *  lặng: thiếu giá vốn không được phép làm hỏng cả bảng kho hàng. */
async function napGiaVon(shopId, generation, requestId) {
    if (!XEM_DUOC_GIA_VON) {
        giaVonTheoSanPham = {};
        soSanPhamChuaKhaiGiaVon = 0;
        return;
    }
    try {
        const res = await apiCall(`/products/${shopId}/costs`);
        if (
            requestId !== productsRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId
        ) return;
        const bang = {};
        (res.costs || []).forEach(d => { bang[d.product_id] = d.cost_price; });
        giaVonTheoSanPham = bang;
        soSanPhamChuaKhaiGiaVon = res.chua_khai || 0;
    } catch (e) {
        giaVonTheoSanPham = {};
        soSanPhamChuaKhaiGiaVon = 0;
    }
}

/** Giá vốn của một sản phẩm, hoặc null nếu chưa khai. `undefined` (chưa nạp
 *  xong) cũng quy về null - không được đoán là 0. */
function giaVonCua(productId) {
    const gia = giaVonTheoSanPham[productId];
    return (gia === undefined || gia === null) ? null : gia;
}

/** Dòng giá vốn nhỏ dưới ô giá bán trong bảng kho hàng.
 *
 *  Sản phẩm chưa khai được nêu rõ bằng chữ chứ không để trống: chỗ trống đọc ra
 *  là "giá vốn bằng 0", và chính những dòng này mới là thứ đang khiến báo cáo
 *  lãi thiếu đơn. */
function dongGiaVon(productId) {
    if (!XEM_DUOC_GIA_VON) return '';
    const gia = giaVonCua(productId);
    if (gia === null) {
        return `<br><span style="font-size:0.72rem; color:#B45309;">`
            + `${escapeHtml(t('seller.products.cost_missing'))}</span>`;
    }
    return `<br><span style="font-size:0.72rem; color:#64748B;">`
        + `${escapeHtml(t('seller.products.cost_short'))} `
        + `${escapeHtml(dinhDangTienDoiSoat(gia))}</span>`;
}

// Ô "Tên sản phẩm" mang hai nghĩa tùy theo có khai biến thể hay không, nên nhãn
// của nó phải nói ra nghĩa đang dùng. Không đổi nhãn thì người dùng gõ
// "Áo thun đỏ L" vào ô tên rồi lại gõ "Đỏ / L" vào ô biến thể, ra tên đầy đủ
// "Áo thun đỏ L - Đỏ / L" - sai mà không có gì báo.
function capNhatNhanTenSanPham() {
    const nhan = document.getElementById('prodNameLabel');
    if (!nhan) return;
    const coBienThe = Boolean(document.getElementById('prodVariant')?.value.trim());
    nhan.innerText = t(
        coBienThe ? 'seller.products.group_required' : 'seller.products.name_required'
    );
}

// Khóa gom nhóm của một dòng. Sản phẩm đơn lẻ tự đứng thành nhóm một mình nên
// đoạn sắp xếp bên dưới không cần rẽ nhánh.
function _khoaNhom(p) {
    return p.variant_group || p.name || '';
}

/** Sắp xếp để các biến thể cùng nhóm nằm liền nhau, và trong nhóm thì theo tên
 *  biến thể. Không gộp thành một dòng: mỗi biến thể vẫn cần đủ nút sửa, nhập
 *  xuất kho, bật tắt và xóa của riêng nó. */
function _sapXepTheoNhom(danhSach) {
    return [...danhSach].sort((a, b) => {
        const nhom = _khoaNhom(a).localeCompare(_khoaNhom(b), 'vi');
        if (nhom !== 0) return nhom;
        return (a.variant_name || '').localeCompare(b.variant_name || '', 'vi');
    });
}

function filterProducts() {
    const tbody = document.getElementById('prodList');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!cacheThuocShop(currentProductsShopId, currentShopId)) return;
    const filterCatId = document.getElementById('filterCatSelect').value;

    const filtered = filterCatId
        ? currentProducts.filter(p => p.category_id == filterCatId)
        : currentProducts;

    _sapXepTheoNhom(filtered).forEach(p => {
        const activeText = p.is_active
            ? `<span style="color:var(--success); font-weight:600; font-size: 0.8rem;">${escapeHtml(t('seller.status.active'))}</span>`
            : `<span style="color:#ef4444; font-weight:600; font-size: 0.8rem;">${escapeHtml(t('seller.status.inactive'))}</span>`;
        // Tên nhóm mờ ở trên, tên biến thể đậm ở dưới. Nhắc lại tên nhóm ở MỌI
        // dòng chứ không chỉ dòng đầu nhóm: bảng này cuộn được và lọc được theo
        // danh mục, nên dòng "Size 32" đứng một mình là chuyện thường - lúc đó
        // không đọc ra được nó là quần hay áo. Chữ mờ lặp lại vẫn đủ để mắt gom
        // nhóm, mà không dòng nào mất nghĩa.
        const oTen = p.variant_group
            ? `<div style="color:#64748B; font-size:0.8rem;">${escapeHtml(p.variant_group)}</div>`
              + `<b>${escapeHtml(p.variant_name)}</b>`
            : escapeHtml(p.name);
        const nutThemBienThe = p.variant_group
            ? `<button class="btn-outline" onclick="themBienTheCungNhom(${p.id})" style="padding: 0.2rem 0.5rem;" title="${escapeHtml(t('seller.products.add_variant'))}" aria-label="${escapeHtml(t('seller.products.add_variant'))}"><i class="ph ph-copy"></i></button>`
            : '';
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(p.code||'--')}${p.barcode ? `<br><span style="font-size:0.75rem; color:#64748B;" title="${escapeHtml(t('seller.products.barcode'))}"><i class="ph ph-barcode"></i> ${escapeHtml(p.barcode)}</span>` : ''}</td>
            <td>${oTen} <br>${activeText}</td>
            <td>${dinhDangTienDoiSoat(p.price)}${dongGiaVon(p.id)}</td>
            <td>${dinhDangSoSeller(p.stock)}</td>
            <td style="display:flex; justify-content: center; align-items: center; gap:0.5rem; height: 7rem; flex-wrap: wrap;">
                <button class="btn-outline" onclick="editProduct(${p.id})" style="padding: 0.2rem 0.5rem;" title="${escapeHtml(t('common.edit'))}" aria-label="${escapeHtml(t('common.edit'))}"><i class="ph ph-pencil-simple"></i></button>
                ${nutThemBienThe}
                <button class="btn-outline" onclick="nhapXuatKho(${p.id})" style="padding: 0.2rem 0.5rem;" title="${escapeHtml(t('seller.actions.stock_adjust'))}" aria-label="${escapeHtml(t('seller.actions.stock_adjust'))}"><i class="ph ph-stack"></i></button>
                <button class="btn-outline" onclick="toggleProductStatus(${p.id})" style="padding: 0.2rem 0.5rem;" title="${escapeHtml(t('seller.actions.toggle'))}" aria-label="${escapeHtml(t('seller.actions.toggle'))}"><i class="ph ph-power"></i></button>
                <button class="btn-outline" onclick="deleteProduct(${p.id})" style="padding: 0.2rem 0.5rem; color:#ef4444;" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}"><i class="ph ph-trash"></i></button>
            </td>
        </tr>`;
    });
}

/** Điền sẵn form để thêm một biến thể nữa vào cùng nhóm.
 *
 *  Khai tám size áo mà phải gõ lại tên nhóm, giá, danh mục tám lần thì đến size
 *  thứ ba là bắt đầu có dòng lệch. CỐ Ý bỏ trống ô biến thể và ô mã vạch: đó là
 *  đúng hai thứ bắt buộc phải khác nhau giữa các biến thể. */
function themBienTheCungNhom(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const goc = currentProducts.find(p => p.id === id);
    if (!goc || !goc.variant_group) return;
    cancelEditProduct();
    document.getElementById('prodName').value = goc.variant_group;
    document.getElementById('prodPrice').value = goc.price;
    document.getElementById('catSelect').value = String(goc.category_id);
    const oLo = document.getElementById('prodTrackBatches');
    if (oLo) oLo.checked = Boolean(goc.track_batches);
    const oBienThe = document.getElementById('prodVariant');
    if (oBienThe) { oBienThe.value = ''; oBienThe.focus(); }
    capNhatNhanTenSanPham();
    showToast(t('seller.products.add_variant_ready', { group: goc.variant_group }));
}

// Khi SỬA sản phẩm, ô tồn kho bị khóa: thay đổi tồn kho đi qua nút Nhập/Xuất
// kho (cộng trừ theo delta), tránh ghi đè làm mất hàng khi bán song song.
function _khoaOTonKho(khoa) {
    const el = document.getElementById('prodStock');
    if (!el) return;
    el.disabled = khoa;
    el.title = khoa ? t('seller.products.edit_stock_hint') : '';
    el.style.opacity = khoa ? '0.5' : '1';
}

function editProduct(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const product = currentProducts.find(p => p.id === id);
    if(!product) return;
    editingProductId = id;
    document.getElementById('prodCode').value = product.code || '';
    document.getElementById('prodBarcode').value = product.barcode || '';
    // Với biến thể, ô tên mang tên NHÓM chứ không phải tên đầy đủ: điền
    // "Áo thun - Đỏ / L" vào đây rồi bấm Lưu là server ghép thêm lần nữa thành
    // "Áo thun - Đỏ / L - Đỏ / L".
    document.getElementById('prodName').value = product.variant_group || product.name;
    const oBienThe = document.getElementById('prodVariant');
    if (oBienThe) oBienThe.value = product.variant_name || '';
    capNhatNhanTenSanPham();
    document.getElementById('prodPrice').value = product.price;
    const oGiaVon = document.getElementById('prodCost');
    if (oGiaVon) {
        // Chưa khai thì để TRỐNG chứ không điền 0. Điền 0 là ghi đè một con số
        // sai vào lúc người dùng chỉ định sửa cái tên.
        const giaVon = giaVonCua(product.id);
        oGiaVon.value = giaVon === null ? '' : giaVon;
    }
    document.getElementById('prodStock').value = product.stock;
    _khoaOTonKho(true);
    const oLo = document.getElementById('prodTrackBatches');
    if (oLo) {
        oLo.checked = Boolean(product.track_batches);
        oLo.disabled = true;   // xem mục 'chỉ gửi khi tạo mới' ở createProduct
    }
    document.getElementById('catSelect').value = String(product.category_id);
    document.getElementById('productFormTitle').innerText = t('seller.products.edit_title');
    document.getElementById('btnSaveProduct').innerHTML = `<i class="ph ph-floppy-disk"></i> <span data-seller-action-label="product-save">${escapeHtml(t('seller.products.update'))}</span>`;
    document.getElementById('btnCancelEditProduct').style.display = 'block';
}

function cancelEditProduct() {
    editingProductId = null;
    document.getElementById('prodCode').value = '';
    document.getElementById('prodBarcode').value = '';
    document.getElementById('prodName').value = '';
    const oBienTheMoi = document.getElementById('prodVariant');
    if (oBienTheMoi) oBienTheMoi.value = '';
    capNhatNhanTenSanPham();
    document.getElementById('prodPrice').value = '';
    const oGiaVon = document.getElementById('prodCost');
    if (oGiaVon) oGiaVon.value = '';
    const oLoMoi = document.getElementById('prodTrackBatches');
    if (oLoMoi) { oLoMoi.checked = false; oLoMoi.disabled = false; }
    document.getElementById('prodStock').value = '100';
    _khoaOTonKho(false);
    document.getElementById('prodImage').value = '';
    document.getElementById('productFormTitle').innerText = t('seller.products.add_title');
    document.getElementById('btnSaveProduct').innerHTML = `<i class="ph ph-plus"></i> <span data-seller-action-label="product-save">${escapeHtml(t('seller.products.save'))}</span>`;
    document.getElementById('btnCancelEditProduct').style.display = 'none';
}

async function nhapXuatKho(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const product = currentProducts.find(p => p.id === id);
    if(!product) return;
    const raw = prompt(t('seller.products.stock_prompt', {
        name: product.name,
        stock: dinhDangSoSeller(product.stock)
    }));
    if(raw === null) return;
    const delta = parseInt(raw, 10);
    if(isNaN(delta) || delta === 0) return showToast(t('seller.products.stock_number_required'));

    // Chỉ hỏi đơn giá khi NHẬP kho. Xuất kho không làm đổi đơn giá bình quân
    // của số hàng còn lại, và backend từ chối thẳng nếu gửi kèm.
    const body = { delta };

    // Sản phẩm theo lô: nhập hàng bắt buộc khai hạn, nếu không server từ chối.
    if (delta > 0 && product.track_batches) {
        const hanRaw = prompt(t('seller.products.expiry_prompt', { name: product.name }));
        if (hanRaw === null) return;
        const han = (hanRaw || '').trim();
        if (!/^\d{4}-\d{2}-\d{2}$/.test(han)) {
            return showToast(t('seller.products.expiry_invalid'));
        }
        body.expiry_date = han;
    }

    if (XEM_DUOC_GIA_VON && delta > 0) {
        const giaVonHienTai = giaVonCua(id);
        const rawCost = prompt(t('seller.products.unit_cost_prompt', {
            name: product.name,
            current: giaVonHienTai === null
                ? t('seller.products.cost_missing')
                : dinhDangTienDoiSoat(giaVonHienTai)
        }));
        if (rawCost === null) return;   // bấm Hủy ở ô đơn giá = hủy cả phiếu nhập
        const chuoi = rawCost.trim();
        if (chuoi !== '') {
            const unitCost = parseFloat(chuoi);
            if (isNaN(unitCost) || unitCost < 0) {
                return showToast(t('seller.products.cost_nonnegative'));
            }
            // Gửi cả khi bằng 0: hàng tặng có đơn giá 0 thật và phải kéo bình
            // quân xuống. Bỏ trống mới là "không khai", và khi đó không gửi.
            body.unit_cost = unitCost;
        }
    }
    try {
        const res = await apiCall(`/products/${id}/stock`, 'POST', body);
        if (generation !== currentShopGeneration || currentShopId !== shopId) return;
        showToast(t(
            delta > 0 ? 'seller.products.stock_updated_in' : 'seller.products.stock_updated_out',
            { stock: dinhDangSoSeller(res.stock) }
        ));
        loadProducts();
    } catch(e) {
        if (generation === currentShopGeneration && currentShopId === shopId) {
            showToast(e.message);
        }
    }
}

// ===== Quét mã vạch ở màn Kho hàng =====

/** Tab Kho hàng đang mở và đang hiện phần sản phẩm (không phải phần danh mục). */
function _khoHangDangMo() {
    const tab = document.getElementById('warehouse');
    if (!tab || !tab.classList.contains('active')) return false;
    const noiDung = document.getElementById('warehouseContent');
    if (!noiDung || noiDung.style.display === 'none') return false;
    const phanSP = document.getElementById('warehouseProductsSection');
    return !!phanSP && phanSP.style.display !== 'none';
}

function xuLyQuetKho(ma) {
    // Con trỏ đang nằm trong ô mã vạch của form: người dùng đang muốn GÁN mã cho
    // sản phẩm, không phải nhập/xuất kho. Đây là cách phân biệt hai ý định mà
    // không cần thêm nút bật/tắt chế độ.
    const oMaVach = document.getElementById('prodBarcode');
    if (oMaVach && document.activeElement === oMaVach) {
        oMaVach.value = ma;
        BarcodeScanner.bipOk();
        return;
    }

    if (!_khoHangDangMo()) {
        BarcodeScanner.bipLoi();
        showToast(t('seller.products.open_warehouse_to_scan'));
        return;
    }
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;

    // Mã vạch và mã nội bộ đều duy nhất theo shop, nên khớp được là chắc chắn.
    const sp = currentProducts.find(p => p.barcode && p.barcode.toUpperCase() === ma)
        || currentProducts.find(p => p.code && p.code.toUpperCase() === ma);
    if (!sp) {
        BarcodeScanner.bipLoi();
        showToast(t('seller.products.not_found_by_code', { code: ma }));
        return;
    }
    BarcodeScanner.bipOk();
    nhapXuatKho(sp.id);
}

// ===== Kiểm kê =====

// Phiếu đếm đang mở: product_id -> { counted, stock_snapshot, name }
// `stock_snapshot` là tồn kho lúc sản phẩm này được đếm LẦN ĐẦU. Server so lại
// với tồn hiện tại lúc áp dụng; lệch nghĩa là có bán/nhập xen vào giữa và dòng
// đó bị bỏ qua thay vì ghi đè làm mất số hàng vừa bán.
let phieuKiemKe = {};

function _kiemKeDangMo() {
    const tab = document.getElementById('kiemke');
    return !!tab && tab.classList.contains('active');
}

function kkDem(sp, soLuong) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const cu = phieuKiemKe[sp.id];
    if (cu) {
        cu.counted += soLuong;
        if (cu.counted < 0) cu.counted = 0;
    } else {
        phieuKiemKe[sp.id] = {
            counted: Math.max(0, soLuong),
            stock_snapshot: sp.stock,
            name: sp.name
        };
    }
    kkVeBang();
}

function kkDatSo(id, giaTri) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const dong = phieuKiemKe[id];
    if (!dong) return;
    const n = parseInt(giaTri, 10);
    dong.counted = (isNaN(n) || n < 0) ? 0 : n;
    kkVeBang();
}

function kkBo(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    delete phieuKiemKe[id];
    kkVeBang();
}

function kkXoaHet() {
    phieuKiemKe = {};
    const kq = document.getElementById('kkKetQua');
    if (kq) kq.style.display = 'none';
    kkVeBang();
}

function kkVeBang() {
    const tbody = document.getElementById('kkList');
    if (!tbody) return;
    const cacDong = Object.entries(phieuKiemKe);
    tbody.innerHTML = '';

    let thieu = 0, thua = 0, khop = 0;
    cacDong.forEach(([id, d]) => {
        const lech = d.counted - d.stock_snapshot;
        if (lech < 0) thieu++; else if (lech > 0) thua++; else khop++;
        const mau = lech < 0 ? '#ef4444' : (lech > 0 ? 'var(--success)' : '#94A3B8');
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(d.name)}</td>
            <td>${dinhDangSoSeller(d.stock_snapshot)}</td>
            <td><input type="number" min="0" value="${d.counted}" onchange="kkDatSo(${id}, this.value)"
                       style="width:80px; padding:0.3rem; border-radius:6px; border:1px solid #334155; background:#0F172A; color:#F8FAFC;"></td>
            <td style="color:${mau}; font-weight:600;">${lech > 0 ? '+' : ''}${lech}</td>
            <td><button class="btn-outline" onclick="kkBo(${id})" style="padding:0.2rem 0.5rem; color:#ef4444;"><i class="ph ph-x"></i></button></td>
        </tr>`;
    });

    document.getElementById('kkSoSP').innerText = dinhDangSoSeller(cacDong.length);
    document.getElementById('kkSoThieu').innerText = dinhDangSoSeller(thieu);
    document.getElementById('kkSoThua').innerText = dinhDangSoSeller(thua);
    document.getElementById('kkSoKhop').innerText = dinhDangSoSeller(khop);
    document.getElementById('kkBtnApDung').disabled = cacDong.length === 0;
}

/** Tìm SP theo mã rồi cộng 1 vào phiếu đếm. */
function kkQuet(ma) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const sp = currentProducts.find(p => p.barcode && p.barcode.toUpperCase() === ma)
        || currentProducts.find(p => p.code && p.code.toUpperCase() === ma);
    if (!sp) {
        BarcodeScanner.bipLoi();
        showToast(t('seller.products.not_found_by_code', { code: ma }));
        return;
    }
    BarcodeScanner.bipOk();
    kkDem(sp, 1);
}

function kkNhapMaTay() {
    const o = document.getElementById('kkNhapTay');
    const ma = BarcodeScanner.chuanHoa(o.value);
    if (!ma) return;
    o.value = '';
    kkQuet(ma);
}

function kkQuetCamera() {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    // Để mở để quét liên tiếp cả kệ hàng, không phải bấm lại từng lần.
    BarcodeCamera.mo();
}

async function kkApDung() {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const items = Object.entries(phieuKiemKe).map(([id, d]) => ({
        product_id: parseInt(id, 10),
        counted: d.counted,
        stock_snapshot: d.stock_snapshot
    }));
    if (!items.length) return;

    const soLech = items.filter(i => i.counted !== i.stock_snapshot).length;

    // Nêu thẳng mức thay đổi của TỔNG tồn kho. Chỉ nói "N sản phẩm bị lệch" là
    // không đủ: quét thử mỗi món một lần rồi bấm Áp dụng sẽ đặt tồn về 1 cho
    // tất cả, tổng tồn có thể tụt từ vài trăm xuống vài đơn vị mà con số đó
    // không hiện ra ở đâu cả.
    const tongTon = items.reduce((s, i) => s + i.stock_snapshot, 0);
    const tongDem = items.reduce((s, i) => s + i.counted, 0);
    const chenh = tongDem - tongTon;
    const moTaChenh = chenh === 0
        ? t('seller.stocktake.no_change')
        : t(
            chenh < 0 ? 'seller.stocktake.decrease' : 'seller.stocktake.increase',
            { amount: dinhDangSoSeller(Math.abs(chenh)) }
        );

    showCustomConfirm(
        t('seller.stocktake.confirm_title', {
            count: dinhDangSoSeller(items.length)
        }),
        t('seller.stocktake.confirm_message', {
            stock: dinhDangSoSeller(tongTon),
            counted: dinhDangSoSeller(tongDem),
            change: moTaChenh,
            different: dinhDangSoSeller(soLech)
        }),
        async () => {
            if (
                generation !== currentShopGeneration
                || currentShopId !== shopId
                || !damBaoCacheShopHienTai(currentProductsShopId)
            ) return;
            try {
                const res = await apiCall(`/products/${shopId}/stocktake`, 'POST', { items });
                if (generation !== currentShopGeneration || currentShopId !== shopId) return;
                kkHienKetQua(res);
                phieuKiemKe = {};
                kkVeBang();
                loadProducts();
            } catch (e) {
                if (generation === currentShopGeneration && currentShopId === shopId) {
                    showToast(e.message);
                }
            }
        },
        t('seller.stocktake.apply')
    );
}

function kkHienKetQua(res) {
    const box = document.getElementById('kkKetQua');
    const boQua = res.bo_qua || [];
    box.style.display = 'block';
    box.style.background = boQua.length ? '#422006' : '#052e16';
    box.style.border = `1px solid ${boQua.length ? '#a16207' : '#15803d'}`;
    box.style.color = '#F8FAFC';

    const tongLech = `${res.tong_lech > 0 ? '+' : ''}${dinhDangSoSeller(res.tong_lech)}`;
    let html = `<b>${escapeHtml(t('seller.stocktake.result', {
        adjusted: dinhDangSoSeller(res.da_dieu_chinh.length),
        difference: tongLech,
        matched: dinhDangSoSeller(res.khong_doi)
    }))}</b>`;
    if (boQua.length) {
        html += `<br><b style="color:#fbbf24;">${escapeHtml(t('seller.stocktake.skipped', {
            count: dinhDangSoSeller(boQua.length)
        }))}</b><ul style="margin:0.4rem 0 0 1.1rem;">`
            + boQua.map(b => `<li>${escapeHtml(b.name || t('seller.stocktake.product_fallback', { id: b.product_id }))}: ${escapeHtml(b.ly_do)}</li>`).join('')
            + `</ul>`;
    }
    box.innerHTML = html;
    showToast(t(boQua.length ? 'seller.stocktake.done_skipped' : 'seller.stocktake.done'));
}

// ===== Định tuyến lượt quét theo tab đang mở =====

/** Máy quét USB bắt ở tầm document nên phải tự phân biệt người dùng đang ở đâu. */
function xuLyQuetSeller(ma) {
    if (_kiemKeDangMo()) return kkQuet(ma);
    return xuLyQuetKho(ma);
}

BarcodeScanner.batDau(xuLyQuetSeller);

/** Nút camera cạnh ô mã vạch: quét xong điền thẳng vào ô, không đụng tồn kho.
 *  Phải truyền handler riêng vì camera mở lên là ô mất focus, nên `xuLyQuetKho`
 *  không còn suy ra được ý định "đang gán mã" như khi dùng máy quét USB. */
function quetMaVachBangCamera() {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    BarcodeCamera.mo({
        dongSauKhiQuet: true,
        xuLy: (ma) => {
            if (generation !== currentShopGeneration || currentShopId !== shopId) return;
            document.getElementById('prodBarcode').value = ma;
            BarcodeScanner.bipOk();
            showToast(t('seller.products.barcode_filled', { code: ma }));
        }
    });
}

/** Nút camera trên danh sách: quét xong mở hộp nhập/xuất kho cho SP đó. */
function quetNhapXuatBangCamera() {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    BarcodeCamera.mo({ dongSauKhiQuet: true });
}

function deleteProduct(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    const product = currentProducts.find(item => Number(item.id) === Number(id));
    if (!product) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    showCustomConfirm(
        t('seller.products.delete_title'),
        t('seller.products.delete_confirm'),
        async () => {
            if (
                generation !== currentShopGeneration
                || currentShopId !== shopId
                || !damBaoCacheShopHienTai(currentProductsShopId)
            ) return;
            try {
                await apiCall(`/products/${id}`, 'DELETE');
                if (generation !== currentShopGeneration || currentShopId !== shopId) return;
                showToast(t('seller.products.deleted'));
                loadProducts();
            } catch(e) {
                if (generation === currentShopGeneration && currentShopId === shopId) {
                    showToast(e.message);
                }
            }
        }
    );
}

async function toggleProductStatus(id) {
    if (!damBaoCacheShopHienTai(currentProductsShopId)) return;
    if (!currentProducts.some(item => Number(item.id) === Number(id))) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    try {
        await apiCall(`/products/${id}/status`, 'PUT');
        if (generation !== currentShopGeneration || currentShopId !== shopId) return;
        showToast(t('seller.products.status_updated'));
        loadProducts();
    } catch(e) {
        if (generation === currentShopGeneration && currentShopId === shopId) {
            showToast(e.message);
        }
    }
}

async function createProduct() {
    if(!currentShopId) return;
    if (
        !damBaoCacheShopHienTai(currentProductsShopId)
        || !damBaoCacheShopHienTai(currentCategoriesShopId)
    ) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const catSelect = document.getElementById('catSelect');
    if(!catSelect || !catSelect.value) {
        return showToast(t('seller.products.category_required'));
    }
    const formData = new FormData();
    formData.append('code', document.getElementById('prodCode').value);
    // Luôn gửi, kể cả khi rỗng: backend phân biệt "không gửi" (giữ mã vạch cũ)
    // với "gửi rỗng" (xóa mã vạch). Xóa trắng ô phải thực sự gỡ được mã.
    formData.append('barcode', document.getElementById('prodBarcode').value);
    formData.append('name', document.getElementById('prodName').value);
    // Luôn gửi, cùng lý do với mã vạch: rỗng nghĩa là GỠ biến thể để sản phẩm
    // trở lại đơn lẻ. Không gửi thì backend hiểu là giữ nguyên biến thể cũ, và
    // người dùng xóa trắng ô sẽ thấy nó tự hiện lại sau khi lưu.
    formData.append('variant_name', document.getElementById('prodVariant')?.value ?? '');
    const priceStr = document.getElementById('prodPrice').value;
    const stockStr = document.getElementById('prodStock').value;
    
    if(parseFloat(priceStr) <= 0) return showToast(t('seller.products.price_positive'));
    if(parseInt(stockStr) < 0) return showToast(t('seller.products.stock_nonnegative'));

    formData.append('price', priceStr);
    // CHỈ chủ shop mới gửi field này. Nhân viên kho mà gửi kèm (dù rỗng) thì
    // backend hiểu là đang cố sửa giá vốn và trả 403 - cả thao tác sửa tên sản
    // phẩm cũng hỏng theo. Không gửi = giữ nguyên giá vốn đang có.
    if (XEM_DUOC_GIA_VON) {
        const costStr = document.getElementById('prodCost')?.value ?? '';
        if (costStr !== '' && parseFloat(costStr) < 0) {
            return showToast(t('seller.products.cost_nonnegative'));
        }
        // Gửi cả khi rỗng: rỗng nghĩa là XÓA giá vốn, dùng khi khai nhầm.
        formData.append('cost_price', costStr);
    }
    // Chỉ gửi khi TẠO mới: đổi cờ này trên sản phẩm đã có tồn kho sẽ làm tổng
    // lô lệch với tồn (chưa có lô nào mà cờ đã bật), nên form sửa không đụng tới.
    if (editingProductId === null && document.getElementById('prodTrackBatches')?.checked) {
        formData.append('track_batches', 'true');
    }
    formData.append('stock', stockStr);
    formData.append('category_id', catSelect.value);
    const img = document.getElementById('prodImage').files[0];
    if(img) formData.append('image', img);

    try {
        const isEditing = editingProductId !== null;
        const url = isEditing
            ? `/api/products/${editingProductId}`
            : `/api/products?shop_id=${shopId}`;
        const res = await fetch(url, {
            method: isEditing ? 'PUT' : 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Accept-Language': getCurrentLocale()
            },
            body: formData
        });
        if(!res.ok) {
            let errMsg = t('seller.products.save_error');
            try {
                const errData = await res.json();
                if(errData.detail) {
                    let msg = errData.detail;
                    if (Array.isArray(msg) && msg.length > 0 && msg[0].msg) {
                        errMsg = msg[0].msg;
                    } else if (typeof msg === 'object') {
                        errMsg = JSON.stringify(msg);
                    } else {
                        errMsg = msg;
                    }
                }
            } catch(err) {}
            throw new Error(errMsg);
        }
        if (generation !== currentShopGeneration || currentShopId !== shopId) return;
        showToast(t(isEditing ? 'seller.products.updated' : 'seller.products.created'));
        cancelEditProduct();
        loadProducts();
    } catch(e) {
        if (generation === currentShopGeneration && currentShopId === shopId) {
            showToast(e instanceof TypeError ? t('common.network_error') : e.message);
        }
    }
}

let currentVouchers = [];
let editingVoucherId = null;

function renderVouchers(vouchers) {
    const tbody = document.getElementById('voucherList');
    tbody.innerHTML = '';
    vouchers.forEach(v => {
        tbody.innerHTML += `<tr>
            <td><strong>${escapeHtml(v.code)}</strong></td>
            <td>${v.discount_type === 'flat' ? 'VND' : '%'}</td>
            <td>${dinhDangSoSeller(v.discount_value)}</td>
            <td>${dinhDangSoSeller(v.usage_count)}/${v.usage_limit === -1 ? '∞' : dinhDangSoSeller(v.usage_limit)}</td>
            <td style="display:flex; gap:0.3rem;">
                <button class="btn-outline" onclick="editVoucher(${v.id})" style="padding:0.2rem 0.5rem;" title="${escapeHtml(t('common.edit'))}" aria-label="${escapeHtml(t('common.edit'))}"><i class="ph ph-pencil"></i></button>
                <button class="btn-outline" onclick="deleteVoucher(${v.id})" style="padding:0.2rem 0.5rem; color:#ef4444;" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}"><i class="ph ph-trash"></i></button>
            </td>
        </tr>`;
    });
}

async function loadVouchers() {
    if(!currentShopId) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const requestId = ++vouchersRequestId;
    try {
        const vouchers = await apiCall(`/vouchers/${shopId}`);
        if (
            requestId !== vouchersRequestId
            || generation !== currentShopGeneration
            || currentShopId !== shopId
        ) return;
        currentVouchers = vouchers;
        currentVouchersShopId = shopId;
        renderVouchers(vouchers);
    } catch (e) {
        if (
            requestId === vouchersRequestId
            && generation === currentShopGeneration
            && currentShopId === shopId
        ) showToast(e.message);
    }
}

function editVoucher(id) {
    if (!damBaoCacheShopHienTai(currentVouchersShopId)) return;
    const v = currentVouchers.find(x => x.id === id);
    if(!v) return;
    editingVoucherId = id;
    document.getElementById('vCode').value = v.code;
    document.getElementById('vType').value = v.discount_type;
    document.getElementById('vVal').value = v.discount_value;
    document.getElementById('vMin').value = v.min_order_value;
    document.getElementById('vLimit').value = v.usage_limit;
    document.getElementById('btnSaveVoucher').innerHTML = `<i class="ph ph-check-circle"></i> <span data-seller-action-label="voucher-save">${escapeHtml(t('seller.vouchers.update'))}</span>`;
    document.getElementById('btnCancelEditVoucher').style.display = 'block';
}

function cancelEditVoucher() {
    editingVoucherId = null;
    document.getElementById('vCode').value = '';
    document.getElementById('vType').value = 'flat';
    document.getElementById('vVal').value = '';
    document.getElementById('vMin').value = '0';
    document.getElementById('vLimit').value = '-1';
    document.getElementById('btnSaveVoucher').innerHTML = `<i class="ph ph-plus-circle"></i> <span data-seller-action-label="voucher-save">${escapeHtml(t('seller.vouchers.create_code'))}</span>`;
    document.getElementById('btnCancelEditVoucher').style.display = 'none';
}

async function createOrUpdateVoucher() {
    if(!currentShopId) return;
    if (!damBaoCacheShopHienTai(currentVouchersShopId)) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    const voucherId = editingVoucherId;
    const isEditing = voucherId !== null;

    const code = document.getElementById('vCode').value.trim();
    if (!code) {
        return showToast(t('seller.vouchers.code_required_error'));
    }

    const discountType = document.getElementById('vType').value;
    const discountValStr = document.getElementById('vVal').value;
    const minOrderValStr = document.getElementById('vMin').value;
    const limitStr = document.getElementById('vLimit').value;

    if (!discountValStr) {
        return showToast(t('seller.vouchers.value_required_error'));
    }
    const discountVal = parseFloat(discountValStr);
    if (isNaN(discountVal) || discountVal < 1) {
        return showToast(t('seller.vouchers.value_min'));
    }

    if (discountType === 'percentage') {
        if (discountVal <= 0 || discountVal > 100) {
            return showToast(t('seller.vouchers.percent_range'));
        }
    }

    const minOrderVal = parseFloat(minOrderValStr || '0');
    if (isNaN(minOrderVal) || minOrderVal < 0) {
        return showToast(t('seller.vouchers.minimum_nonnegative'));
    }

    const body = {
        code: code.toUpperCase(),
        discount_type: discountType,
        discount_value: discountVal,
        min_order_value: minOrderVal,
        max_discount: 0,
        usage_limit: parseInt(limitStr || '-1')
    };
    try {
        if(isEditing) {
            await apiCall(`/vouchers/${voucherId}`, 'PUT', body);
        } else {
            await apiCall(`/vouchers?shop_id=${shopId}`, 'POST', body);
        }
        if (generation !== currentShopGeneration || currentShopId !== shopId) return;
        showToast(t(isEditing ? 'seller.vouchers.updated' : 'seller.vouchers.created'));
        cancelEditVoucher();
        loadVouchers();
    } catch(e) {
        if (generation === currentShopGeneration && currentShopId === shopId) {
            showToast(e.message);
        }
    }
}

function deleteVoucher(id) {
    if (!damBaoCacheShopHienTai(currentVouchersShopId)) return;
    if (!currentVouchers.some(item => Number(item.id) === Number(id))) return;
    const shopId = currentShopId;
    const generation = currentShopGeneration;
    showCustomConfirm(
        t('seller.vouchers.delete_title'),
        t('seller.vouchers.delete_confirm'),
        async () => {
            if (
                generation !== currentShopGeneration
                || currentShopId !== shopId
                || !damBaoCacheShopHienTai(currentVouchersShopId)
            ) return;
            try {
                await apiCall(`/vouchers/${id}`, 'DELETE');
                if (generation !== currentShopGeneration || currentShopId !== shopId) return;
                showToast(t('seller.vouchers.deleted'));
                loadVouchers();
            } catch(e) {
                if (generation === currentShopGeneration && currentShopId === shopId) {
                    showToast(e.message);
                }
            }
        }
    );
}

async function downloadExcel() {
    if(!dashboardShopId) return showToast(t('seller.export.choose_shop'));
    try {
        const res = await fetch(`/api/export/seller/${dashboardShopId}`, {
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Accept-Language': getCurrentLocale()
            },
            cache: 'no-store'
        });
        if (!res.ok) {
            if (res.status === 403) return showToast(t('seller.export.forbidden'));
            return showToast(t('seller.export.failed'));
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'seller_transactions.xlsx';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        showToast(t('common.network_error'));
    }
}

// ĐỔI MẬT KHẨU
function showChangePasswordModal() {
    document.getElementById('changePasswordModal').style.display = 'flex';
    document.getElementById('changePasswordErrorMsg').innerText = '';
    document.getElementById('changePasswordSuccessMsg').innerText = '';
    document.getElementById('oldPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmNewPassword').value = '';
}

function closeChangePasswordModal() {
    document.getElementById('changePasswordModal').style.display = 'none';
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('changePasswordForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const old_password = document.getElementById('oldPassword').value;
        const new_password = document.getElementById('newPassword').value;
        const confirm = document.getElementById('confirmNewPassword').value;
        const errorMsg = document.getElementById('changePasswordErrorMsg');
        const successMsg = document.getElementById('changePasswordSuccessMsg');
        errorMsg.innerText = '';
        successMsg.innerText = '';
        
        if (new_password !== confirm) {
            errorMsg.innerText = t('seller.password.mismatch');
            return;
        }
        
        const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
        if (!regex.test(new_password)) {
            errorMsg.innerText = t('seller.password.requirements');
            return;
        }
        
        try {
            const res = await apiCall('/auth/change-password', 'POST', { old_password, new_password });
            successMsg.innerText = t('seller.password.success');
            localStorage.setItem('token', res.access_token);
            if (res.staff_role) localStorage.setItem('staff_role', res.staff_role);
            showToast(t('seller.password.success'));
            closeChangePasswordModal();
        } catch (err) {
            errorMsg.innerText = err.message;
        }
    });
});

let confirmCallback = null;

function showCustomConfirm(title, message, onConfirm, confirmLabel = t('common.confirm')) {
    const titleEl = document.getElementById('confirmTitle');
    const msgEl = document.getElementById('confirmMessage');
    const modalEl = document.getElementById('confirmModal');
    const okEl = document.getElementById('btnConfirmOk');
    if (titleEl) titleEl.innerText = title;
    if (msgEl) msgEl.innerText = message;
    if (okEl) {
        okEl.innerHTML = `<i class="ph ph-check-circle"></i> <span data-seller-action-label="confirm-ok">${escapeHtml(confirmLabel)}</span>`;
    }
    confirmCallback = onConfirm;
    if (modalEl) modalEl.style.display = 'flex';
}

function closeCustomConfirm() {
    const modalEl = document.getElementById('confirmModal');
    if (modalEl) modalEl.style.display = 'none';
    confirmCallback = null;
}

const btnCancel = document.getElementById('btnConfirmCancel');
if (btnCancel) btnCancel.onclick = closeCustomConfirm;

const btnOk = document.getElementById('btnConfirmOk');
if (btnOk) {
    btnOk.onclick = () => {
        if (confirmCallback) confirmCallback();
        closeCustomConfirm();
    };
}

// Bắt cả giao dịch chuyển thêm sau khi POS đã xuất hóa đơn và dọn đơn hiện
// tại. Khi tab ẩn chỉ tải 1 dòng để cập nhật badge; khi tab mở tải lại danh sách.
if (coQuyenNhanVien('RECONCILIATION')) {
    setInterval(lamMoiBadgeDoiSoatNen, 30000);
}

// ===== Phân trang + lọc ngày cho danh sách đơn (nhóm B) =====
let trangDonHienTai = 1;
const DON_MOI_TRANG = 50;

function chuoiThamSoNgay() {
    const tu = document.getElementById('filterTuNgay')?.value;
    const den = document.getElementById('filterDenNgay')?.value;
    const p = new URLSearchParams();
    if (tu) p.set('tu_ngay', tu);
    if (den) p.set('den_ngay', den);
    const s = p.toString();
    return s ? `?${s}` : '';
}

function chuoiThamSoDon() {
    const tu = document.getElementById('filterTuNgay')?.value;
    const den = document.getElementById('filterDenNgay')?.value;
    const p = new URLSearchParams({ page: String(trangDonHienTai) });
    p.set('per_page', String(DON_MOI_TRANG));
    if (tu) p.set('tu_ngay', tu);
    if (den) p.set('den_ngay', den);
    return `?${p.toString()}`;
}

function capNhatDieuKhienTrang(res) {
    const info = document.getElementById('thongTinTrang');
    const truoc = document.getElementById('btnTrangTruoc');
    const sau = document.getElementById('btnTrangSau');
    if (!info) return;

    const tong = res.total_orders ?? res.orders.length;
    if (tong === 0) {
        info.innerText = t('seller.pagination.no_orders_in_range');
    } else {
        const dau = (res.page - 1) * res.per_page + 1;
        const cuoi = Math.min(res.page * res.per_page, tong);
        info.innerText = t('seller.pagination.showing_orders', {
            from: dinhDangSoSeller(dau),
            to: dinhDangSoSeller(cuoi),
            total: dinhDangSoSeller(tong)
        });
    }
    if (truoc) truoc.disabled = res.page <= 1;
    if (sau) sau.disabled = !res.has_more;
}

function doiTrang(buoc) {
    const moi = trangDonHienTai + buoc;
    if (moi < 1) return;
    trangDonHienTai = moi;
    if (dashboardShopId) loadDashboardShop(dashboardShopId);
}

function apDungLocNgay() {
    const tu = document.getElementById('filterTuNgay').value;
    const den = document.getElementById('filterDenNgay').value;
    if (tu && den && tu > den) return showToast(t('seller.dashboard.date_range_invalid'));
    trangDonHienTai = 1;
    if (dashboardShopId) loadDashboardShop(dashboardShopId);
}

function xoaLocNgay() {
    document.getElementById('filterTuNgay').value = '';
    document.getElementById('filterDenNgay').value = '';
    trangDonHienTai = 1;
    if (dashboardShopId) loadDashboardShop(dashboardShopId);
}

// ===== Xem chi tiết đơn (nhóm B + D4 đối soát) =====

function nhanLoaiButToan(entryType) {
    const nhan = {
        BANK_IN: t('seller.ledger.bank_in'),
        CASH_TOPUP: t('seller.ledger.cash_topup'),
        REFUND_CASH: t('seller.ledger.refund_cash'),
        REFUND_TRANSFER: t('seller.ledger.refund_transfer')
    };
    return nhan[entryType] || entryType || t('seller.ledger.transaction');
}

function nhanGhiChuButToan(note) {
    const value = String(note || '');
    if (value === 'SYSTEM_POS_CASH_TOPUP' || value === 'Thu bù tại quầy POS') {
        return t('seller.order_detail.system_pos_cash_topup');
    }
    return value;
}

function veChiTietDoiSoat(d) {
    const box = document.getElementById('odDoiSoat');
    const tomTat = document.getElementById('odDoiSoatTomTat');
    const paymentSection = document.getElementById('odThanhToanSection');
    const paymentList = document.getElementById('odThanhToanList');
    if (!box || !tomTat || !paymentSection || !paymentList) return;

    const reason = d.reconciliation_reason;
    if (!reason && !d.reconciliation_pending) {
        box.style.display = 'none';
        tomTat.innerHTML = '';
        paymentSection.style.display = 'none';
        paymentList.innerHTML = '';
        return;
    }

    const meta = thongTinLoaiDoiSoat(reason);
    let chenhLech = `${escapeHtml(t('seller.reconciliation.received'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.received_amount))}</strong>`;
    if (reason === 'UNDERPAID') {
        chenhLech = `${escapeHtml(t('seller.reconciliation.remaining'))}: <strong style="color:#B45309;">${escapeHtml(dinhDangTienDoiSoat(d.remaining_amount))}</strong>`;
    } else if (reason === 'OVERPAID' || reason === 'LATE_PAYMENT') {
        chenhLech = `${escapeHtml(t('seller.reconciliation.refund_customer'))}: <strong style="color:#B91C1C;">${escapeHtml(dinhDangTienDoiSoat(d.refund_due_amount))}</strong>`;
    }

    tomTat.innerHTML = `
        <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start; flex-wrap:wrap;">
            <strong>${escapeHtml(meta.title)}</strong>
            <span class="doi-soat-state ${meta.stateClass}">${escapeHtml(meta.stateLabel)}</span>
        </div>
        <div class="doi-soat-detail-summary-grid">
            <div>${escapeHtml(t('seller.reconciliation.order_total'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.total_amount))}</strong></div>
            <div>${chenhLech}</div>
            <div>${escapeHtml(t('seller.reconciliation.bank_amount'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.bank_paid_amount))}</strong></div>
            <div>${escapeHtml(t('seller.reconciliation.cash_topup'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.cash_paid_amount))}</strong></div>
        </div>
        <p style="margin:0.65rem 0 0; color:var(--text-muted); font-size:0.8rem; line-height:1.5;">${escapeHtml(meta.note)}</p>`;

    const payments = Array.isArray(d.payments) ? d.payments : [];
    paymentSection.style.display = payments.length ? 'block' : 'none';
    paymentList.innerHTML = payments.map(payment => {
        const entryType = String(payment.entry_type || '');
        const laHoan = entryType === 'REFUND_CASH' || entryType === 'REFUND_TRANSFER';
        const metaParts = [];
        if (payment.created_at) metaParts.push(dinhDangNgayGio(payment.created_at));
        if (payment.bank_txn_id) {
            metaParts.push(t('seller.order_detail.bank_transaction', {
                value: payment.bank_txn_id
            }));
        }
        if (payment.reference) {
            metaParts.push(t('seller.order_detail.reference', {
                value: payment.reference
            }));
        }
        if (payment.note) {
            metaParts.push(t('seller.order_detail.note', {
                value: nhanGhiChuButToan(payment.note)
            }));
        }
        return `
            <div class="doi-soat-payment-row">
                <strong>${escapeHtml(nhanLoaiButToan(entryType))}</strong>
                <strong style="text-align:right; color:${laHoan ? '#B91C1C' : '#166534'};">
                    ${laHoan ? '− ' : '+ '}${dinhDangTienDoiSoat(payment.amount)}
                </strong>
                <div class="doi-soat-payment-meta">${escapeHtml(metaParts.join(' · '))}</div>
            </div>`;
    }).join('');

    if (!payments.length && reason === 'LEGACY_REVIEW') {
        paymentSection.style.display = 'block';
        paymentList.innerHTML = `<div style="color:var(--text-muted); font-size:0.82rem;">${escapeHtml(t('seller.order_detail.no_ledger'))}</div>`;
    }
    box.style.display = 'block';
}

function renderChiTietDon(d) {
    document.getElementById('odMaDon').innerText = `#${d.id}`;

    const tt = window.moTaTrangThaiDon(d.status);
    const ngay = dinhDangNgayGio(d.created_at);
    const coChuyenKhoan = Number(d.bank_paid_amount || 0) > 0;
    const coTienMat = Number(d.cash_paid_amount || 0) > 0;
    const pttt = coChuyenKhoan && coTienMat
        ? t('seller.order_detail.mixed_payment', {
            defaultValue: 'Chuyển khoản + tiền mặt'
        })
        : t(coChuyenKhoan ? 'common.payment.transfer' : 'common.payment.cash');
    document.getElementById('odThongTin').innerText =
        `${ngay} • ${pttt} • ${tt.label}`;

    const khachHang = document.getElementById('odKhachHang');
    if (d.customer) {
        khachHang.innerText = t('seller.order_detail.customer', {
            name: d.customer.name,
            phone: d.customer.phone
        });
        khachHang.style.display = 'block';
    } else {
        khachHang.innerText = '';
        khachHang.style.display = 'none';
    }
    veChiTietDoiSoat(d);

    const tbody = document.getElementById('odDanhSach');
    tbody.innerHTML = '';
    (d.items || []).forEach(i => {
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(i.product_name)}</td>
            <td style="text-align:right;">${escapeHtml(dinhDangTienDoiSoat(i.price || 0))}</td>
            <td style="text-align:right;">${escapeHtml(dinhDangSoSeller(i.quantity))}</td>
            <td style="text-align:right;">${escapeHtml(dinhDangTienDoiSoat(i.line_total || 0))}</td>
        </tr>`;
    });

    let tongKet = `<div>${escapeHtml(t('seller.order_detail.subtotal'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.subtotal || 0))}</strong></div>`;
    if (d.discount_amount > 0) {
        const ma = d.voucher_code ? ` (${d.voucher_code})` : '';
        tongKet += `<div style="color: #F59E0B;">${escapeHtml(t('seller.order_detail.discount', { code: ma }))}: −${escapeHtml(dinhDangTienDoiSoat(d.discount_amount))}</div>`;
    }
    tongKet += `<div style="font-size: 1.2rem; margin-top: 0.5rem;">${escapeHtml(t('seller.order_detail.grand_total'))}: <strong>${escapeHtml(dinhDangTienDoiSoat(d.total_amount || 0))}</strong></div>`;
    document.getElementById('odTongKet').innerHTML = tongKet;
    veLichSuTraHang(d);

    document.getElementById('orderDetailModal').style.display = 'flex';
}

/** Lịch sử khách trả hàng của đơn, hiện ngay dưới phần tổng kết.
 *
 *  Chỉ ĐỌC. Việc nhận trả nằm ở POS - đó mới là chỗ thu ngân đứng khi khách
 *  mang hàng đến, và là nơi có ca thu ngân để trừ tiền mặt ra khỏi két. */
function veLichSuTraHang(d) {
    const khoi = document.getElementById('odTraHang');
    if (!khoi) return;
    const phieu = d.returns || [];
    if (!phieu.length) {
        khoi.style.display = 'none';
        khoi.innerHTML = '';
        return;
    }

    let html = `<div style="border-top:1px solid var(--border-color); padding-top:0.75rem;">
        <strong style="color:#B91C1C;">${escapeHtml(t('seller.order_detail.returns_title'))}</strong>
        <div style="margin-top:0.35rem; font-weight:600;">
            ${escapeHtml(t('seller.order_detail.returned_total', {
                amount: dinhDangTienDoiSoat(d.returned_total || 0)
            }))}
        </div>`;
    phieu.forEach(p => {
        const cach = p.refund_method
            ? t(p.refund_method === 'cash'
                ? 'common.payment.cash'
                : 'common.payment.transfer')
            : '—';
        html += `<div style="margin-top:0.5rem; font-size:0.85rem; color:#475569;">
            <div>${escapeHtml(dinhDangNgayGio(p.created_at))} • ${escapeHtml(cach)}
                • <strong>${escapeHtml(dinhDangTienDoiSoat(p.refund_amount || 0))}</strong></div>`;
        (p.items || []).forEach(i => {
            // Nói rõ dòng nào KHÔNG quay lại kho: đó là hàng hỏng, và là phần
            // chênh giữa tiền hoàn với vốn thu hồi được trong báo cáo lãi.
            const kho = i.restocked
                ? ''
                : ` <span style="color:#B45309;">(${escapeHtml(t('seller.order_detail.not_restocked'))})</span>`;
            html += `<div style="padding-left:0.75rem;">• ${escapeHtml(i.product_name || '')}
                × ${escapeHtml(dinhDangSoSeller(i.quantity))}${kho}</div>`;
        });
        if (p.reason) {
            html += `<div style="padding-left:0.75rem; font-style:italic;">${escapeHtml(p.reason)}</div>`;
        }
        html += '</div>';
    });
    html += '</div>';
    khoi.innerHTML = html;
    khoi.style.display = 'block';
}

async function xemChiTietDon(orderId) {
    try {
        const d = await apiCall(`/orders/${orderId}/detail`);
        openOrderDetailId = Number(orderId);
        orderDetailCache = d;
        renderChiTietDon(d);
    } catch (e) { showToast(e.message); }
}

function dongChiTietDon() {
    document.getElementById('orderDetailModal').style.display = 'none';
    openOrderDetailId = null;
}


// ===== Cài đặt Đọc tiền (nằm ở tab Cài Đặt, không ở POS) =====

function dtLuuBat() {
    DocTien.datBat(document.getElementById('dtBat').checked);
    dtCapNhatHien();
}

function dtCapNhatHien() {
    document.getElementById('dtChiTiet').style.display =
        document.getElementById('dtBat').checked ? 'block' : 'none';
}

function dtKhoiTao() {
    const bat = document.getElementById('dtBat');
    if (!bat || typeof DocTien === 'undefined') return;
    bat.checked = DocTien.dangBat();
    dtCapNhatHien();
}

// ===== C1d: phân biệt vai trò SELLER / STAFF trên giao diện =====
function applyRoleUI() {
    if (!XEM_DUOC_GIA_VON) {
        // Ô giá vốn ở form sản phẩm. Nhân viên kho vẫn thêm/sửa sản phẩm được,
        // chỉ là không thấy và không gửi field này (xem createProduct).
        const oGiaVon = document.getElementById('prodCostGroup');
        if (oGiaVon) oGiaVon.style.display = 'none';
    }
    if (MY_ROLE !== 'STAFF') return;
    // Nhân viên KHÔNG quản lý cửa hàng, nhưng vẫn phải chỉnh được phần Đọc tiền:
    // họ mới là người đứng quầy POS và nghe cái loa đó. Nên giữ tab Cài Đặt,
    // chỉ giấu phần cấu hình cửa hàng bên dưới.
    document.querySelectorAll('#settings > *').forEach(el => {
        if (el.id !== 'khoiDocTien') el.style.display = 'none';
    });

    const allowedTabs = {
        CASHIER: new Set(['customers', 'settings']),
        WAREHOUSE: new Set(['warehouse', 'kiemke', 'settings']),
        MANAGER: new Set([
            'dashboard', 'reconciliation', 'warehouse', 'kiemke',
            'voucher', 'customers', 'settings'
        ])
    }[MY_STAFF_ROLE] || new Set(['settings']);

    document.querySelectorAll('.tab-btn[data-main-tab]').forEach(button => {
        if (!allowedTabs.has(button.dataset.mainTab)) button.style.display = 'none';
    });
    document.querySelectorAll('.tab-content').forEach(section => {
        if (!allowedTabs.has(section.id)) section.style.display = 'none';
    });

    const btnOpenPos = document.getElementById('btnOpenPos');
    if (btnOpenPos && !coQuyenNhanVien('SALE')) btnOpenPos.style.display = 'none';

    const defaultTab = MY_STAFF_ROLE === 'CASHIER'
        ? 'customers'
        : (MY_STAFF_ROLE === 'WAREHOUSE' ? 'warehouse' : 'dashboard');
    switchTab(defaultTab);
}

// ===== C1d: quản lý nhân viên (chỉ chủ shop) =====
function renderStaffShopOptions() {
    const sel = document.getElementById('staffShopSelect');
    if (!sel) return;
    sel.innerHTML = allShops.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    if (allShops.length) loadStaff();
}

function renderStaff(list) {
    const tbody = document.getElementById('staffList');
    tbody.innerHTML = '';
    if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="3" style="color: var(--text-muted);">${escapeHtml(t('seller.staff.empty'))}</td></tr>`;
        return;
    }
    list.forEach(nv => {
        const selectedRole = nv.staff_role || 'MANAGER';
        const staffId = Number(nv.id);
        if (!Number.isInteger(staffId)) return;
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(nv.username)}</td>
            <td>
                <select onchange="capNhatVaiTroNhanVien(${staffId}, this)" style="margin: 0; min-width: 8.5rem;">
                    <option value="CASHIER" ${selectedRole === 'CASHIER' ? 'selected' : ''}>${escapeHtml(t('common.role.cashier'))}</option>
                    <option value="WAREHOUSE" ${selectedRole === 'WAREHOUSE' ? 'selected' : ''}>${escapeHtml(t('common.role.warehouse'))}</option>
                    <option value="MANAGER" ${selectedRole === 'MANAGER' ? 'selected' : ''}>${escapeHtml(t('common.role.manager'))}</option>
                </select>
            </td>
            <td style="text-align:right;">
                <button type="button" class="btn-outline" data-staff-remove-id="${staffId}" style="padding: 0.2rem 0.5rem; color:#ef4444;" title="${escapeHtml(t('seller.actions.stop_account'))}" aria-label="${escapeHtml(t('seller.actions.stop_account'))}"><i class="ph ph-user-minus"></i></button>
            </td>
        </tr>`;
    });
    tbody.querySelectorAll('[data-staff-remove-id]').forEach(button => {
        button.addEventListener('click', () => {
            xoaNhanVien(Number(button.dataset.staffRemoveId));
        });
    });
}

async function loadStaff() {
    const sel = document.getElementById('staffShopSelect');
    if (!sel || !sel.value) return;
    const shopId = Number(sel.value);
    const requestId = ++staffRequestId;
    if (!cacheThuocShop(currentStaffShopId, shopId)) {
        currentStaff = [];
        currentStaffShopId = null;
        renderStaff([]);
    }
    try {
        const list = await apiCall(`/staff/${shopId}`);
        if (requestId !== staffRequestId || Number(sel.value) !== shopId) return;
        currentStaff = list;
        currentStaffShopId = shopId;
        renderStaff(list);
    } catch (e) {
        if (requestId === staffRequestId && Number(sel.value) === shopId) {
            showToast(e.message);
        }
    }
}

async function taoNhanVien() {
    const sel = document.getElementById('staffShopSelect');
    const username = document.getElementById('staffUsername').value.trim();
    const password = document.getElementById('staffPassword').value;
    const staffRole = document.getElementById('staffRole').value;
    if (!sel || !sel.value) return showToast(t('seller.staff.choose_shop'));
    const shopId = damBaoCacheShopTrongSelector(currentStaffShopId, 'staffShopSelect');
    if (!shopId) return;
    if (!username) return showToast(t('seller.staff.username_required'));
    if (!password) return showToast(t('seller.staff.password_required'));
    try {
        await apiCall(`/staff/${shopId}`, 'POST', {
            username,
            password,
            staff_role: staffRole
        });
        if (shopDangChon('staffShopSelect') !== shopId) return;
        showToast(t('seller.staff.added'));
        document.getElementById('staffUsername').value = '';
        document.getElementById('staffPassword').value = '';
        loadStaff();
    } catch (e) {
        if (shopDangChon('staffShopSelect') === shopId) showToast(e.message);
    }
}

async function capNhatVaiTroNhanVien(id, select) {
    const shopId = damBaoCacheShopTrongSelector(currentStaffShopId, 'staffShopSelect');
    if (!shopId) {
        loadStaff();
        return;
    }
    const staff = currentStaff.find(item => Number(item.id) === Number(id));
    if (!staff) return;
    const previousRole = staff?.staff_role;
    if (staff) staff.staff_role = select.value;
    try {
        await apiCall(`/staff/member/${id}/role`, 'PUT', { staff_role: select.value });
        if (shopDangChon('staffShopSelect') === shopId) {
            showToast(t('seller.staff.role_updated'));
        }
    } catch (e) {
        if (
            shopDangChon('staffShopSelect') === shopId
            && cacheThuocShop(currentStaffShopId, shopId)
        ) {
            staff.staff_role = previousRole;
            showToast(e.message);
            loadStaff();
        }
    }
}

function xoaNhanVien(id) {
    const shopId = damBaoCacheShopTrongSelector(currentStaffShopId, 'staffShopSelect');
    if (!shopId) return;
    const staff = currentStaff.find(item => Number(item.id) === Number(id));
    if (!staff) return;
    showCustomConfirm(
        t('seller.staff.stop_title'),
        t('seller.staff.stop_confirm', { username: staff.username }),
        async () => {
            if (
                shopDangChon('staffShopSelect') !== shopId
                || !cacheThuocShop(currentStaffShopId, shopId)
            ) return;
            try {
                await apiCall(`/staff/member/${id}`, 'DELETE');
                if (shopDangChon('staffShopSelect') !== shopId) return;
                showToast(t('seller.staff.stopped'));
                loadStaff();
            } catch (e) {
                if (shopDangChon('staffShopSelect') === shopId) showToast(e.message);
            }
        }
    );
}

// Chạy sau khi DOM và allShops sẵn sàng. init() sẽ gọi renderStaffShopOptions.
applyRoleUI();
dtKhoiTao();


// ===== C2d: quản lý khách hàng (CRM) =====
let editingCustomerId = null;

function renderCustomerShopOptions() {
    const sel = document.getElementById('custShopSelect');
    if (!sel) return;
    sel.innerHTML = allShops.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    if (allShops.length) loadCustomers();
}

/** Dòng công nợ nhỏ dưới tên khách. Khách không nợ thì không hiện gì cho gọn. */
function dongCongNo(kh) {
    const no = Number(kh.debt_amount || 0);
    if (no <= 0) return '';
    const hanMuc = kh.credit_limit;
    const chamTran = hanMuc !== null && hanMuc !== undefined && no >= Number(hanMuc);
    const mau = chamTran ? '#B91C1C' : '#B45309';
    return `<br><span style="font-size:0.75rem; color:${mau}; font-weight:600;">`
        + `${escapeHtml(t('seller.customers.owes', {
            amount: dinhDangTienDoiSoat(no)
        }))}</span>`;
}

function renderCustomers(list) {
    const tbody = document.getElementById('customerList');
    tbody.innerHTML = '';
    if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="3" style="color: var(--text-muted);">${escapeHtml(t('seller.customers.empty'))}</td></tr>`;
        return;
    }
    list.forEach(kh => {
        const customerId = Number(kh.id);
        if (!Number.isInteger(customerId)) return;
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(kh.name)}${dongCongNo(kh)}</td>
            <td>${escapeHtml(kh.phone)}</td>
            <td style="text-align:right; white-space:nowrap;">
                <button type="button" class="btn-outline" style="padding:0.2rem 0.5rem;" data-customer-history-id="${customerId}" title="${escapeHtml(t('seller.customers.history_action'))}" aria-label="${escapeHtml(t('seller.customers.history_action'))}"><i class="ph ph-clock-counter-clockwise"></i></button>
                <button type="button" class="btn-outline" style="padding:0.2rem 0.5rem;" data-customer-edit-id="${customerId}" title="${escapeHtml(t('common.edit'))}" aria-label="${escapeHtml(t('common.edit'))}"><i class="ph ph-pencil-simple"></i></button>
                <button type="button" class="btn-outline" style="padding:0.2rem 0.5rem; color:#ef4444;" data-customer-delete-id="${customerId}" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}"><i class="ph ph-trash"></i></button>
            </td>
        </tr>`;
    });
    tbody.querySelectorAll('[data-customer-history-id]').forEach(button => {
        button.addEventListener('click', () => {
            xemLichSuKhach(Number(button.dataset.customerHistoryId));
        });
    });
    tbody.querySelectorAll('[data-customer-edit-id]').forEach(button => {
        button.addEventListener('click', () => {
            editCustomer(Number(button.dataset.customerEditId));
        });
    });
    tbody.querySelectorAll('[data-customer-delete-id]').forEach(button => {
        button.addEventListener('click', () => {
            deleteCustomer(Number(button.dataset.customerDeleteId));
        });
    });
}

async function loadCustomers() {
    const sel = document.getElementById('custShopSelect');
    if (!sel || !sel.value) return;
    const shopId = Number(sel.value);
    const q = (document.getElementById('custSearch')?.value || '').trim();
    const requestId = ++customersRequestId;
    if (!cacheThuocShop(currentCustomersShopId, shopId)) {
        window._customersCache = [];
        currentCustomersShopId = null;
        currentCustomersQuery = '';
        renderCustomers([]);
        cancelEditCustomer();
        customerHistoryRequestId += 1;
        customerHistoryCache = null;
        customerHistoryShopId = null;
        dongLichSuKhach();
    }
    try {
        const url = q ? `/customers/${shopId}?q=${encodeURIComponent(q)}` : `/customers/${shopId}`;
        const list = await apiCall(url);
        const currentQuery = (document.getElementById('custSearch')?.value || '').trim();
        if (
            requestId !== customersRequestId
            || Number(sel.value) !== shopId
            || currentQuery !== q
        ) return;
        window._customersCache = list;
        currentCustomersShopId = shopId;
        currentCustomersQuery = q;
        renderCustomers(list);
    } catch (e) {
        const currentQuery = (document.getElementById('custSearch')?.value || '').trim();
        if (
            requestId === customersRequestId
            && Number(sel.value) === shopId
            && currentQuery === q
        ) showToast(e.message);
    }
}

async function saveCustomer() {
    const sel = document.getElementById('custShopSelect');
    const name = document.getElementById('custName').value.trim();
    const phone = document.getElementById('custPhone').value.trim();
    const address = document.getElementById('custAddress').value.trim();
    const note = document.getElementById('custNote').value.trim();
    if (!sel || !sel.value) return showToast(t('seller.staff.choose_shop'));
    const shopId = damBaoCacheShopTrongSelector(currentCustomersShopId, 'custShopSelect');
    if (!shopId) return;
    const customerId = editingCustomerId;
    const isEditing = customerId !== null;
    if (
        isEditing
        && !(window._customersCache || []).some(
            customer => Number(customer.id) === Number(customerId)
        )
    ) return;
    if (!name) return showToast(t('seller.customers.name_required_error'));
    if (!phone) return showToast(t('seller.customers.phone_required_error'));
    // Ô trống = không giới hạn (gửi null), KHÁC HẲN 0 = cấm khách này nợ.
    const hanMucRaw = (document.getElementById('custCreditLimit')?.value || '').trim();
    if (hanMucRaw !== '' && Number(hanMucRaw) < 0) {
        return showToast(t('seller.customers.credit_limit_negative'));
    }
    const body = {
        name, phone, address, note,
        credit_limit: hanMucRaw === '' ? null : Number(hanMucRaw)
    };
    try {
        if (isEditing) {
            await apiCall(`/customers/member/${customerId}`, 'PUT', body);
        } else {
            await apiCall(`/customers/${shopId}`, 'POST', body);
        }
        if (shopDangChon('custShopSelect') !== shopId) return;
        showToast(t(isEditing ? 'seller.customers.updated' : 'seller.customers.added'));
        cancelEditCustomer();
        loadCustomers();
    } catch (e) {
        if (shopDangChon('custShopSelect') === shopId) showToast(e.message);
    }
}

function editCustomer(id) {
    if (!damBaoCacheShopTrongSelector(currentCustomersShopId, 'custShopSelect')) return;
    const kh = (window._customersCache || []).find(c => c.id === id);
    if (!kh) return;
    editingCustomerId = id;
    document.getElementById('custName').value = kh.name || '';
    document.getElementById('custPhone').value = kh.phone || '';
    document.getElementById('custAddress').value = kh.address || '';
    document.getElementById('custNote').value = kh.note || '';
    const oHanMuc = document.getElementById('custCreditLimit');
    // Chưa đặt hạn mức thì để TRỐNG, không điền 0 - 0 mang nghĩa cấm nợ.
    if (oHanMuc) oHanMuc.value = (kh.credit_limit === null || kh.credit_limit === undefined)
        ? '' : kh.credit_limit;
    document.getElementById('custFormTitle').innerText = t('seller.customers.edit_title');
    document.getElementById('btnSaveCustomer').innerHTML = `<i class="ph ph-floppy-disk"></i> <span data-seller-action-label="customer-save">${escapeHtml(t('seller.customers.update'))}</span>`;
    document.getElementById('btnCancelEditCustomer').style.display = 'block';
}

function cancelEditCustomer() {
    editingCustomerId = null;
    ['custName', 'custPhone', 'custAddress', 'custNote', 'custCreditLimit'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('custFormTitle').innerText = t('seller.customers.add_title');
    document.getElementById('btnSaveCustomer').innerHTML = `<i class="ph ph-plus"></i> <span data-seller-action-label="customer-save">${escapeHtml(t('seller.customers.save'))}</span>`;
    document.getElementById('btnCancelEditCustomer').style.display = 'none';
}

function deleteCustomer(id) {
    const shopId = damBaoCacheShopTrongSelector(
        currentCustomersShopId,
        'custShopSelect'
    );
    if (!shopId) return;
    const customer = (window._customersCache || []).find(
        item => Number(item.id) === Number(id)
    );
    if (!customer) return;
    showCustomConfirm(
        t('seller.customers.delete_title'),
        t('seller.customers.delete_confirm', { name: customer.name }),
        async () => {
            if (
                shopDangChon('custShopSelect') !== shopId
                || !cacheThuocShop(currentCustomersShopId, shopId)
            ) return;
            try {
                await apiCall(`/customers/member/${id}`, 'DELETE');
                if (shopDangChon('custShopSelect') !== shopId) return;
                showToast(t('seller.customers.deleted'));
                loadCustomers();
            } catch (e) {
                if (shopDangChon('custShopSelect') === shopId) showToast(e.message);
            }
        }
    );
}

function renderCustomerHistory(d) {
    document.getElementById('chTen').innerText = `${d.customer.name} (${d.customer.phone})`;
    document.getElementById('chTongKet').innerText =
        t('seller.customers.history_summary', {
            count: d.order_count,
            formattedCount: dinhDangSoSeller(d.order_count),
            amount: dinhDangTienDoiSoat(d.total_paid || 0)
        });
    const tbody = document.getElementById('chDanhSach');
    tbody.innerHTML = '';
    if (!d.orders.length) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: var(--text-muted);">${escapeHtml(t('seller.customers.no_orders'))}</td></tr>`;
    } else {
        d.orders.forEach(o => {
            const tt = window.moTaTrangThaiDon(o.status);
            const ngay = dinhDangNgayGio(o.date);
            const conNo = Number(o.remaining || 0);
            const oThuNo = conNo > 0
                ? `<br><button type="button" class="btn-outline" style="padding:0.15rem 0.45rem; font-size:0.75rem; margin-top:0.25rem;" data-debt-order-id="${o.id}" data-debt-remaining="${conNo}">`
                  + `<i class="ph ph-hand-coins"></i> ${escapeHtml(t('seller.customers.collect_debt'))}</button>`
                : '';
            const dongConNo = conNo > 0
                ? `<br><span style="font-size:0.75rem;">${escapeHtml(t('seller.customers.still_owes', {
                    amount: dinhDangTienDoiSoat(conNo)
                  }))}</span>`
                : '';
            tbody.innerHTML += `<tr>
                <td><strong>#${o.id}</strong></td>
                <td>${ngay}</td>
                <td>${escapeHtml(dinhDangTienDoiSoat(o.total || 0))}</td>
                <td style="color:${tt.color}; font-weight:600;">${escapeHtml(tt.label)}${dongConNo}${oThuNo}</td>
            </tr>`;
        });
        tbody.querySelectorAll('[data-debt-order-id]').forEach(nut => {
            nut.addEventListener('click', () => thuNo(
                Number(nut.dataset.debtOrderId),
                Number(nut.dataset.debtRemaining)
            ));
        });
    }
    document.getElementById('customerHistoryModal').style.display = 'flex';
}

/** Thu bớt nợ của một đơn. Trả bao nhiêu cũng được, nên phải hỏi số tiền. */
async function thuNo(orderId, conNo) {
    const raw = prompt(t('seller.customers.collect_prompt', {
        id: orderId,
        remaining: dinhDangTienDoiSoat(conNo)
    }), String(Math.round(conNo)));
    if (raw === null) return;
    const soTien = parseFloat((raw || '').replace(/[.,\s]/g, ''));
    if (!isFinite(soTien) || soTien <= 0) {
        return showToast(t('seller.customers.collect_amount_invalid'));
    }
    if (soTien > conNo) {
        return showToast(t('seller.customers.collect_too_much', {
            remaining: dinhDangTienDoiSoat(conNo)
        }));
    }
    // Hỏi hình thức bằng prompt thứ hai thay vì showCustomConfirm: hàm đó không
    // có callback cho nút Hủy, dùng nó ở đây sẽ treo im lặng khi người dùng bỏ
    // giữa chừng.
    const cachRaw = prompt(t('seller.customers.collect_method_prompt'), 'TM');
    if (cachRaw === null) return;
    const cach = (cachRaw || '').trim().toUpperCase();
    if (!['TM', 'CK'].includes(cach)) {
        return showToast(t('seller.customers.collect_method_invalid'));
    }
    const tienMat = cach === 'TM';
    try {
        const res = await apiCall(`/orders/${orderId}/debt-payment`, 'POST', {
            amount: soTien,
            method: tienMat ? 'cash' : 'transfer',
            // Một mã cho đúng một lần bấm: bấm lại vì mạng chậm không thu hai lần.
            operation_id: taoOperationIdHoanTien()
        });
        showToast(t('seller.customers.collect_done', {
            amount: dinhDangTienDoiSoat(soTien),
            remaining: dinhDangTienDoiSoat(res.remaining_amount || 0)
        }));
        if (openCustomerHistoryId !== null) xemLichSuKhach(openCustomerHistoryId);
        loadCustomers();
    } catch (e) {
        showToast(e.message);
    }
}


async function xemLichSuKhach(id) {
    const shopId = damBaoCacheShopTrongSelector(
        currentCustomersShopId,
        'custShopSelect'
    );
    if (!shopId) return;
    if (!(window._customersCache || []).some(item => Number(item.id) === Number(id))) return;
    const requestId = ++customerHistoryRequestId;
    try {
        const d = await apiCall(`/customers/member/${id}/history`);
        if (
            requestId !== customerHistoryRequestId
            || shopDangChon('custShopSelect') !== shopId
            || !cacheThuocShop(currentCustomersShopId, shopId)
        ) return;
        openCustomerHistoryId = Number(id);
        customerHistoryCache = d;
        customerHistoryShopId = shopId;
        renderCustomerHistory(d);
    } catch (e) {
        if (
            requestId === customerHistoryRequestId
            && shopDangChon('custShopSelect') === shopId
        ) showToast(e.message);
    }
}

function dongLichSuKhach() {
    document.getElementById('customerHistoryModal').style.display = 'none';
    openCustomerHistoryId = null;
    customerHistoryRequestId += 1;
}

const refundModalEl = document.getElementById('refundModal');
if (refundModalEl) {
    refundModalEl.addEventListener('click', event => {
        if (event.target === refundModalEl) dongModalHoanTien();
    });
}

document.addEventListener('keydown', event => {
    if (
        event.key === 'Escape'
        && document.getElementById('refundModal')?.style.display === 'flex'
    ) {
        dongModalHoanTien();
    }
});

function capNhatNhanFormDongSeller() {
    const reconciliationCount = document.getElementById('doiSoatCount');
    if (reconciliationCount) {
        reconciliationCount.innerText = t(
            'seller.reconciliation.waiting_cases',
            {
                count: doiSoatBadgeCount,
                formattedCount: dinhDangSoSeller(doiSoatBadgeCount)
            }
        );
    }
    if (!allShops.length) {
        document.getElementById('statRev').innerText = dinhDangTienDoiSoat(0);
    }

    const shopFormOpen =
        document.getElementById('shopFormContainer')?.style.display !== 'none';
    const shop = allShops.find(item => item.id === editShopId);
    const shopTitleKey = editShopId && shop
        ? 'seller.shops.edit_title'
        : (shopFormOpen ? 'seller.shops.create_title' : 'seller.shops.business_info');
    capNhatNhanNut(
        '[data-seller-action-label="shop-form-title"]',
        shopTitleKey
    );
    const shopTitle = document.querySelector(
        '[data-seller-action-label="shop-form-title"]'
    );
    if (shopTitle && editShopId && shop) {
        shopTitle.textContent = t('seller.shops.edit_title', { name: shop.name });
    }
    capNhatNhanNut(
        '[data-seller-action-label="shop-save"]',
        editShopId ? 'seller.shops.save_update' : (
            shopFormOpen ? 'seller.shops.create_confirm' : 'seller.shops.save_settings'
        )
    );

    document.getElementById('productFormTitle').innerText = t(
        editingProductId === null
            ? 'seller.products.add_title'
            : 'seller.products.edit_title'
    );
    capNhatNhanNut(
        '[data-seller-action-label="product-save"]',
        editingProductId === null ? 'seller.products.save' : 'seller.products.update'
    );
    _khoaOTonKho(editingProductId !== null);

    document.getElementById('catFormTitle').innerText = t(
        editingCategoryId === null
            ? 'seller.categories.add_title'
            : 'seller.categories.edit_title'
    );
    capNhatNhanNut(
        '[data-seller-action-label="category-save"]',
        editingCategoryId === null ? 'seller.categories.save' : 'seller.categories.update'
    );
    capNhatNhanNut(
        '[data-seller-action-label="voucher-save"]',
        editingVoucherId === null ? 'seller.vouchers.create_code' : 'seller.vouchers.update'
    );
    document.getElementById('custFormTitle').innerText = t(
        editingCustomerId === null
            ? 'seller.customers.add_title'
            : 'seller.customers.edit_title'
    );
    capNhatNhanNut(
        '[data-seller-action-label="customer-save"]',
        editingCustomerId === null ? 'seller.customers.save' : 'seller.customers.update'
    );

    const confirmModal = document.getElementById('confirmModal');
    if (confirmModal?.style.display !== 'flex') {
        document.getElementById('confirmTitle').innerText =
            t('seller.confirm.default_title');
        document.getElementById('confirmMessage').innerText =
            t('seller.confirm.default_message');
        capNhatNhanNut(
            '[data-seller-action-label="confirm-ok"]',
            'seller.confirm.delete'
        );
    }

    if (refundOrderId) {
        document.getElementById('refundOrderLabel').innerText =
            refundReason === 'LATE_PAYMENT'
                ? t('seller.refund.cancelled_order', { id: refundOrderId })
                : t('seller.refund.completed_order', { id: refundOrderId });
        document.getElementById('refundAmount').innerText =
            dinhDangTienDoiSoat(refundDueAmount);
    } else {
        document.getElementById('refundAmount').innerText =
            dinhDangTienDoiSoat(0);
    }
    if (!dangLuuHoanTien) {
        capNhatNhanNut(
            '[data-seller-action-label="refund-submit"]',
            'seller.reconciliation.mark_refunded'
        );
    }
    triggerPreview();
}

function capNhatSellerTheoNgonNgu() {
    capNhatNhanFormDongSeller();
    renderBankOptions();
    renderShopsList();
    capNhatBadgeDoiSoat(doiSoatBadgeCount);

    if (currentProductsShopId === currentShopId) {
        filterProducts();
        kkVeBang();
    }
    if (
        coQuyenNhanVien('INVENTORY')
        && currentCategoriesShopId === currentShopId
    ) {
        renderCategories(currentCategories);
    }
    if (
        coQuyenNhanVien('VOUCHER')
        && currentVouchersShopId === currentShopId
    ) {
        renderVouchers(currentVouchers);
    }
    const selectedStaffShopId = Number(
        document.getElementById('staffShopSelect')?.value
    );
    if (
        MY_ROLE !== 'STAFF'
        && currentStaffShopId === selectedStaffShopId
    ) {
        renderStaff(currentStaff);
    }
    const selectedCustomerShopId = Number(
        document.getElementById('custShopSelect')?.value
    );
    const selectedCustomerQuery =
        (document.getElementById('custSearch')?.value || '').trim();
    if (
        coQuyenNhanVien('CUSTOMER')
        && window._customersCache
        && currentCustomersShopId === selectedCustomerShopId
        && currentCustomersQuery === selectedCustomerQuery
    ) {
        renderCustomers(window._customersCache);
    }
    if (
        dashboardOrdersCache
        && dashboardOrdersCache.shopId === dashboardShopId
        && dashboardOrdersCache.key === khoaDashboardOrders(
            dashboardShopId,
            chuoiThamSoDon()
        )
        && coQuyenNhanVien('REPORT')
    ) {
        renderDashboardOrders(dashboardShopId, dashboardOrdersCache.data);
    }
    if (
        dashboardStatsCache
        && dashboardStatsCache.shopId === dashboardShopId
        && dashboardStatsCache.key === khoaDashboardStats(
            dashboardShopId,
            chuoiThamSoNgay()
        )
        && coQuyenNhanVien('REPORT')
    ) {
        renderDashboardStats(dashboardStatsCache.data);
    }
    if (
        shiftHistoryCache
        && shiftHistoryCache.shopId === dashboardShopId
        && coQuyenNhanVien('REPORT')
    ) {
        renderShiftHistory(shiftHistoryCache.data);
    }
    if (document.getElementById('reconciliation')?.classList.contains('active')) {
        if (!doiSoatShopId) {
            renderDoiSoatKhongCoShop();
        } else if (
            reconciliationCache
            && reconciliationCache.shopId === doiSoatShopId
        ) {
            renderDoiSoatResponse(reconciliationCache.data);
        }
    }
    if (
        openOrderDetailId
        && orderDetailCache
        && Number(orderDetailCache.id) === openOrderDetailId
    ) {
        renderChiTietDon(orderDetailCache);
    }
    if (
        openCustomerHistoryId
        && customerHistoryCache
        && customerHistoryShopId === selectedCustomerShopId
        && Number(customerHistoryCache.customer?.id) === openCustomerHistoryId
    ) {
        renderCustomerHistory(customerHistoryCache);
    }
}

document.addEventListener('fselling:localechange', capNhatSellerTheoNgonNgu);
capNhatNhanFormDongSeller();
init();
