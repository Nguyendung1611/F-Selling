const storedRegisterEmail = localStorage.getItem('register_email');
const registerEmail = storedRegisterEmail || t('verify.email_fallback');
const targetEmail = document.getElementById('targetEmail');
const timerDisplay = document.getElementById('timerDisplay');
const verifyHelpActive = document.getElementById('verifyHelpActive');
const verifyHelpExpired = document.getElementById('verifyHelpExpired');
const otpFields = document.querySelectorAll('.otp-field');
let timerInterval = null;
let timeRemaining = 300;

targetEmail.textContent = registerEmail;

function clearVerifyMessage(element) {
    element.textContent = '';
    delete element.dataset.messageKey;
    delete element.dataset.apiMessage;
}

function showVerifyMessage(element, key) {
    element.dataset.messageKey = key;
    delete element.dataset.apiMessage;
    element.textContent = t(key);
}

function showVerifyApiError(element, message) {
    delete element.dataset.messageKey;
    element.dataset.apiMessage = '1';
    element.textContent = message;
}

function setVerifySubmitState(button, key, disabled) {
    button.dataset.i18n = key;
    button.textContent = t(key);
    button.disabled = disabled;
}

function setResendState(key, busy) {
    const resendBtn = document.getElementById('resendBtn');
    resendBtn.dataset.i18n = key;
    resendBtn.textContent = t(key);
    resendBtn.setAttribute('aria-disabled', busy ? 'true' : 'false');
    resendBtn.style.pointerEvents = busy ? 'none' : '';
}

function showExpiredState(expired) {
    verifyHelpActive.style.display = expired ? 'none' : '';
    verifyHelpExpired.style.display = expired ? '' : 'none';
    timerDisplay.style.color = expired ? '#EF4444' : '#F59E0B';
    timerDisplay.parentElement.style.backgroundColor = expired ? '#FEE2E2' : '#FEF3C7';
    timerDisplay.parentElement.style.borderLeftColor = expired ? '#EF4444' : '#F59E0B';
}

function updateTimer() {
    const minutes = Math.floor(timeRemaining / 60);
    const seconds = timeRemaining % 60;
    timerDisplay.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    
    if (timeRemaining <= 0) {
        clearInterval(timerInterval);
        timerInterval = null;
        showExpiredState(true);
        return;
    }
    timeRemaining--;
}

function startTimer(reset = true) {
    if (timerInterval) clearInterval(timerInterval);
    if (reset) {
        timeRemaining = 300;
        localStorage.setItem('otp_send_time', Date.now().toString());
    }
    showExpiredState(false);
    updateTimer();
    if (timeRemaining > 0) timerInterval = setInterval(updateTimer, 1000);
}

// Khôi phục đúng thời gian còn lại nếu người dùng tải lại trang xác thực.
const otpSendTime = Number.parseInt(localStorage.getItem('otp_send_time'), 10);
if (Number.isFinite(otpSendTime)) {
    const elapsedSeconds = Math.floor((Date.now() - otpSendTime) / 1000);
    timeRemaining = Math.max(0, 300 - elapsedSeconds);
}
startTimer(false);

document.addEventListener('fselling:localechange', () => {
    document.querySelectorAll('[data-message-key]').forEach(element => {
        element.textContent = t(element.dataset.messageKey);
    });
    document.querySelectorAll('[data-api-message="1"]').forEach(clearVerifyMessage);
    if (!storedRegisterEmail) targetEmail.textContent = t('verify.email_fallback');
});

// Auto focus flow for OTP fields
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
    const submitBtn = e.currentTarget.querySelector('button[type="submit"]');
    clearVerifyMessage(errorMsg);
    clearVerifyMessage(successMsg);

    // Get combined code
    let code = '';
    otpFields.forEach(field => {
        code += field.value;
    });
    setVerifySubmitState(submitBtn, 'verify.submitting', true);

    try {
        await apiCall('/auth/verify-email', 'POST', {
            email: registerEmail,
            code
        });
        showVerifyMessage(successMsg, 'verify.success');
        alert(t('verify.success'));
        localStorage.removeItem('register_email');
        localStorage.removeItem('otp_send_time');
        redirectToLogin();
    } catch (err) {
        setVerifySubmitState(submitBtn, 'verify.submit', false);
        showVerifyApiError(errorMsg, err.message);
    }
});

document.getElementById('resendBtn').addEventListener('click', async (e) => {
    e.preventDefault();
    if (e.currentTarget.getAttribute('aria-disabled') === 'true') return;

    const errorMsg = document.getElementById('errorMsg');
    const successMsg = document.getElementById('successMsg');
    clearVerifyMessage(errorMsg);
    clearVerifyMessage(successMsg);
    setResendState('verify.resending', true);

    try {
        await apiCall('/auth/resend-code', 'POST', {
            email: registerEmail
        });
        showVerifyMessage(successMsg, 'verify.resend_success');
        // Clear fields
        otpFields.forEach(field => {
            field.value = '';
        });
        otpFields[0].focus();
        startTimer();
    } catch (err) {
        showVerifyApiError(errorMsg, err.message);
    } finally {
        setResendState('verify.resend', false);
    }
});
