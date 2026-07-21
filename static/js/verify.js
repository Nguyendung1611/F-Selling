const registerEmail = localStorage.getItem('register_email') || 'your-email@example.com';
document.getElementById('targetEmail').innerText = registerEmail;

// Timer setup (5 minutes = 300 seconds)
let timeRemaining = 300;
const timerDisplay = document.getElementById('timerDisplay');
let timerInterval = null;

// Check if OTP send time is stored, calculate remaining time
const otpSendTime = localStorage.getItem('otp_send_time');
if (otpSendTime) {
    const elapsedSeconds = Math.floor((Date.now() - parseInt(otpSendTime)) / 1000);
    timeRemaining = Math.max(0, 300 - elapsedSeconds);
    localStorage.removeItem('otp_send_time');
}

function updateTimer() {
    const minutes = Math.floor(timeRemaining / 60);
    const seconds = timeRemaining % 60;
    timerDisplay.innerText = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    
    if (timeRemaining <= 0) {
        clearInterval(timerInterval);
        timerDisplay.style.color = '#EF4444';
        timerDisplay.parentElement.style.backgroundColor = '#FEE2E2';
        timerDisplay.parentElement.style.borderLeftColor = '#EF4444';
        document.querySelector('[style*="Không nhận được"]').parentElement.innerHTML = '<p style="font-size: 0.9rem; color: var(--text-muted);">Mã xác thực đã hết hạn. <a href="/" style="color: var(--primary); font-weight: 600;">Đăng ký lại</a></p>';
        return;
    }
    timeRemaining--;
}

function startTimer() {
    timeRemaining = 300;
    updateTimer();
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(updateTimer, 1000);
}

// Start timer on page load
startTimer();

// Auto focus flow for OTP fields
const otpFields = document.querySelectorAll('.otp-field');
otpFields.forEach((field, index) => {
    field.addEventListener('input', (e) => {
        if (e.target.value.length === 1 && index < otpFields.length - 1) {
            otpFields[index + 1].focus();
        }
    });
    field.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && e.target.value.length === 0 && index > 0) {
            otpFields[index - 1].focus();
        }
    });
    // Handle paste of whole 6-digit OTP code
    field.addEventListener('paste', (e) => {
        const pasteData = e.clipboardData.getData('text');
        if (pasteData.length === 6 && /^\d+$/.test(pasteData)) {
            otpFields.forEach((f, i) => {
                f.value = pasteData[i];
            });
            otpFields[5].focus();
            e.preventDefault();
        }
    });
});

document.getElementById('verifyForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorMsg = document.getElementById('errorMsg');
    const successMsg = document.getElementById('successMsg');
    errorMsg.innerText = '';
    successMsg.innerText = '';

    // Get combined code
    let code = '';
    otpFields.forEach(f => code += f.value);

    try {
        const res = await apiCall('/auth/verify-email', 'POST', {
            email: registerEmail,
            code: code
        });
        successMsg.innerText = res.msg;
        alert(res.msg);
        localStorage.removeItem('register_email');
        window.location.href = '/';
    } catch (err) {
        errorMsg.innerText = err.message;
    }
});

document.getElementById('resendBtn').addEventListener('click', async (e) => {
    e.preventDefault();
    const errorMsg = document.getElementById('errorMsg');
    const successMsg = document.getElementById('successMsg');
    errorMsg.innerText = '';
    successMsg.innerText = '';

    try {
        const res = await apiCall('/auth/resend-code', 'POST', {
            email: registerEmail
        });
        successMsg.innerText = res.msg;
        // Clear fields
        otpFields.forEach(f => f.value = '');
        otpFields[0].focus();
        // Restart timer
        startTimer();
        // Reset timer display styling
        timerDisplay.style.color = '#F59E0B';
        timerDisplay.parentElement.style.backgroundColor = '#FEF3C7';
        timerDisplay.parentElement.style.borderLeftColor = '#F59E0B';
    } catch (err) {
        errorMsg.innerText = err.message;
    }
});