/**
 * LabFlow Simplified Authentication Logic
 * Note: This is for testing purposes with plain-text passwords.
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Basic Protection Logic
    const isLoginPage = window.location.pathname === '/login';
    const isOfflinePath = window.location.pathname.startsWith('/offline');

    if (isOfflinePath) {
        localStorage.setItem('workspaceMode', 'offline');
        return;
    }

    if (isLoginPage) {
        if (!navigator.onLine) {
            localStorage.setItem('workspaceMode', 'offline');
            window.location.href = '/offline/';
            return;
        }
    }

    const isAuthenticated = localStorage.getItem('isLoggedIn') === 'true';

    if (!isLoginPage && !isAuthenticated) {
        window.location.href = '/login';
        return;
    }

    // 2. Login Handling
    const loginForm = document.getElementById('loginForm');
    const loginBtn = document.getElementById('loginBtn');
    const loader = document.getElementById('loader');
    const btnText = loginBtn ? loginBtn.querySelector('.btn-text') : null;
    const errorBox = document.getElementById('errorBox');
    const errorMessage = document.getElementById('errorMessage');

    const userSelect = document.getElementById('userSelect');
    const emailInput = document.getElementById('email');

    // Mode Switcher Selectors
    const btnOnlineMode = document.getElementById('btnOnlineMode');
    const btnOfflineMode = document.getElementById('btnOfflineMode');
    const btnBackToMode = document.getElementById('btnBackToMode');
    const modeSelectionSection = document.getElementById('modeSelectionSection');
    const loginFormSection = document.getElementById('loginFormSection');

    if (btnOnlineMode && btnOfflineMode) {
        btnOnlineMode.addEventListener('click', () => {
            localStorage.setItem('workspaceMode', 'online');
            // Clear any active offline session so they must authenticate online
            localStorage.removeItem('isLoggedIn');
            localStorage.removeItem('userEmail');
            localStorage.removeItem('userName');
            localStorage.removeItem('userId');
            
            modeSelectionSection.style.display = 'none';
            loginFormSection.style.display = 'block';
            loadLoginUsers();
        });

        btnOfflineMode.addEventListener('click', () => {
            localStorage.setItem('workspaceMode', 'offline');
            localStorage.setItem('isLoggedIn', 'true');
            localStorage.setItem('userEmail', 'offline@labflow.com');
            localStorage.setItem('userName', 'Offline User');
            window.location.href = '/offline/';
        });
    }

    if (btnBackToMode) {
        btnBackToMode.addEventListener('click', () => {
            loginFormSection.style.display = 'none';
            modeSelectionSection.style.display = 'block';
        });
    }

    if (userSelect && emailInput) {
        userSelect.addEventListener('change', () => {
            const opt = userSelect.selectedOptions[0];
            emailInput.value = opt && opt.dataset.email ? opt.dataset.email : '';
        });
    }

    async function loadLoginUsers() {
        if (!userSelect) return;
        try {
            const res = await fetch('/api/auth/login-users');
            const data = await res.json();
            const users = data.users || [];
            if (!users.length) {
                userSelect.innerHTML = '<option value="">No active users found</option>';
                emailInput.removeAttribute('readonly');
                emailInput.placeholder = 'name@labflow.com';
                return;
            }
            userSelect.innerHTML = '<option value="">Select user…</option>' + users.map(u =>
                `<option value="${u.id}" data-email="${u.email}">${escapeHtml(u.name)} (${u.email})</option>`
            ).join('');
            const lastId = localStorage.getItem('lastLoginUserId');
            if (lastId) {
                userSelect.value = lastId;
                userSelect.dispatchEvent(new Event('change'));
            }
        } catch (err) {
            console.error('Failed to load users (likely no internet):', err);
            userSelect.innerHTML = '<option value="">Could not load users</option>';
            emailInput.removeAttribute('readonly');
            emailInput.placeholder = 'name@labflow.com';

            showError('Unable to connect to online services. Redirecting to offline mode in 3 seconds...');
            setTimeout(() => {
                localStorage.setItem('workspaceMode', 'offline');
                window.location.href = '/offline/';
            }, 3000);
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const emailInput = document.getElementById('email').value.trim();
            const passwordInput = document.getElementById('password').value;

            setLoading(true);
            hideError();

            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: emailInput, password: passwordInput }),
                });
                const result = await response.json();

                if (result.status === 'Success' && result.user) {
                    localStorage.setItem('workspaceMode', 'online');
                    if (result.user.id != null) {
                        localStorage.setItem('lastLoginUserId', String(result.user.id));
                    }
                    if (window.LabFlowPermissions) {
                        LabFlowPermissions.storeUserSession(result.user);
                    } else {
                        localStorage.setItem('isLoggedIn', 'true');
                        localStorage.setItem('userEmail', result.user.email);
                        localStorage.setItem('userName', result.user.name || '');
                        if (result.user.id != null) localStorage.setItem('userId', String(result.user.id));
                        if (result.user.default_shift) localStorage.setItem('defaultShift', result.user.default_shift);
                        if (result.user.default_shift_id != null) localStorage.setItem('defaultShiftId', String(result.user.default_shift_id));
                    }
                    setTimeout(() => { window.location.href = '/'; }, 500);
                } else {
                    showError(result.message || 'Access denied. Contact your administrator.');
                    setLoading(false);
                }

            } catch (error) {
                console.error('Login error:', error);
                showError('Server error. Please try again later.');
                setLoading(false);
            }
        });
    }

    function setLoading(isLoading) {
        if (!loginBtn) return;
        if (isLoading) {
            loginBtn.disabled = true;
            if (loader) loader.style.display = 'block';
            if (btnText) btnText.style.opacity = '0.5';
        } else {
            loginBtn.disabled = false;
            if (loader) loader.style.display = 'none';
            if (btnText) btnText.style.opacity = '1';
        }
    }

    function showError(message) {
        if (!errorMessage) return;
        errorMessage.textContent = message;
        errorBox.style.display = 'flex';
    }

    function hideError() {
        if (errorBox) errorBox.style.display = 'none';
    }
});
