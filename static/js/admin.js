if(localStorage.getItem('role') !== 'ADMIN') window.location.href = '/';

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
    
    if(tabId === 'logs') loadLogs();
}

async function loadDashboard() {
    try {
        const data = await apiCall('/dashboard/admin');
        const tbody = document.getElementById('shopList');
        tbody.innerHTML = '';
        data.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(item.shop_name)}</td>
                <td style="color: var(--success); font-weight: 600;">${item.total_revenue.toLocaleString()} ₫</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast(err.message);
    }
}

async function downloadExcel() {
    try {
        const token = getToken();
        const res = await fetch('/api/export/admin', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if(!res.ok) throw new Error('Export failed');
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'admin_revenue.xlsx';
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast("Đã xuất Excel thành công!");
    } catch (err) {
        showToast(err.message);
    }
}

async function loadLogs() {
    try {
        const data = await apiCall('/logs/admin');
        const tbody = document.getElementById('logList');
        tbody.innerHTML = '';
        data.forEach(item => {
            const dt = new Date(item.created_at).toLocaleString('vi-VN');
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>#${item.id}</td>
                <td>${dt}</td>
                <td><strong>${escapeHtml(item.username)}</strong></td>
                <td><span style="background: #E2E8F0; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">${escapeHtml(item.action)}</span></td>
                <td>${escapeHtml(item.details)}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast(err.message);
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
    if (form) {
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
                errorMsg.innerText = "Mật khẩu mới xác nhận không khớp!";
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
    }

    loadDashboard();
});