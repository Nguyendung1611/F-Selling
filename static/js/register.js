document.getElementById('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const confirm = document.getElementById('confirm_password').value;
    const submitBtn = e.target.querySelector('button[type="submit"]');
    
    if(password !== confirm) {
        return document.getElementById('errorMsg').innerText = "Mật khẩu xác nhận không khớp!";
    }

    const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
    if (!regex.test(password)) {
        return document.getElementById('errorMsg').innerText = "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số!";
    }

    try {
        submitBtn.disabled = true;
        submitBtn.innerText = "Đang đăng ký...";
        await apiCall('/auth/register', 'POST', { username, email, password, role: 'SELLER' });
        localStorage.setItem('register_email', email);
        localStorage.setItem('otp_send_time', Date.now().toString());
        alert("Đăng ký thành công! Đang chuyển hướng về trang xác thực tài khoản...");
        window.location.href = "/verify";
    } catch (err) {
        submitBtn.disabled = false;
        submitBtn.innerText = "Đăng ký";
        document.getElementById('errorMsg').innerText = err.message;
    }
});