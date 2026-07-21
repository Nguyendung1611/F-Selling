document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const errorMsg = document.getElementById('errorMsg');


    try {
        const data = await apiCall('/auth/login', 'POST', { username, password });
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('role', data.role);
        if (data.role === 'ADMIN') {
            window.location.href = '/admin';
        } else {
            window.location.href = '/seller';
        }
    } catch (err) {
        // Kiểm tra nếu là lỗi 401 hoặc lỗi xác thực, hiển thị message chung
        if (err.message.includes('401') || err.message.includes('không chính xác') || err.message.includes('không đúng') || err.message.includes('Unauthorized')) {
            errorMsg.innerText = "Tên đăng nhập hoặc mật khẩu không đúng";
            console.log(errorMsg);
        } else {
            errorMsg.innerText = err.message;
        }
    }
});

// HÀM QUÊN MẬT KHẨU
function showForgotModal() {
    document.getElementById('forgotModal').style.display = 'flex';
    document.getElementById('forgotStep1Form').style.display = 'block';
    document.getElementById('forgotStep2Form').style.display = 'none';
    document.getElementById('forgotErrorMsg').innerText = '';
    document.getElementById('forgotSuccessMsg').innerText = '';
    document.getElementById('forgotEmail').value = '';
    document.getElementById('forgotOTP').value = '';
    document.getElementById('forgotNewPassword').value = '';
    document.getElementById('forgotConfirmPassword').value = '';
}

function closeForgotModal() {
    document.getElementById('forgotModal').style.display = 'none';
}

document.getElementById('forgotStep1Form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('forgotEmail').value;
    const errorMsg = document.getElementById('forgotErrorMsg');
    const successMsg = document.getElementById('forgotSuccessMsg');
    errorMsg.innerText = '';
    successMsg.innerText = '';
    
    try {
        const res = await apiCall('/auth/forgot-password-request', 'POST', { email });
        successMsg.innerText = res.msg;
        setTimeout(() => {
            document.getElementById('forgotStep1Form').style.display = 'none';
            document.getElementById('forgotStep2Form').style.display = 'block';
            successMsg.innerText = '';
        }, 1500);
    } catch (err) {
        errorMsg.innerText = err.message;
    }
});

document.getElementById('forgotStep2Form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('forgotEmail').value;
    const code = document.getElementById('forgotOTP').value;
    const new_password = document.getElementById('forgotNewPassword').value;
    const confirm = document.getElementById('forgotConfirmPassword').value;
    const errorMsg = document.getElementById('forgotErrorMsg');
    const successMsg = document.getElementById('forgotSuccessMsg');
    errorMsg.innerText = '';
    successMsg.innerText = '';
    
    if (new_password !== confirm) {
        errorMsg.innerText = "Mật khẩu xác nhận không khớp!";
        return;
    }
    
    const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
    if (!regex.test(new_password)) {
        errorMsg.innerText = "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số!";
        return;
    }
    
    try {
        const res = await apiCall('/auth/forgot-password-reset', 'POST', { email, code, new_password });
        successMsg.innerText = res.msg;
        alert(res.msg);
        closeForgotModal();
    } catch (err) {
        errorMsg.innerText = err.message;
    }
});