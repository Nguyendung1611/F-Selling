function clearRegisterMessage(element) {
    element.textContent = '';
    delete element.dataset.messageKey;
    delete element.dataset.apiMessage;
}

function showRegisterMessage(element, key) {
    element.dataset.messageKey = key;
    delete element.dataset.apiMessage;
    element.textContent = t(key);
}

function showRegisterApiError(element, message) {
    delete element.dataset.messageKey;
    element.dataset.apiMessage = '1';
    element.textContent = message;
}

function setRegisterSubmitState(button, key, disabled) {
    button.dataset.i18n = key;
    button.textContent = t(key);
    button.disabled = disabled;
}

document.addEventListener('fselling:localechange', () => {
    document.querySelectorAll('[data-message-key]').forEach(element => {
        element.textContent = t(element.dataset.messageKey);
    });
    document.querySelectorAll('[data-api-message="1"]').forEach(clearRegisterMessage);
});

document.getElementById('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const confirm = document.getElementById('confirm_password').value;
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const errorMsg = document.getElementById('errorMsg');

    clearRegisterMessage(errorMsg);
    
    if (password !== confirm) {
        showRegisterMessage(errorMsg, 'auth.validation.password_mismatch');
        return;
    }

    const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_]).+$/;
    if (!regex.test(password)) {
        showRegisterMessage(errorMsg, 'auth.validation.password_policy');
        return;
    }

    try {
        setRegisterSubmitState(submitBtn, 'register.submitting', true);
        await apiCall('/auth/register', 'POST', { username, email, password, role: 'SELLER' });
        localStorage.setItem('register_email', email);
        localStorage.setItem('otp_send_time', Date.now().toString());
        alert(t('register.success_redirect'));
        navigateToPage('/verify');
    } catch (err) {
        setRegisterSubmitState(submitBtn, 'register.submit', false);
        showRegisterApiError(errorMsg, err.message);
    }
});
