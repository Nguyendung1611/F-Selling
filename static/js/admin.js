if (localStorage.getItem('role') !== 'ADMIN') redirectToLogin();

let dashboardData = null;
let logData = null;

function switchTab(tabId, tabButton) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    if (tabButton) tabButton.classList.add('active');
    
    if (tabId === 'logs') loadLogs();
}

function renderDashboard() {
    if (!dashboardData) return;
    const tbody = document.getElementById('shopList');
    tbody.innerHTML = '';

    if (dashboardData.length === 0) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="2" style="text-align: center; color: var(--text-muted);">${escapeHtml(t('admin.dashboard.no_shops'))}</td>`;
        tbody.appendChild(tr);
        return;
    }

    dashboardData.forEach(item => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHtml(item.shop_name)}</td>
            <td style="color: var(--success); font-weight: 600;">${escapeHtml(dinhDangTienTe(item.total_revenue))}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadDashboard() {
    try {
        dashboardData = await apiCall('/dashboard/admin');
        renderDashboard();
    } catch (err) {
        showAdminApiToast(err.message);
    }
}

async function downloadExcel() {
    try {
        const token = getToken();
        const headers = {
            'Accept-Language': getCurrentLocale()
        };
        if (token) headers.Authorization = `Bearer ${token}`;
        const res = await fetch('/api/export/admin', {
            headers
        });
        if (!res.ok) throw new Error(t('common.export_failed'));
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'admin_revenue.xlsx';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        showAdminToast('common.export_success');
    } catch (err) {
        showAdminToast('common.export_failed');
    }
}

function renderLogs() {
    if (!logData) return;
    const tbody = document.getElementById('logList');
    tbody.innerHTML = '';

    if (logData.length === 0) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="5" style="text-align: center; color: var(--text-muted);">${escapeHtml(t('admin.logs.no_logs'))}</td>`;
        tbody.appendChild(tr);
        return;
    }

    logData.forEach(item => {
        const dt = dinhDangNgayGio(item.created_at);
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>#${escapeHtml(item.id)}</td>
            <td>${escapeHtml(dt)}</td>
            <td><strong>${escapeHtml(item.username)}</strong></td>
            <td><span style="background: #E2E8F0; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">${escapeHtml(item.action)}</span></td>
            <td>${escapeHtml(item.details)}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadLogs() {
    try {
        logData = await apiCall('/logs/admin');
        renderLogs();
    } catch (err) {
        showAdminApiToast(err.message);
    }
}

function showAdminToast(key) {
    const toast = document.getElementById('toast');
    toast.dataset.messageKey = key;
    delete toast.dataset.apiMessage;
    showToast(t(key));
}

function showAdminApiToast(message) {
    const toast = document.getElementById('toast');
    delete toast.dataset.messageKey;
    toast.dataset.apiMessage = '1';
    showToast(message);
}

function clearChangePasswordMessage(element) {
    element.textContent = '';
    delete element.dataset.messageKey;
    delete element.dataset.apiMessage;
}

function showChangePasswordMessage(element, key) {
    element.dataset.messageKey = key;
    delete element.dataset.apiMessage;
    element.textContent = t(key);
}

function showChangePasswordApiError(element, message) {
    delete element.dataset.messageKey;
    element.dataset.apiMessage = '1';
    element.textContent = message;
}

function setChangePasswordSubmitState(button, key, disabled) {
    button.dataset.i18n = key;
    button.textContent = t(key);
    button.disabled = disabled;
}

// ĐỔI MẬT KHẨU
function showChangePasswordModal() {
    document.getElementById('changePasswordModal').style.display = 'flex';
    clearChangePasswordMessage(document.getElementById('changePasswordErrorMsg'));
    clearChangePasswordMessage(document.getElementById('changePasswordSuccessMsg'));
    document.getElementById('oldPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('confirmNewPassword').value = '';
    setChangePasswordSubmitState(
        document.querySelector('#changePasswordForm button[type="submit"]'),
        'admin.change_password.submit',
        false
    );
    document.getElementById('oldPassword').focus();
}

function closeChangePasswordModal() {
    document.getElementById('changePasswordModal').style.display = 'none';
}

document.addEventListener('fselling:localechange', () => {
    renderDashboard();
    renderLogs();

    document.querySelectorAll('[data-message-key]').forEach(element => {
        element.textContent = t(element.dataset.messageKey);
    });
    document.querySelectorAll('[data-api-message="1"]').forEach(element => {
        element.textContent = '';
        delete element.dataset.apiMessage;
        if (element.id === 'toast') element.style.display = 'none';
    });
});

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('changePasswordForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const old_password = document.getElementById('oldPassword').value;
            const new_password = document.getElementById('newPassword').value;
            const confirm = document.getElementById('confirmNewPassword').value;
            const errorMsg = document.getElementById('changePasswordErrorMsg');
            const successMsg = document.getElementById('changePasswordSuccessMsg');
            const submitBtn = e.currentTarget.querySelector('button[type="submit"]');
            clearChangePasswordMessage(errorMsg);
            clearChangePasswordMessage(successMsg);
            
            if (new_password !== confirm) {
                showChangePasswordMessage(errorMsg, 'auth.validation.new_password_mismatch');
                return;
            }
            
            const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
            if (!regex.test(new_password)) {
                showChangePasswordMessage(errorMsg, 'auth.validation.new_password_policy');
                return;
            }

            setChangePasswordSubmitState(
                submitBtn,
                'admin.change_password.submitting',
                true
            );
            
            try {
                const res = await apiCall('/auth/change-password', 'POST', { old_password, new_password });
                showChangePasswordMessage(successMsg, 'admin.change_password.success');
                localStorage.setItem('token', res.access_token);
                // Toast chứ không phải alert: câu thông báo ở trên nằm TRONG
                // modal nên đóng modal là nó biến mất theo, còn alert() thì
                // Chrome chặn được và khi bị chặn người dùng không thấy gì cả.
                showToast(t('admin.change_password.success'));
                closeChangePasswordModal();
                setChangePasswordSubmitState(
                    submitBtn,
                    'admin.change_password.submit',
                    false
                );
            } catch (err) {
                setChangePasswordSubmitState(
                    submitBtn,
                    'admin.change_password.submit',
                    false
                );
                showChangePasswordApiError(errorMsg, err.message);
            }
        });
    }

    loadDashboard();
});
