const BASE_URL = '/api';
let cachedToken = localStorage.getItem('token');

// Escape dữ liệu người dùng trước khi chèn vào innerHTML để chống XSS.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Nhãn tiếng Việt + màu cho trạng thái đơn hàng.
// Trạng thái lạ (do backend thêm sau này) vẫn hiển thị được, không vỡ giao diện.
const NHAN_TRANG_THAI_DON = {
    PENDING:      { label: 'Chờ thanh toán', color: '#F59E0B' },
    PAID:         { label: 'Đã thanh toán',  color: 'var(--success)' },
    CANCELLED:    { label: 'Đã hủy',         color: '#94A3B8' },
    UNRECONCILED: { label: 'Cần đối soát',   color: '#EF4444' }
};

function moTaTrangThaiDon(status) {
    return NHAN_TRANG_THAI_DON[status] || { label: status, color: '#94A3B8' };
}

// Ghi đè localStorage.setItem để cập nhật cachedToken riêng cho tab này
const originalSetItem = localStorage.setItem;
localStorage.setItem = function(key, value) {
    if (key === 'token') {
        cachedToken = value;
    }
    originalSetItem.apply(this, arguments);
};

function getToken() {
    return cachedToken;
}

async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = {
        'Content-Type': 'application/json'
    };
    
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const options = { method, headers, cache: 'no-store' };
    if (body) {
        options.body = JSON.stringify(body);
    }

    const res = await fetch(`${BASE_URL}${endpoint}`, options);
    if (res.status === 401 && !endpoint.includes('/auth/login')) {
        // Chỉ xóa localStorage nếu token hiện tại trong localStorage trùng với token cũ của tab này
        if (localStorage.getItem('token') === cachedToken) {
            localStorage.clear();
        }
        window.location.href = '/';
        return;
    }
    
    if (res.headers.get('Content-Disposition')) {
        return res; // Return raw response for file downloads
    }
    
    const data = await res.json();
    if (!res.ok) {
        let msg = data.detail || 'API Error';
        if (Array.isArray(msg) && msg.length > 0 && msg[0].msg) {
            msg = msg[0].msg;
        } else if (typeof msg === 'object') {
            msg = JSON.stringify(msg);
        }
        throw new Error(msg);
    }
    return data;
}

function showToast(msg) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
}

function logout() {
    localStorage.clear();
    window.location.href = '/';
}

// Tự động phát hiện khi đăng nhập ở tab khác trên cùng trình duyệt (Lập tức logout tab cũ)
window.addEventListener('storage', (e) => {
    if (e.key === 'token') {
        if (e.newValue !== cachedToken) {
            window.location.href = '/';
        }
    }
});

// Định kỳ kiểm tra phiên đăng nhập với server (Lập tức logout nếu đăng nhập ở thiết bị/trình duyệt khác)
setInterval(async () => {
    const token = getToken();
    if (token) {
        try {
            const res = await fetch(`${BASE_URL}/auth/session-check`, {
                headers: { 'Authorization': `Bearer ${token}` },
                cache: 'no-store'
            });
            if (res.status === 401) {
                if (localStorage.getItem('token') === cachedToken) {
                    localStorage.clear();
                }
                window.location.href = '/';
            }
        } catch (e) {
            // Lỗi mạng tạm thời, bỏ qua để tránh logout nhầm
        }
    }
}, 3000); // Kiểm tra mỗi 3 giây để đảm bảo phản hồi gần như tức thì
