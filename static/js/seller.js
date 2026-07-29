// Chủ shop (SELLER) và nhân viên (STAFF) đều dùng trang này. Vai trò quyết định
// những gì được hiển thị (xem applyRoleUI ở cuối file).
const MY_ROLE = localStorage.getItem('role');
if(MY_ROLE !== 'SELLER' && MY_ROLE !== 'STAFF') window.location.href = '/';

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

function renderBankOptions() {
    const bankSelect = document.getElementById('bankCode');
    if (!bankSelect) return;
    bankSelect.innerHTML = `<option value="" disabled selected>Chọn ngân hàng</option>` +
        BANKS.map(bank => `<option value="${bank.code}">${bank.label}</option>`).join('');
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
}

// Live Preview Logic
document.getElementById('shopName').addEventListener('input', e => document.getElementById('previewCardName').innerText = e.target.value || 'Tên cửa hàng');
document.getElementById('shopTaxCode').addEventListener('input', e => document.getElementById('previewCardTaxCode').innerText = e.target.value || 'Chưa có');
document.getElementById('shopAddress').addEventListener('input', e => document.getElementById('previewCardAddress').innerText = e.target.value || 'Chưa có');

async function init() {
    try {
        allShops = await apiCall('/shops');
        renderShopsList(); // Cho phần cài đặt
        // Danh sách nhân viên chỉ dành cho chủ shop (nhân viên gọi sẽ bị 404).
        if (MY_ROLE !== 'STAFF') renderStaffShopOptions();
        // Khách hàng: cả chủ shop lẫn nhân viên đều quản lý được.
        renderCustomerShopOptions();

        if(allShops.length === 0) {
            document.getElementById('dashboardContent').style.display = 'none';
            document.getElementById('noShopMsg').style.display = 'block';
            openCreateShopForm();
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
    } catch(e) { showToast(e.message); }

    renderBankOptions();
}

function renderShopSelectors() {
    const dashList = document.getElementById('dashShopList');
    const whList = document.getElementById('whShopList');
    const vouList = document.getElementById('vouShopList');
    const posList = document.getElementById('posShopList');
    
    dashList.innerHTML = '';
    if(whList) whList.innerHTML = '';
    if(vouList) vouList.innerHTML = '';
    if(posList) posList.innerHTML = '';
    
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
            btn2.onclick = () => { currentShopId = s.id; loadDataForCurrentShop(); };
            whList.appendChild(btn2);
        }

        // Kiểm kê
        const kkList = document.getElementById('kkShopList');
        if(kkList) {
            const btnKK = document.createElement('button');
            btnKK.className = currentShopId === s.id ? 'btn-primary' : 'btn-outline';
            btnKK.innerText = s.name;
            btnKK.onclick = () => { currentShopId = s.id; loadDataForCurrentShop(); };
            kkList.appendChild(btnKK);
        }

        // Voucher
        if(vouList) {
            const btn3 = document.createElement('button');
            btn3.className = currentShopId === s.id ? 'btn-primary' : 'btn-outline';
            btn3.innerText = s.name;
            btn3.onclick = () => { currentShopId = s.id; loadDataForCurrentShop(); };
            vouList.appendChild(btn3);
        }
        
        // POS
        if(posList) {
            posList.innerHTML += `<button style="width: 100%; padding: 1rem; text-align: left; display: flex; align-items: center; gap: 0.5rem;" onclick="goToPOS(${s.id})"><i class="ph ph-storefront"></i> ${escapeHtml(s.name)}</button>`;
        }
    });
}

function openPosShopSelector() {
    if(allShops.length === 0) return showToast("Vui lòng tạo cửa hàng trước!");
    document.getElementById('posModal').style.display = 'flex';
}

async function loadDashboardShop(id) {
    dashboardShopId = id;
    try {
        // Lấy thông tin shop
        const shop = allShops.find(s => s.id === id);
        document.getElementById('currentShopName').innerText = shop ? shop.name : '';

        // Đơn hàng: phân trang + lọc theo khoảng ngày
        const res = await apiCall(`/dashboard/seller/${id}${chuoiThamSoDon()}`);
        const tbody = document.getElementById('orderList');
        tbody.innerHTML = '';
        res.orders.forEach(o => {
            const hienThi = window.moTaTrangThaiDon(o.status);
            const dt = dinhDangNgayGio(o.date);
            tbody.innerHTML += `<tr>
                <td><strong>#${o.id}</strong></td>
                <td>${dt}</td>
                <td>${o.total.toLocaleString()} ₫</td>
                <td style="color: ${hienThi.color}; font-weight: 600;">${escapeHtml(hienThi.label)}</td>
                <td><button class="btn-outline" style="padding: 0.25rem 0.6rem; font-size: 0.8rem;" onclick="xemChiTietDon(${o.id})">Xem</button></td>
            </tr>`;
        });
        capNhatDieuKhienTrang(res);

        // Lấy số liệu thống kê & biểu đồ (API mới)
        const stats = await apiCall(`/shops/${id}/stats${chuoiThamSoNgay()}`);
        
        document.getElementById('statRev').innerText = stats.total_revenue.toLocaleString() + ' ₫';
        document.getElementById('statOrders').innerText = stats.total_orders;
        document.getElementById('statSold').innerText = stats.total_sold;
        
        // Top Products Pie Chart
        const pieCtx = document.getElementById('productPieChart').getContext('2d');
        if (pieChartInstance) pieChartInstance.destroy();
        
        const pieLabels = stats.top_products.map(p => p.name);
        const pieData = stats.top_products.map(p => p.qty);
        const pieColors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];

        pieChartInstance = new Chart(pieCtx, {
            type: 'doughnut',
            data: {
                labels: pieLabels.length ? pieLabels : ['Chưa có dữ liệu'],
                datasets: [{
                    data: pieData.length ? pieData : [1],
                    backgroundColor: pieData.length ? pieColors : ['#E2E8F0'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { boxWidth: 12 } }
                }
            }
        });
        
        // Chart
        const ctx = document.getElementById('revenueChart').getContext('2d');
        if (chartInstance) chartInstance.destroy();
        chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: stats.trend_labels,
                datasets: [{
                    label: 'Doanh thu (VNĐ)',
                    data: stats.trend_data,
                    borderColor: '#3B82F6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });

        document.getElementById('dashboardContent').style.display = 'block';
        // Update UI button selection visually
        const dashList = document.getElementById('dashShopList');
        if(dashList) {
            Array.from(dashList.children).forEach(btn => {
                if(btn.innerText === shop.name) btn.className = 'btn-primary';
                else btn.className = 'btn-outline';
            });
        }
    } catch(e) { showToast(e.message); }
}

function goToPOS(id) {
    localStorage.setItem('currentShopId', id);
    window.location.href = '/pos';
}

function changeShop(id) {
    currentShopId = parseInt(id);
    localStorage.setItem('currentShopId', currentShopId);
    loadDataForCurrentShop();
    showToast("Đã tải dữ liệu Cửa hàng: " + allShops.find(s=>s.id===id).name);
}

function loadDataForCurrentShop() {
    if(allShops.length === 0) return;
    document.getElementById('dashboardContent').style.display = 'block';
    document.getElementById('warehouseContent').style.display = 'grid';
    document.getElementById('voucherContent').style.display = 'grid';
    document.getElementById('kkContent').style.display = 'block';
    document.getElementById('noShopMsg').style.display = 'none';
    
    const shop = allShops.find(s => s.id === currentShopId);
    document.getElementById('currentShopName').innerText = shop.name;
    document.getElementById('whShopName').innerText = shop.name;
    document.getElementById('vcShopName').innerText = shop.name;
    document.getElementById('kkShopName').innerText = shop.name;
    kkXoaHet();   // đổi shop thì phiếu đếm của shop cũ không còn nghĩa lý gì
    
    // Clear inputs for new shop
    document.getElementById('prodCode').value = '';
    document.getElementById('prodBarcode').value = '';
    document.getElementById('prodName').value = '';
    document.getElementById('prodPrice').value = '';
    document.getElementById('prodImage').value = '';
    document.getElementById('catNameInput').value = '';
    
    loadDashboardShop(currentShopId);
    loadCategories();
    loadProducts();
    loadVouchers();
}

// Settings List Render
function renderShopsList() {
    const listDiv = document.getElementById('myShopsList');
    listDiv.innerHTML = '';
    if(allShops.length === 0) {
        listDiv.innerHTML = '<p>Chưa có cửa hàng nào.</p>';
        return;
    }
    allShops.forEach(s => {
        const activeBadge = s.is_active ? '<span style="color:var(--success); font-size: 0.8rem; margin-left: 0.5rem; padding: 2px 6px; background: rgba(16,185,129,0.1); border-radius: 4px;">ACTIVE</span>' : '<span style="color:#ef4444; font-size: 0.8rem; margin-left: 0.5rem; padding: 2px 6px; background: rgba(239,68,68,0.1); border-radius: 4px;">INACTIVE</span>';
        const toggleBtn = `<button class="btn-outline" onclick="toggleShopStatus(${s.id})" style="padding: 0.5rem 1rem; margin-right: 0.5rem;" title="Đổi trạng thái"><i class="ph ph-power"></i></button>`;
        const deleteBtn = `<button class="btn-outline" onclick="deleteShop(${s.id})" style="padding: 0.5rem 1rem; color: #ef4444; margin-left: 0.5rem;" title="Xóa"><i class="ph ph-trash"></i></button>`;
        
        listDiv.innerHTML += `
            <div class="shop-list-card">
                <div>
                    <h4 style="display:flex; align-items:center;">${escapeHtml(s.name)} ${activeBadge}</h4>
                    <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.3rem;"><i class="ph ph-map-pin"></i> ${escapeHtml(s.business_address || 'Chưa cập nhật')}</div>
                </div>
                <div style="display: flex;">
                    ${toggleBtn}
                    <button class="btn-outline" onclick="openEditShopForm(${s.id})" style="padding: 0.5rem 1rem;"><i class="ph ph-pencil"></i> Chỉnh sửa</button>
                    ${deleteBtn}
                </div>
            </div>
        `;
    });
}

async function toggleShopStatus(id) {
    try {
        await apiCall(`/shops/${id}/status`, 'PUT');
        showToast("Đã cập nhật trạng thái cửa hàng!");
        init();
    } catch(e) { showToast(e.message); }
}

function deleteShop(id) {
    showCustomConfirm(
        "Xác nhận xóa cửa hàng",
        "Bạn có chắc muốn xóa vĩnh viễn cửa hàng này và toàn bộ dữ liệu liên quan (sản phẩm, danh mục, voucher, đơn hàng)?",
        async () => {
            try {
                await apiCall(`/shops/${id}`, 'DELETE');
                showToast("Đã xóa cửa hàng thành công!");
                // Clear selected shop if it was the one deleted
                if (currentShopId === id) {
                    currentShopId = null;
                    localStorage.removeItem('currentShopId');
                }
                init();
            } catch(e) { showToast(e.message); }
        }
    );
}

function openCreateShopForm() {
    if(allShops.length >= 3) return showToast("Bạn đã đạt giới hạn 3 cửa hàng!");
    editShopId = null;
    document.getElementById('formTitle').innerHTML = `<i class="ph ph-storefront" style="color: var(--primary);"></i> Tạo Cửa Hàng Mới`;
    document.getElementById('btnSaveShop').innerHTML = `<i class="ph ph-plus-circle"></i> Xác nhận Tạo mới`;
    
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
    document.getElementById('formTitle').innerHTML = `<i class="ph ph-storefront" style="color: var(--primary);"></i> Chỉnh sửa: ${escapeHtml(shop.name)}`;
    document.getElementById('btnSaveShop').innerHTML = `<i class="ph ph-check-circle"></i> Lưu Cập nhật`;
    
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

    if (!name) return showToast("Tên cửa hàng không được để trống!");
    if (!address) return showToast("Địa chỉ kinh doanh không được để trống!");
    if (!taxCode) return showToast("Mã số thuế không được để trống!");
    if (!phone) return showToast("Số điện thoại không được để trống!");
    if (!email) return showToast("Email không được để trống!");
    if (!bankCode) return showToast("Vui lòng chọn ngân hàng!");
    if (!bankAcc) return showToast("Số tài khoản không được để trống!");
    if (!bankAccName) return showToast("Tên chủ tài khoản không được để trống!");

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
            showToast("Cập nhật cửa hàng thành công!");
        } else {
            await apiCall('/shops', 'POST', body);
            showToast("Tạo cửa hàng mới thành công!");
        }
        setTimeout(() => location.reload(), 1000);
    } catch(e) { showToast(e.message); }
}

// --- DASHBOARD / DATA LOGIC ---

function switchWarehouseSubTab(subTab) {
    const prodsBtn = document.getElementById('whSubTabProds');
    const catsBtn = document.getElementById('whSubTabCats');
    const prodsSec = document.getElementById('warehouseProductsSection');
    const catsSec = document.getElementById('warehouseCategoriesSection');
    
    if (subTab === 'products') {
        if (prodsBtn) prodsBtn.classList.add('active');
        if (catsBtn) catsBtn.classList.remove('active');
        if (prodsSec) prodsSec.style.display = 'grid';
        if (catsSec) catsSec.style.display = 'none';
    } else {
        if (prodsBtn) prodsBtn.classList.remove('active');
        if (catsBtn) catsBtn.classList.add('active');
        if (prodsSec) prodsSec.style.display = 'none';
        if (catsSec) catsSec.style.display = 'grid';
    }
}

async function loadCategories() {
    if(!currentShopId) return;
    try {
        const cats = await apiCall(`/categories/${currentShopId}`);
        const sel = document.getElementById('catSelect');
        if (sel) {
            sel.innerHTML = '';
            const activeCats = cats.filter(c => c.is_active !== false);
            activeCats.forEach(c => sel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)}</option>`);
        }
        
        const filterSel = document.getElementById('filterCatSelect');
        if (filterSel) {
            const prevVal = filterSel.value;
            filterSel.innerHTML = '<option value="">-- Tất cả --</option>';
            cats.forEach(c => {
                const suffix = c.is_active === false ? ' (Ẩn)' : '';
                filterSel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)}${suffix}</option>`;
            });
            if (cats.find(c => c.id == prevVal)) {
                filterSel.value = prevVal;
            }
        }
        
        renderCategoriesTable(cats);
    } catch(e) {
        console.error("Error loading categories:", e);
    }
}

let editingCategoryId = null;

function renderCategoriesTable(cats) {
    const tbody = document.getElementById('categoryTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    cats.forEach(c => {
        const activeText = c.is_active !== false 
            ? '<span style="color:var(--success); font-weight:600; font-size: 0.8rem;">ACTIVE</span>' 
            : '<span style="color:#ef4444; font-weight:600; font-size: 0.8rem;">INACTIVE</span>';
            
        tbody.innerHTML += `<tr>
            <td>${c.id}</td>
            <td><strong>${escapeHtml(c.name)}</strong></td>
            <td>${activeText}</td>
            <td>
                <button class="btn-outline" onclick="editCategory(${c.id}, '${escapeJS(c.name)}', ${c.is_active !== false})" style="padding: 0.2rem 0.5rem;" title="Chỉnh sửa"><i class="ph ph-pencil"></i></button>
            </td>
        </tr>`;
    });
}

function escapeJS(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

function editCategory(id, name, isActive) {
    editingCategoryId = id;
    document.getElementById('editingCatId').value = id;
    document.getElementById('catNameInput').value = name;
    document.getElementById('catStatusSelect').value = isActive ? 'active' : 'inactive';
    
    document.getElementById('catFormTitle').innerText = 'Chỉnh sửa danh mục';
    document.getElementById('btnSaveCategory').innerHTML = '<i class="ph ph-check-circle"></i> Cập nhật Danh Mục';
    document.getElementById('btnCancelEditCategory').style.display = 'block';
}

function cancelEditCategory() {
    editingCategoryId = null;
    document.getElementById('editingCatId').value = '';
    document.getElementById('catNameInput').value = '';
    document.getElementById('catStatusSelect').value = 'active';
    
    document.getElementById('catFormTitle').innerText = 'Thêm danh mục mới';
    document.getElementById('btnSaveCategory').innerHTML = '<i class="ph ph-plus-circle"></i> Lưu Danh Mục';
    document.getElementById('btnCancelEditCategory').style.display = 'none';
}

async function saveCategory() {
    if(!currentShopId) return;
    const name = document.getElementById('catNameInput').value.trim();
    const status = document.getElementById('catStatusSelect').value;
    
    if(!name) {
        return showToast("Tên danh mục không được để trống!");
    }
    
    try {
        if(editingCategoryId) {
            const body = {
                name: name,
                is_active: status === 'active'
            };
            await apiCall(`/categories/${editingCategoryId}`, 'PUT', body);
            showToast("Đã cập nhật danh mục thành công!");
            cancelEditCategory();
        } else {
            await apiCall(`/categories?name=${encodeURIComponent(name)}&shop_id=${currentShopId}`, 'POST');
            showToast("Đã thêm danh mục mới!");
            cancelEditCategory();
        }
        loadCategories();
        loadProducts();
    } catch(e) {
        showToast(e.message);
    }
}

let currentProducts = [];
let editingProductId = null;

async function loadProducts() {
    if(!currentShopId) return;
    try {
        currentProducts = await apiCall(`/products/${currentShopId}`);
        filterProducts();
    } catch (e) { showToast(e.message); }
}

function filterProducts() {
    const filterCatId = document.getElementById('filterCatSelect').value;
    const tbody = document.getElementById('prodList');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    const filtered = filterCatId 
        ? currentProducts.filter(p => p.category_id == filterCatId)
        : currentProducts;
        
    filtered.forEach(p => {
        const activeText = p.is_active ? '<span style="color:var(--success); font-weight:600; font-size: 0.8rem;">ACTIVE</span>' : '<span style="color:#ef4444; font-weight:600; font-size: 0.8rem;">INACTIVE</span>';
        tbody.innerHTML += `<tr>
            <td>${escapeHtml(p.code||'--')}${p.barcode ? `<br><span style="font-size:0.75rem; color:#64748B;" title="Mã vạch"><i class="ph ph-barcode"></i> ${escapeHtml(p.barcode)}</span>` : ''}</td>
            <td>${escapeHtml(p.name)} <br>${activeText}</td>
            <td>${p.price.toLocaleString()} ₫</td>
            <td>${p.stock}</td>
            <td style="display:flex; justify-content: center; align-items: center; gap:0.5rem; height: 7rem;">
                <button class="btn-outline" onclick="editProduct(${p.id})" style="padding: 0.2rem 0.5rem;" title="Sửa"><i class="ph ph-pencil-simple"></i></button>
                <button class="btn-outline" onclick="nhapXuatKho(${p.id})" style="padding: 0.2rem 0.5rem;" title="Nhập/Xuất kho"><i class="ph ph-stack"></i></button>
                <button class="btn-outline" onclick="toggleProductStatus(${p.id})" style="padding: 0.2rem 0.5rem;" title="Bật/Tắt"><i class="ph ph-power"></i></button>
                <button class="btn-outline" onclick="deleteProduct(${p.id})" style="padding: 0.2rem 0.5rem; color:#ef4444;" title="Xóa"><i class="ph ph-trash"></i></button>
            </td>
        </tr>`;
    });
}

// Khi SỬA sản phẩm, ô tồn kho bị khóa: thay đổi tồn kho đi qua nút Nhập/Xuất
// kho (cộng trừ theo delta), tránh ghi đè làm mất hàng khi bán song song.
function _khoaOTonKho(khoa) {
    const el = document.getElementById('prodStock');
    if (!el) return;
    el.disabled = khoa;
    el.title = khoa ? 'Sửa sản phẩm không đổi tồn kho. Dùng nút Nhập/Xuất kho.' : '';
    el.style.opacity = khoa ? '0.5' : '1';
}

function editProduct(id) {
    const product = currentProducts.find(p => p.id === id);
    if(!product) return;
    editingProductId = id;
    document.getElementById('prodCode').value = product.code || '';
    document.getElementById('prodBarcode').value = product.barcode || '';
    document.getElementById('prodName').value = product.name;
    document.getElementById('prodPrice').value = product.price;
    document.getElementById('prodStock').value = product.stock;
    _khoaOTonKho(true);
    document.getElementById('catSelect').value = String(product.category_id);
    document.getElementById('productFormTitle').innerText = 'Sửa sản phẩm';
    document.getElementById('btnSaveProduct').innerHTML = '<i class="ph ph-floppy-disk"></i> Cập nhật sản phẩm';
    document.getElementById('btnCancelEditProduct').style.display = 'block';
}

function cancelEditProduct() {
    editingProductId = null;
    document.getElementById('prodCode').value = '';
    document.getElementById('prodBarcode').value = '';
    document.getElementById('prodName').value = '';
    document.getElementById('prodPrice').value = '';
    document.getElementById('prodStock').value = '100';
    _khoaOTonKho(false);
    document.getElementById('prodImage').value = '';
    document.getElementById('productFormTitle').innerText = 'Thêm sản phẩm mới';
    document.getElementById('btnSaveProduct').innerHTML = '<i class="ph ph-plus"></i> Lưu vào kho';
    document.getElementById('btnCancelEditProduct').style.display = 'none';
}

async function nhapXuatKho(id) {
    const product = currentProducts.find(p => p.id === id);
    if(!product) return;
    const raw = prompt(
        `Nhập/Xuất kho cho "${product.name}" (tồn hiện tại: ${product.stock}).\n` +
        `Nhập số dương để NHẬP thêm, số âm để XUẤT bớt.\nVí dụ: 20  hoặc  -5`
    );
    if(raw === null) return;
    const delta = parseInt(raw, 10);
    if(isNaN(delta) || delta === 0) return showToast("Vui lòng nhập một số khác 0");
    try {
        const res = await apiCall(`/products/${id}/stock`, 'POST', { delta });
        showToast(`Đã ${delta > 0 ? 'nhập' : 'xuất'} kho. Tồn mới: ${res.stock}`);
        loadProducts();
    } catch(e) { showToast(e.message); }
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
        showToast('Mở tab Kho hàng để quét nhập/xuất, hoặc dùng màn POS để bán.');
        return;
    }

    // Mã vạch và mã nội bộ đều duy nhất theo shop, nên khớp được là chắc chắn.
    const sp = currentProducts.find(p => p.barcode && p.barcode.toUpperCase() === ma)
        || currentProducts.find(p => p.code && p.code.toUpperCase() === ma);
    if (!sp) {
        BarcodeScanner.bipLoi();
        showToast(`Không tìm thấy sản phẩm có mã "${ma}"`);
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
    const dong = phieuKiemKe[id];
    if (!dong) return;
    const n = parseInt(giaTri, 10);
    dong.counted = (isNaN(n) || n < 0) ? 0 : n;
    kkVeBang();
}

function kkBo(id) {
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
            <td>${d.stock_snapshot}</td>
            <td><input type="number" min="0" value="${d.counted}" onchange="kkDatSo(${id}, this.value)"
                       style="width:80px; padding:0.3rem; border-radius:6px; border:1px solid #334155; background:#0F172A; color:#F8FAFC;"></td>
            <td style="color:${mau}; font-weight:600;">${lech > 0 ? '+' : ''}${lech}</td>
            <td><button class="btn-outline" onclick="kkBo(${id})" style="padding:0.2rem 0.5rem; color:#ef4444;"><i class="ph ph-x"></i></button></td>
        </tr>`;
    });

    document.getElementById('kkSoSP').innerText = cacDong.length;
    document.getElementById('kkSoThieu').innerText = thieu;
    document.getElementById('kkSoThua').innerText = thua;
    document.getElementById('kkSoKhop').innerText = khop;
    document.getElementById('kkBtnApDung').disabled = cacDong.length === 0;
}

/** Tìm SP theo mã rồi cộng 1 vào phiếu đếm. */
function kkQuet(ma) {
    const sp = currentProducts.find(p => p.barcode && p.barcode.toUpperCase() === ma)
        || currentProducts.find(p => p.code && p.code.toUpperCase() === ma);
    if (!sp) {
        BarcodeScanner.bipLoi();
        showToast(`Không tìm thấy sản phẩm có mã "${ma}"`);
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
    // Để mở để quét liên tiếp cả kệ hàng, không phải bấm lại từng lần.
    BarcodeCamera.mo();
}

async function kkApDung() {
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
        ? 'không đổi'
        : (chenh < 0 ? `GIẢM ${-chenh}` : `TĂNG ${chenh}`);

    if (!confirm(
        `Áp dụng kiểm kê cho ${items.length} sản phẩm?\n\n`
        + `Tổng tồn kho: ${tongTon} → ${tongDem}  (${moTaChenh})\n`
        + `${soLech} sản phẩm bị lệch.\n\n`
        + `Tồn kho sẽ được đặt đúng bằng số đếm thực tế.\n`
        + `Sản phẩm không có trong phiếu giữ nguyên tồn kho.`
    )) return;

    try {
        const res = await apiCall(`/products/${currentShopId}/stocktake`, 'POST', { items });
        kkHienKetQua(res);
        phieuKiemKe = {};
        kkVeBang();
        loadProducts();
    } catch (e) {
        showToast(e.message);
    }
}

function kkHienKetQua(res) {
    const box = document.getElementById('kkKetQua');
    const boQua = res.bo_qua || [];
    box.style.display = 'block';
    box.style.background = boQua.length ? '#422006' : '#052e16';
    box.style.border = `1px solid ${boQua.length ? '#a16207' : '#15803d'}`;
    box.style.color = '#F8FAFC';

    let html = `<b>Đã điều chỉnh ${res.da_dieu_chinh.length} sản phẩm</b>`
        + ` (lệch tổng ${res.tong_lech > 0 ? '+' : ''}${res.tong_lech}),`
        + ` ${res.khong_doi} sản phẩm khớp sẵn.`;
    if (boQua.length) {
        html += `<br><b style="color:#fbbf24;">${boQua.length} sản phẩm bị bỏ qua:</b><ul style="margin:0.4rem 0 0 1.1rem;">`
            + boQua.map(b => `<li>${escapeHtml(b.name || ('SP #' + b.product_id))}: ${escapeHtml(b.ly_do)}</li>`).join('')
            + `</ul>`;
    }
    box.innerHTML = html;
    showToast(boQua.length ? 'Kiểm kê xong, có dòng bị bỏ qua - xem chi tiết bên dưới bảng.'
                           : 'Đã áp dụng kiểm kê.');
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
    BarcodeCamera.mo({
        dongSauKhiQuet: true,
        xuLy: (ma) => {
            document.getElementById('prodBarcode').value = ma;
            BarcodeScanner.bipOk();
            showToast(`Đã điền mã vạch: ${ma}`);
        }
    });
}

/** Nút camera trên danh sách: quét xong mở hộp nhập/xuất kho cho SP đó. */
function quetNhapXuatBangCamera() {
    BarcodeCamera.mo({ dongSauKhiQuet: true });
}

function deleteProduct(id) {
    showCustomConfirm(
        "Xác nhận xóa sản phẩm",
        "Bạn có chắc muốn xóa Sản phẩm này?",
        async () => {
            try {
                await apiCall(`/products/${id}`, 'DELETE');
                showToast("Đã xóa sản phẩm!");
                loadProducts();
            } catch(e) { showToast(e.message); }
        }
    );
}

async function toggleProductStatus(id) {
    try {
        await apiCall(`/products/${id}/status`, 'PUT');
        showToast("Cập nhật trạng thái SP thành công!");
        loadProducts();
    } catch(e) { showToast(e.message); }
}

async function createProduct() {
    if(!currentShopId) return;
    const catSelect = document.getElementById('catSelect');
    if(!catSelect || !catSelect.value) {
        return showToast("Lỗi: Bạn phải tạo Danh mục cho cửa hàng này trước!");
    }
    const formData = new FormData();
    formData.append('code', document.getElementById('prodCode').value);
    // Luôn gửi, kể cả khi rỗng: backend phân biệt "không gửi" (giữ mã vạch cũ)
    // với "gửi rỗng" (xóa mã vạch). Xóa trắng ô phải thực sự gỡ được mã.
    formData.append('barcode', document.getElementById('prodBarcode').value);
    formData.append('name', document.getElementById('prodName').value);
    const priceStr = document.getElementById('prodPrice').value;
    const stockStr = document.getElementById('prodStock').value;
    
    if(parseFloat(priceStr) <= 0) return showToast("Giá sản phẩm phải lớn hơn 0!");
    if(parseInt(stockStr) < 0) return showToast("Số lượng không được âm!");

    formData.append('price', priceStr);
    formData.append('stock', stockStr);
    formData.append('category_id', catSelect.value);
    const img = document.getElementById('prodImage').files[0];
    if(img) formData.append('image', img);

    try {
        const isEditing = editingProductId !== null;
        const url = isEditing
            ? `/api/products/${editingProductId}`
            : `/api/products?shop_id=${currentShopId}`;
        const res = await fetch(url, {
            method: isEditing ? 'PUT' : 'POST',
            headers: { 'Authorization': `Bearer ${getToken()}` },
            body: formData
        });
        if(!res.ok) {
            let errMsg = "Lỗi lưu sản phẩm";
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
        showToast(isEditing ? "Đã cập nhật sản phẩm!" : "Đã lưu sản phẩm vào kho!");
        cancelEditProduct();
        loadProducts();
    } catch(e) { showToast(e.message); }
}

let currentVouchers = [];
let editingVoucherId = null;

async function loadVouchers() {
    if(!currentShopId) return;
    currentVouchers = await apiCall(`/vouchers/${currentShopId}`);
    const tbody = document.getElementById('voucherList');
    tbody.innerHTML = '';
    currentVouchers.forEach(v => {
        tbody.innerHTML += `<tr>
            <td><strong>${escapeHtml(v.code)}</strong></td>
            <td>${v.discount_type==='flat'?'VNĐ':'%'}</td>
            <td>${v.discount_value}</td>
            <td>${v.usage_count}/${v.usage_limit===-1?'∞':v.usage_limit}</td>
            <td style="display:flex; gap:0.3rem;">
                <button class="btn-outline" onclick="editVoucher(${v.id})" style="padding:0.2rem 0.5rem;"><i class="ph ph-pencil"></i></button>
                <button class="btn-outline" onclick="deleteVoucher(${v.id})" style="padding:0.2rem 0.5rem; color:#ef4444;"><i class="ph ph-trash"></i></button>
            </td>
        </tr>`;
    });
}

function editVoucher(id) {
    const v = currentVouchers.find(x => x.id === id);
    if(!v) return;
    editingVoucherId = id;
    document.getElementById('vCode').value = v.code;
    document.getElementById('vType').value = v.discount_type;
    document.getElementById('vVal').value = v.discount_value;
    document.getElementById('vMin').value = v.min_order_value;
    document.getElementById('vLimit').value = v.usage_limit;
    document.getElementById('btnSaveVoucher').innerHTML = '<i class="ph ph-check-circle"></i> Cập nhật Khuyến Mãi';
    document.getElementById('btnCancelEditVoucher').style.display = 'block';
}

function cancelEditVoucher() {
    editingVoucherId = null;
    document.getElementById('vCode').value = '';
    document.getElementById('vType').value = 'flat';
    document.getElementById('vVal').value = '';
    document.getElementById('vMin').value = '0';
    document.getElementById('vLimit').value = '-1';
    document.getElementById('btnSaveVoucher').innerHTML = '<i class="ph ph-plus-circle"></i> Tạo Mã Khuyến Mãi';
    document.getElementById('btnCancelEditVoucher').style.display = 'none';
}

async function createOrUpdateVoucher() {
    if(!currentShopId) return;

    const code = document.getElementById('vCode').value.trim();
    if (!code) {
        return showToast("Mã voucher không được để trống!");
    }

    const discountType = document.getElementById('vType').value;
    const discountValStr = document.getElementById('vVal').value;
    const minOrderValStr = document.getElementById('vMin').value;
    const limitStr = document.getElementById('vLimit').value;

    if (!discountValStr) {
        return showToast("Giá trị giảm không được để trống!");
    }
    const discountVal = parseFloat(discountValStr);
    if (isNaN(discountVal) || discountVal < 1) {
        return showToast("Giá trị giảm tối thiểu phải là 1!");
    }

    if (discountType === 'percentage') {
        if (discountVal <= 0 || discountVal > 100) {
            return showToast("Giá trị giảm phần trăm phải từ 1% đến 100%!");
        }
    }

    const minOrderVal = parseFloat(minOrderValStr || '0');
    if (isNaN(minOrderVal) || minOrderVal < 0) {
        return showToast("Đơn tối thiểu không được âm!");
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
        if(editingVoucherId) {
            await apiCall(`/vouchers/${editingVoucherId}`, 'PUT', body);
            showToast("Đã cập nhật Voucher!");
            cancelEditVoucher();
        } else {
            await apiCall(`/vouchers?shop_id=${currentShopId}`, 'POST', body);
            showToast("Đã tạo Voucher thành công!");
            cancelEditVoucher();
        }
        loadVouchers();
    } catch(e) { showToast(e.message); }
}

function deleteVoucher(id) {
    showCustomConfirm(
        "Xác nhận xóa voucher",
        "Bạn có chắc muốn xóa Voucher này?",
        async () => {
            try {
                await apiCall(`/vouchers/${id}`, 'DELETE');
                showToast("Đã xóa Voucher!");
                loadVouchers();
            } catch(e) { showToast(e.message); }
        }
    );
}

async function downloadExcel() {
    if(!dashboardShopId) return showToast("Vui lòng chọn cửa hàng trước");
    try {
        const res = await fetch(`/api/export/seller/${dashboardShopId}`, {
            headers: { 'Authorization': `Bearer ${getToken()}` },
            cache: 'no-store'
        });
        if (!res.ok) {
            if (res.status === 403) return showToast("Bạn không có quyền tải dữ liệu cửa hàng này");
            return showToast("Không tải được file. Vui lòng thử lại.");
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
        showToast("Lỗi khi tải file: " + e.message);
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
            errorMsg.innerText = "Đổi mật khẩu mới xác nhận không khớp!";
            return;
        }
        
        const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
        if (!regex.test(new_password)) {
            errorMsg.innerText = "Mật khẩu mới phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số!";
            return;
        }
        
        try {
            const res = await apiCall('/auth/change-password', 'POST', { old_password, new_password });
            successMsg.innerText = "Đổi mật khẩu thành công!";
            localStorage.setItem('token', res.access_token);
            alert("Đổi mật khẩu thành công!");
            closeChangePasswordModal();
        } catch (err) {
            errorMsg.innerText = err.message;
        }
    });
});

let confirmCallback = null;

function showCustomConfirm(title, message, onConfirm) {
    const titleEl = document.getElementById('confirmTitle');
    const msgEl = document.getElementById('confirmMessage');
    const modalEl = document.getElementById('confirmModal');
    if (titleEl) titleEl.innerText = title;
    if (msgEl) msgEl.innerText = message;
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

init();

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
        info.innerText = 'Không có đơn nào trong khoảng đã chọn';
    } else {
        const dau = (res.page - 1) * res.per_page + 1;
        const cuoi = Math.min(res.page * res.per_page, tong);
        info.innerText = `Hiển thị ${dau}-${cuoi} trên tổng ${tong} đơn`;
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
    if (tu && den && tu > den) return showToast('Từ ngày không được lớn hơn đến ngày');
    trangDonHienTai = 1;
    if (dashboardShopId) loadDashboardShop(dashboardShopId);
}

function xoaLocNgay() {
    document.getElementById('filterTuNgay').value = '';
    document.getElementById('filterDenNgay').value = '';
    trangDonHienTai = 1;
    if (dashboardShopId) loadDashboardShop(dashboardShopId);
}

// ===== Xem chi tiết đơn (nhóm B) =====
async function xemChiTietDon(orderId) {
    try {
        const d = await apiCall(`/orders/${orderId}/detail`);
        document.getElementById('odMaDon').innerText = `#${d.id}`;

        const tt = window.moTaTrangThaiDon(d.status);
        const ngay = dinhDangNgayGio(d.created_at);
        const pttt = d.payment_method === 'cash' ? 'Tiền mặt' : 'Chuyển khoản';
        document.getElementById('odThongTin').innerText =
            `${ngay} • ${pttt} • ${tt.label}`;

        const khachHang = document.getElementById('odKhachHang');
        if (d.customer) {
            khachHang.innerText = `Khách hàng: ${d.customer.name} (${d.customer.phone})`;
            khachHang.style.display = 'block';
        } else {
            khachHang.innerText = '';
            khachHang.style.display = 'none';
        }

        const tbody = document.getElementById('odDanhSach');
        tbody.innerHTML = '';
        d.items.forEach(i => {
            tbody.innerHTML += `<tr>
                <td>${escapeHtml(i.product_name)}</td>
                <td style="text-align:right;">${(i.price || 0).toLocaleString()} ₫</td>
                <td style="text-align:right;">${i.quantity}</td>
                <td style="text-align:right;">${(i.line_total || 0).toLocaleString()} ₫</td>
            </tr>`;
        });

        let tongKet = `<div>Tạm tính: <strong>${(d.subtotal || 0).toLocaleString()} ₫</strong></div>`;
        if (d.discount_amount > 0) {
            const ma = d.voucher_code ? ` (${escapeHtml(d.voucher_code)})` : '';
            tongKet += `<div style="color: #F59E0B;">Giảm giá${ma}: -${d.discount_amount.toLocaleString()} ₫</div>`;
        }
        tongKet += `<div style="font-size: 1.2rem; margin-top: 0.5rem;">Tổng cộng: <strong>${(d.total_amount || 0).toLocaleString()} ₫</strong></div>`;
        document.getElementById('odTongKet').innerHTML = tongKet;

        document.getElementById('orderDetailModal').style.display = 'flex';
    } catch (e) { showToast(e.message); }
}

function dongChiTietDon() {
    document.getElementById('orderDetailModal').style.display = 'none';
}


// ===== C1d: phân biệt vai trò SELLER / STAFF trên giao diện =====
function applyRoleUI() {
    if (MY_ROLE !== 'STAFF') return;
    // Nhân viên không quản lý cửa hàng: ẩn tab Cài Đặt và mọi lối vào nó.
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const oc = btn.getAttribute('onclick') || '';
        if (oc.includes("switchTab('settings')")) btn.style.display = 'none';
    });
    // Nếu POS shop selector có nút tạo shop... không áp dụng ở đây.
}

// ===== C1d: quản lý nhân viên (chỉ chủ shop) =====
function renderStaffShopOptions() {
    const sel = document.getElementById('staffShopSelect');
    if (!sel) return;
    sel.innerHTML = allShops.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    if (allShops.length) loadStaff();
}

async function loadStaff() {
    const sel = document.getElementById('staffShopSelect');
    if (!sel || !sel.value) return;
    try {
        const list = await apiCall(`/staff/${sel.value}`);
        const tbody = document.getElementById('staffList');
        tbody.innerHTML = '';
        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="2" style="color: var(--text-muted);">Chưa có nhân viên</td></tr>`;
            return;
        }
        list.forEach(nv => {
            tbody.innerHTML += `<tr>
                <td>${escapeHtml(nv.username)}</td>
                <td style="text-align:right;">
                    <button class="btn-outline" style="padding: 0.2rem 0.5rem; color:#ef4444;" onclick="xoaNhanVien(${nv.id}, '${escapeHtml(nv.username)}')" title="Xóa"><i class="ph ph-trash"></i></button>
                </td>
            </tr>`;
        });
    } catch (e) { showToast(e.message); }
}

async function taoNhanVien() {
    const sel = document.getElementById('staffShopSelect');
    const username = document.getElementById('staffUsername').value.trim();
    const password = document.getElementById('staffPassword').value;
    if (!sel || !sel.value) return showToast('Vui lòng chọn cửa hàng');
    if (!username) return showToast('Vui lòng nhập tên đăng nhập');
    if (!password) return showToast('Vui lòng nhập mật khẩu');
    try {
        await apiCall(`/staff/${sel.value}`, 'POST', { username, password });
        showToast('Đã thêm nhân viên');
        document.getElementById('staffUsername').value = '';
        document.getElementById('staffPassword').value = '';
        loadStaff();
    } catch (e) { showToast(e.message); }
}

function xoaNhanVien(id, username) {
    showCustomConfirm(
        'Xóa nhân viên',
        `Xóa nhân viên "${username}"? Tài khoản này sẽ không đăng nhập được nữa.`,
        async () => {
            try {
                await apiCall(`/staff/member/${id}`, 'DELETE');
                showToast('Đã xóa nhân viên');
                loadStaff();
            } catch (e) { showToast(e.message); }
        }
    );
}

// Chạy sau khi DOM và allShops sẵn sàng. init() sẽ gọi renderStaffShopOptions.
applyRoleUI();


// ===== C2d: quản lý khách hàng (CRM) =====
let editingCustomerId = null;

function renderCustomerShopOptions() {
    const sel = document.getElementById('custShopSelect');
    if (!sel) return;
    sel.innerHTML = allShops.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    if (allShops.length) loadCustomers();
}

async function loadCustomers() {
    const sel = document.getElementById('custShopSelect');
    if (!sel || !sel.value) return;
    const q = (document.getElementById('custSearch')?.value || '').trim();
    try {
        const url = q ? `/customers/${sel.value}?q=${encodeURIComponent(q)}` : `/customers/${sel.value}`;
        const list = await apiCall(url);
        const tbody = document.getElementById('customerList');
        tbody.innerHTML = '';
        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="3" style="color: var(--text-muted);">Chưa có khách hàng</td></tr>`;
            return;
        }
        list.forEach(kh => {
            tbody.innerHTML += `<tr>
                <td>${escapeHtml(kh.name)}</td>
                <td>${escapeHtml(kh.phone)}</td>
                <td style="text-align:right; white-space:nowrap;">
                    <button class="btn-outline" style="padding:0.2rem 0.5rem;" onclick="xemLichSuKhach(${kh.id})" title="Lịch sử mua"><i class="ph ph-clock-counter-clockwise"></i></button>
                    <button class="btn-outline" style="padding:0.2rem 0.5rem;" onclick="editCustomer(${kh.id})" title="Sửa"><i class="ph ph-pencil-simple"></i></button>
                    <button class="btn-outline" style="padding:0.2rem 0.5rem; color:#ef4444;" onclick="deleteCustomer(${kh.id}, '${escapeHtml(kh.name)}')" title="Xóa"><i class="ph ph-trash"></i></button>
                </td>
            </tr>`;
        });
        window._customersCache = list;
    } catch (e) { showToast(e.message); }
}

async function saveCustomer() {
    const sel = document.getElementById('custShopSelect');
    const name = document.getElementById('custName').value.trim();
    const phone = document.getElementById('custPhone').value.trim();
    const address = document.getElementById('custAddress').value.trim();
    const note = document.getElementById('custNote').value.trim();
    if (!sel || !sel.value) return showToast('Vui lòng chọn cửa hàng');
    if (!name) return showToast('Vui lòng nhập tên khách');
    if (!phone) return showToast('Vui lòng nhập số điện thoại');
    const body = { name, phone, address, note };
    try {
        if (editingCustomerId !== null) {
            await apiCall(`/customers/member/${editingCustomerId}`, 'PUT', body);
            showToast('Đã cập nhật khách');
        } else {
            await apiCall(`/customers/${sel.value}`, 'POST', body);
            showToast('Đã thêm khách');
        }
        cancelEditCustomer();
        loadCustomers();
    } catch (e) { showToast(e.message); }
}

function editCustomer(id) {
    const kh = (window._customersCache || []).find(c => c.id === id);
    if (!kh) return;
    editingCustomerId = id;
    document.getElementById('custName').value = kh.name || '';
    document.getElementById('custPhone').value = kh.phone || '';
    document.getElementById('custAddress').value = kh.address || '';
    document.getElementById('custNote').value = kh.note || '';
    document.getElementById('custFormTitle').innerText = 'Sửa khách hàng';
    document.getElementById('btnSaveCustomer').innerHTML = '<i class="ph ph-floppy-disk"></i> Cập nhật';
    document.getElementById('btnCancelEditCustomer').style.display = 'block';
}

function cancelEditCustomer() {
    editingCustomerId = null;
    ['custName', 'custPhone', 'custAddress', 'custNote'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('custFormTitle').innerText = 'Thêm khách hàng';
    document.getElementById('btnSaveCustomer').innerHTML = '<i class="ph ph-plus"></i> Lưu khách';
    document.getElementById('btnCancelEditCustomer').style.display = 'none';
}

function deleteCustomer(id, ten) {
    showCustomConfirm(
        'Xóa khách hàng',
        `Xóa khách "${ten}"? Các đơn cũ vẫn giữ nhưng sẽ không còn gắn tên khách.`,
        async () => {
            try {
                await apiCall(`/customers/member/${id}`, 'DELETE');
                showToast('Đã xóa khách');
                loadCustomers();
            } catch (e) { showToast(e.message); }
        }
    );
}

async function xemLichSuKhach(id) {
    try {
        const d = await apiCall(`/customers/member/${id}/history`);
        document.getElementById('chTen').innerText = `${d.customer.name} (${d.customer.phone})`;
        document.getElementById('chTongKet').innerText =
            `${d.order_count} đơn • Đã chi (đã thanh toán): ${(d.total_paid || 0).toLocaleString()} ₫`;
        const tbody = document.getElementById('chDanhSach');
        tbody.innerHTML = '';
        if (!d.orders.length) {
            tbody.innerHTML = `<tr><td colspan="4" style="color: var(--text-muted);">Chưa có đơn nào</td></tr>`;
        } else {
            d.orders.forEach(o => {
                const tt = window.moTaTrangThaiDon(o.status);
                const ngay = dinhDangNgayGio(o.date);
                tbody.innerHTML += `<tr>
                    <td><strong>#${o.id}</strong></td>
                    <td>${ngay}</td>
                    <td>${(o.total || 0).toLocaleString()} ₫</td>
                    <td style="color:${tt.color}; font-weight:600;">${escapeHtml(tt.label)}</td>
                </tr>`;
            });
        }
        document.getElementById('customerHistoryModal').style.display = 'flex';
    } catch (e) { showToast(e.message); }
}

function dongLichSuKhach() {
    document.getElementById('customerHistoryModal').style.display = 'none';
}
