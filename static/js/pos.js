if(localStorage.getItem('role') !== 'SELLER') window.location.href = '/';
let allShops = [];
let currentShopId = parseInt(localStorage.getItem('currentShopId'));

let cart = [];
let products = [];
let categories = [];
let currentCategoryId = null;
let currentVoucher = null;
let discount = 0;
let subtotal = 0;
let total = 0;
let paymentMethod = 'transfer';
let currentOrderId = null;

async function loadShop() {
    try {
        const res = await apiCall('/shops');
        allShops = res.filter(s => s.is_active !== false); // fallback if undefined
        const sel = document.getElementById('shopSelect');
        sel.innerHTML = '<option value="">-- Chọn Cửa Hàng --</option>';
        allShops.forEach(s => {
            sel.innerHTML += `<option value="${s.id}" ${s.id === currentShopId ? 'selected' : ''}>${escapeHtml(s.name)}</option>`;
        });
        if(allShops.length > 0 && !currentShopId) {
            currentShopId = allShops[0].id;
            localStorage.setItem('currentShopId', currentShopId);
            sel.value = currentShopId;
        }
        loadCategories();
        loadProducts();
    } catch(e) {}
}

function changeShopPOS() {
    const val = document.getElementById('shopSelect').value;
    if(!val) return;
    currentShopId = parseInt(val);
    localStorage.setItem('currentShopId', currentShopId);
    resetPOS();
}

async function loadProducts() {
    if(!currentShopId) return;
    try {
        const res = await apiCall(`/products/${currentShopId}`);
        products = res.filter(p => p.is_active !== false && p.category_is_active !== false);
        filterAndRenderProducts();
    } catch (e) { showToast(e.message); }
}

async function loadCategories() {
    if(!currentShopId) return;
    try {
        const res = await apiCall(`/categories/${currentShopId}`);
        categories = res.filter(c => c.is_active !== false);
        renderCategories();
    } catch (e) { console.error(e); }
}

function renderCategories() {
    const container = document.getElementById('categoryFilter');
    if(!container) return;
    container.innerHTML = `<button class="category-btn ${!currentCategoryId ? 'active' : ''}" onclick="filterByCategory(null)">Tất cả</button>`;
    categories.forEach(c => {
        container.innerHTML += `<button class="category-btn ${currentCategoryId === c.id ? 'active' : ''}" onclick="filterByCategory(${c.id})">${escapeHtml(c.name)}</button>`;
    });
}

function filterByCategory(catId) {
    currentCategoryId = catId;
    renderCategories();
    filterAndRenderProducts();
}

function filterAndRenderProducts() {
    let filtered = products;
    if (currentCategoryId) {
        filtered = filtered.filter(p => p.category_id === currentCategoryId);
    }
    const searchVal = document.getElementById('searchProd').value.toLowerCase();
    if (searchVal) {
        filtered = filtered.filter(p => (p.code && p.code.toLowerCase() === searchVal) || p.name.toLowerCase().includes(searchVal));
    }
    renderProducts(filtered);
}

function renderProducts(list) {
    const grid = document.getElementById('productGrid');
    grid.innerHTML = '';
    list.forEach(p => {
        const imgUrl = p.image_url ? p.image_url : 'https://placehold.co/150x150/1E293B/FFF?text=SP';
        const div = document.createElement('div');
        div.className = 'product-card';
        div.innerHTML = `
            <div class="product-stock" style="color: white;">Kho: ${p.stock}</div>
            <img src="${imgUrl}" onerror="this.src='https://via.placeholder.com/150x150?text=Error'" class="product-img">
            <div class="product-info">
                <div class="product-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
                <div class="product-price">${p.price.toLocaleString()} ₫</div>
            </div>
        `;
        div.onclick = () => addToCart(p);
        grid.appendChild(div);
    });
}

// Tìm kiếm / Quét mã vạch
document.getElementById('searchProd').addEventListener('input', (e) => {
    filterAndRenderProducts();
});

function addToCart(p) {
    try {
        if(!cart) cart = [];
        if(p.stock <= 0) return showToast("Sản phẩm đã hết hàng!");
        const existing = cart.find(i => i.product_name === p.name);
        if(existing) {
            if(existing.quantity >= p.stock) return showToast("Vượt quá số lượng tồn kho!");
            existing.quantity++;
        }
        else cart.push({ product_name: p.name, price: p.price, quantity: 1, max_stock: p.stock });
        calcCart();
    } catch (err) {
        console.error("Lỗi thêm vào giỏ:", err);
        showToast("Lỗi hệ thống khi thêm sản phẩm.");
    }
}

function updateQty(index, delta) {
    const item = cart[index];
    if(item.quantity + delta > item.max_stock) return showToast("Vượt quá tồn kho!");
    if(item.quantity + delta <= 0) cart.splice(index, 1);
    else item.quantity += delta;
    calcCart();
}

function removeItem(index) {
    cart.splice(index, 1);
    calcCart();
}

function calcCart() {
    try {
        if(!cart) cart = [];
        subtotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
        if(currentVoucher) applyVoucher(); // Re-apply voucher logic
        else { discount = 0; total = subtotal; updateUI(); }
    } catch (err) {
        console.error("Lỗi tính tiền:", err);
    }
}

async function applyVoucher() {
    const code = document.getElementById('voucherInput').value.toUpperCase();
    if(!code) {
        currentVoucher = null; discount = 0; total = subtotal;
        document.getElementById('voucherMsg').innerText = "";
        updateUI(); return;
    }
    if(subtotal === 0) return;

    const formData = new FormData();
    formData.append('subtotal', subtotal);
    formData.append('voucher_code', code);

    try {
        const res = await fetch(`/api/vouchers/apply/${currentShopId}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getToken()}` },
            body: formData
        });
        const data = await res.json();
        if(!res.ok) {
            currentVoucher = null; discount = 0; total = subtotal;
            document.getElementById('voucherMsg').innerText = data.detail;
            document.getElementById('voucherMsg').style.color = '#EF4444';
        } else {
            currentVoucher = code;
            discount = data.discount_amount;
            total = data.new_total;
            document.getElementById('voucherMsg').innerText = "Áp dụng thành công!";
            document.getElementById('voucherMsg').style.color = 'var(--success)';
        }
        updateUI();
    } catch(e) { console.log(e); }
}

function updateUI() {
    const container = document.getElementById('cartContainer');
    container.innerHTML = '';
    cart.forEach((item, index) => {
        container.innerHTML += `
            <div class="cart-item">
                <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #F8FAFC;" title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</div>
                <div style="color: var(--success);">${item.price.toLocaleString()}</div>
                <div style="display: flex; gap: 0.3rem; align-items: center; color: white;">
                    <button class="btn-qty" onclick="updateQty(${index}, -1)">-</button>
                    <span>${item.quantity}</span>
                    <button class="btn-qty" onclick="updateQty(${index}, 1)">+</button>
                </div>
                <button class="btn-del" onclick="removeItem(${index})"><i class="ph ph-trash"></i></button>
            </div>
        `;
    });

    document.getElementById('txtSubtotal').innerText = subtotal.toLocaleString() + ' ₫';
    document.getElementById('txtDiscount').innerText = '- ' + discount.toLocaleString() + ' ₫';
    document.getElementById('txtTotal').innerText = total.toLocaleString() + ' ₫';
}

function setMethod(m) {
    paymentMethod = m;
    document.getElementById('btnMethodQR').classList.remove('active');
    document.getElementById('btnMethodCash').classList.remove('active');
    if(m==='transfer') document.getElementById('btnMethodQR').classList.add('active');
    else document.getElementById('btnMethodCash').classList.add('active');
    
    // Hide QR section if switching to cash
    if(m === 'cash') document.getElementById('qrSection').style.display = 'none';
}

let paymentPollingInterval = null;

async function checkout() {
    if(cart.length === 0) return showToast("Giỏ hàng trống!");
    try {
        const body = {
            items: cart.map(i => ({product_name: i.product_name, price: i.price, quantity: i.quantity})),
            voucher_code: currentVoucher,
            payment_method: paymentMethod
        };
        const res = await apiCall(`/orders/${currentShopId}`, 'POST', body);
        currentOrderId = res.order_id;
        
        if(paymentMethod === 'transfer') {
            document.getElementById('qrImage').src = res.qr_url;
            document.getElementById('qrTotalTxt').innerText = res.total.toLocaleString() + ' ₫';
            document.getElementById('qrSection').style.display = 'block';
            showToast("Tạo đơn thành công! Khách vui lòng quét mã.");
            startPaymentPolling();
        } else {
            // Tiền mặt -> auto pay for simplicity or just show success
            await apiCall(`/orders/${currentOrderId}/pay`, 'POST');
            showToast("Thu tiền mặt thành công!");
            resetPOS();
        }
    } catch (e) { showToast(e.message); }
}

async function confirmPayment() {
    if(!currentOrderId) return;
    try {
        await apiCall(`/orders/${currentOrderId}/pay`, 'POST');
        stopPaymentPolling();
        showToast("Đã xác nhận tiền vào tài khoản!");
        resetPOS();
    } catch (e) { showToast(e.message); }
}

async function cancelOrder() {
    if(!currentOrderId) return;
    if(!confirm(`Hủy đơn #${currentOrderId}? Hàng trong đơn sẽ được trả lại kho.`)) return;
    try {
        const res = await apiCall(`/orders/${currentOrderId}/cancel`, 'POST');
        stopPaymentPolling();
        if(res.unrestored_items > 0) {
            showToast(`Đã hủy đơn. Có ${res.unrestored_items} dòng không hoàn kho được, vui lòng kiểm tra lại tồn kho.`);
        } else {
            showToast("Đã hủy đơn và hoàn lại hàng vào kho.");
        }
        resetPOS();
    } catch (e) { showToast(e.message); }
}

function startPaymentPolling() {
    stopPaymentPolling();
    paymentPollingInterval = setInterval(async () => {
        if(!currentOrderId) return stopPaymentPolling();
        try {
            const statusRes = await apiCall(`/orders/${currentOrderId}`);
            if(statusRes.status === 'PAID') {
                stopPaymentPolling();
                showToast('Thanh toán chuyển khoản thành công!');
                resetPOS();
            } else if(statusRes.status === 'CANCELLED') {
                // Đơn có thể bị hủy tự động do quá hạn thanh toán
                stopPaymentPolling();
                showToast('Đơn đã bị hủy, hàng đã được hoàn về kho.');
                resetPOS();
            } else if(statusRes.status === 'UNRECONCILED') {
                stopPaymentPolling();
                showToast('Tiền về sau khi đơn đã hủy. Vui lòng đối soát trước khi giao hàng!');
                resetPOS();
            }
        } catch (err) {
            console.error('Polling lỗi:', err);
        }
    }, 5000);
}

function stopPaymentPolling() {
    if(paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

function resetPOS() {
    stopPaymentPolling();
    cart = [];
    currentVoucher = null;
    document.getElementById('voucherInput').value = '';
    document.getElementById('voucherMsg').innerText = '';
    document.getElementById('qrSection').style.display = 'none';
    currentOrderId = null;
    calcCart();
    loadProducts(); // refresh stock
}

loadShop();
loadProducts();