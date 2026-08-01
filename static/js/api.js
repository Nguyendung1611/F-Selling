const BASE_URL = '/api';
let cachedToken = localStorage.getItem('token');
const AUTH_STORAGE_KEYS = Object.freeze([
    'token',
    'role',
    'staff_role',
    'username',
    'currentShopId',
    'register_email',
    'otp_send_time'
]);

function currentLanguage() {
    return window.FSellingI18n?.getLocale?.() || 'vi';
}

// Chỉ xóa dữ liệu phiên đăng nhập. Lựa chọn ngôn ngữ và cài đặt đọc tiền
// thuộc về thiết bị nên phải còn nguyên sau logout/401.
function clearAuthState() {
    AUTH_STORAGE_KEYS.forEach(key => localStorage.removeItem(key));
    cachedToken = null;
}

// Dùng URL mới sau logout/401 để trình duyệt không khôi phục một bản HTML
// đăng nhập cũ từ back-forward cache. Locale vẫn nằm trong localStorage và
// được i18n.js áp dụng ngay khi trang mới nạp xong.
function redirectToLogin() {
    window.location.replace(`/?auth=${Date.now()}`);
}

function navigateToPage(path) {
    const separator = path.includes('?') ? '&' : '?';
    window.location.href = `${path}${separator}entry=${Date.now()}`;
}

function hasLocalAccessToPage(pathname) {
    const token = localStorage.getItem('token');
    const role = localStorage.getItem('role');
    if (!token) return false;
    if (pathname === '/admin') return role === 'ADMIN';
    if (pathname === '/seller' || pathname === '/pos') {
        return role === 'SELLER' || role === 'STAFF';
    }
    return true;
}

// Back/Forward Cache có thể khôi phục nguyên một trang được bảo vệ mà không
// chạy lại các dòng kiểm tra ở đầu file trang. Kiểm tra lại khi pageshow để
// nút Back sau logout không làm lộ dashboard/POS cũ.
window.addEventListener('pageshow', event => {
    if (
        !event.persisted
        || !['/admin', '/seller', '/pos'].includes(window.location.pathname)
    ) {
        return;
    }
    if (!hasLocalAccessToPage(window.location.pathname)) {
        redirectToLogin();
        return;
    }
    // Nếu người dùng đã đăng nhập tài khoản khác rồi bấm Back, document trong
    // BFCache vẫn mang cachedToken và dữ liệu của phiên cũ. Nạp lại trang để
    // lấy đúng tài khoản, locale và dữ liệu hiện tại.
    if (localStorage.getItem('token') !== cachedToken) {
        window.location.replace(
            `${window.location.pathname}?session=${Date.now()}`
        );
        return;
    }
    const storedLocale = localStorage.getItem(
        window.FSellingI18n?.STORAGE_KEY || 'fselling.locale'
    );
    const locale = window.FSellingI18n?.SUPPORTED?.includes(storedLocale)
        ? storedLocale
        : 'vi';
    if (locale !== currentLanguage()) {
        setLanguage(locale, { persist: false });
    }
});

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

// Khóa bản dịch + màu cho trạng thái đơn hàng.
// Trạng thái lạ (do backend thêm sau này) vẫn hiển thị được, không vỡ giao diện.
const NHAN_TRANG_THAI_DON = {
    PENDING:      { key: 'common.status.pending',      color: '#F59E0B' },
    PAID:         { key: 'common.status.paid',         color: 'var(--success)' },
    CANCELLED:    { key: 'common.status.cancelled',    color: '#94A3B8' },
    UNRECONCILED: { key: 'common.status.unreconciled', color: '#EF4444' },
    // F4: bán ghi nợ. Thiếu dòng này thì mọi màn hiện chữ "DEBT" trần.
    DEBT:         { key: 'common.status.debt',         color: '#B45309' }
};

function moTaTrangThaiDon(status) {
    const description = NHAN_TRANG_THAI_DON[status];
    if (!description) return { label: status, color: '#94A3B8' };
    return { label: t(description.key), color: description.color };
}

/**
 * Đổi mốc thời gian do server trả về thành giờ địa phương đọc được.
 *
 * Server lưu bằng `datetime.utcnow()` nên chuỗi trả về là giờ UTC nhưng KHÔNG
 * kèm ký hiệu múi giờ, ví dụ "2026-07-29T18:41:52". Trình duyệt gặp chuỗi kiểu
 * đó sẽ hiểu là giờ địa phương, nên giờ hiển thị bị lệch đúng bằng múi giờ máy
 * - ở Việt Nam là 7 tiếng, khiến đơn bán buổi tối bị ghi lùi sang hôm trước.
 * Thêm "Z" để trình duyệt hiểu đúng là UTC rồi tự quy về giờ máy.
 *
 * Chuỗi đã có sẵn múi giờ ("Z" hoặc "+07:00") thì giữ nguyên.
 */
function dinhDangNgayGio(chuoi) {
    if (window.FSellingI18n?.formatDateTime) {
        return window.FSellingI18n.formatDateTime(chuoi);
    }
    if (!chuoi) return '';
    let s = String(chuoi);
    if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += 'Z';
    const d = new Date(s);
    return isNaN(d.getTime()) ? String(chuoi) : d.toLocaleString('vi-VN');
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
        'Content-Type': 'application/json',
        'Accept-Language': currentLanguage()
    };
    
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const options = { method, headers, cache: 'no-store' };
    if (body) {
        options.body = JSON.stringify(body);
    }

    let res;
    try {
        res = await fetch(`${BASE_URL}${endpoint}`, options);
    } catch (error) {
        throw new Error(t('common.network_error'));
    }
    if (res.status === 401 && !endpoint.includes('/auth/login')) {
        // Chỉ xóa localStorage nếu token hiện tại trong localStorage trùng với token cũ của tab này
        if (localStorage.getItem('token') === cachedToken) {
            clearAuthState();
        }
        redirectToLogin();
        return;
    }
    
    if (res.headers.get('Content-Disposition')) {
        return res; // Return raw response for file downloads
    }
    
    let data = null;
    try {
        const rawBody = await res.text();
        data = rawBody ? JSON.parse(rawBody) : null;
    } catch (error) {
        const parseError = new Error(t('common.api_error'));
        parseError.status = res.status;
        throw parseError;
    }
    if (!res.ok) {
        let msg = data?.detail || t('common.api_error');
        if (Array.isArray(msg) && msg.length > 0 && msg[0].msg) {
            msg = msg[0].msg;
        } else if (typeof msg === 'object') {
            msg = JSON.stringify(msg);
        }
        const error = new Error(msg);
        error.status = res.status;
        throw error;
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
    clearAuthState();
    redirectToLogin();
}

// Tự động phát hiện khi đăng nhập ở tab khác trên cùng trình duyệt (Lập tức logout tab cũ)
window.addEventListener('storage', (e) => {
    if (e.key === 'token') {
        if (e.newValue !== cachedToken) {
            redirectToLogin();
        }
    }
});

// Định kỳ kiểm tra phiên đăng nhập với server (Lập tức logout nếu đăng nhập ở thiết bị/trình duyệt khác)
setInterval(async () => {
    const token = getToken();
    if (token) {
        try {
            const res = await fetch(`${BASE_URL}/auth/session-check`, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Accept-Language': currentLanguage()
                },
                cache: 'no-store'
            });
            if (res.status === 401) {
                if (localStorage.getItem('token') === cachedToken) {
                    clearAuthState();
                }
                redirectToLogin();
            }
        } catch (e) {
            // Lỗi mạng tạm thời, bỏ qua để tránh logout nhầm
        }
    }
}, 3000); // Kiểm tra mỗi 3 giây để đảm bảo phản hồi gần như tức thì
