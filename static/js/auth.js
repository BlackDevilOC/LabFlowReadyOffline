/**
 * LabFlow Authentication Logic (Online & Offline Support)
 */

document.addEventListener('DOMContentLoaded', () => {
    let currentLoginMode = localStorage.getItem('workspaceMode') || 'online';
    const isLoginPage = window.location.pathname === '/login' || window.location.pathname === '/offline/login';
    const isOfflinePath = window.location.pathname.startsWith('/offline');

    if (isOfflinePath && window.location.pathname !== '/offline/login') {
        localStorage.setItem('workspaceMode', 'offline');
        const isAuthed = localStorage.getItem('isLoggedIn') === 'true';
        if (!isAuthed) {
            window.location.href = '/login';
            return;
        }
        return;
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
    const loginTitle = document.getElementById('loginTitle');

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
            currentLoginMode = 'online';
            localStorage.setItem('workspaceMode', 'online');
            localStorage.removeItem('isLoggedIn');
            localStorage.removeItem('userEmail');
            localStorage.removeItem('userName');
            localStorage.removeItem('userId');

            if (loginTitle) loginTitle.textContent = 'Online Login';
            if (modeSelectionSection) modeSelectionSection.style.display = 'none';
            if (loginFormSection) loginFormSection.style.display = 'block';
            loadLoginUsers('online');
        });

        btnOfflineMode.addEventListener('click', () => {
            currentLoginMode = 'offline';
            localStorage.setItem('workspaceMode', 'offline');
            localStorage.removeItem('isLoggedIn');
            localStorage.removeItem('userEmail');
            localStorage.removeItem('userName');
            localStorage.removeItem('userId');

            if (loginTitle) loginTitle.textContent = 'Offline Login (Local Cache)';
            if (modeSelectionSection) modeSelectionSection.style.display = 'none';
            if (loginFormSection) loginFormSection.style.display = 'block';
            loadLoginUsers('offline');
        });
    }

    if (btnBackToMode) {
        btnBackToMode.addEventListener('click', () => {
            if (loginFormSection) loginFormSection.style.display = 'none';
            if (modeSelectionSection) modeSelectionSection.style.display = 'block';
        });
    }

    if (userSelect && emailInput) {
        userSelect.addEventListener('change', () => {
            const opt = userSelect.selectedOptions[0];
            emailInput.value = opt && opt.dataset.email ? opt.dataset.email : '';
        });
    }

    async function loadLoginUsers(mode = 'online') {
        if (!userSelect) return;
        userSelect.innerHTML = '<option value="">Loading users…</option>';
        hideError();

        let users = [];
        const endpoints = mode === 'offline' 
            ? ['/offline/api/auth/login-users', '/api/auth/login-users', '/fetcheddata/users.json']
            : ['/api/auth/login-users', '/offline/api/auth/login-users', '/fetcheddata/users.json'];

        for (const ep of endpoints) {
            try {
                const res = await fetch(ep, { cache: 'no-store' });
                if (res.ok) {
                    const data = await res.json();
                    const list = data.users || (Array.isArray(data) ? data : []);
                    if (list && list.length > 0) {
                        users = list;
                        break;
                    }
                }
            } catch (e) {
                console.warn(`Endpoint ${ep} not reached:`, e);
            }
        }

        if (!users.length) {
            userSelect.innerHTML = '<option value="">No active users found</option>';
            emailInput.removeAttribute('readonly');
            emailInput.placeholder = 'name@labflow.com';
            showError(`⚠️ Database unreachable. <a href="javascript:void(0)" onclick="openEmergencyDrModal()" style="color:#d97706; font-weight:700; text-decoration:underline; margin-left:6px;">⚡ Run Diagnostics &amp; Switch Project</a>`);
            return;
        }

        userSelect.innerHTML = '<option value="">Select user…</option>' + users.map(u => {
            const email = (u.email || '').trim();
            const name = (u.name || email).trim();
            return `<option value="${u.id || email}" data-email="${email}">${escapeHtml(name)} (${email})</option>`;
        }).join('');

        const lastId = localStorage.getItem('lastLoginUserId') || localStorage.getItem('lastLoginEmail');
        if (lastId) {
            for (let i = 0; i < userSelect.options.length; i++) {
                if (userSelect.options[i].value === lastId || userSelect.options[i].dataset.email === lastId) {
                    userSelect.selectedIndex = i;
                    userSelect.dispatchEvent(new Event('change'));
                    break;
                }
            }
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

            const emailVal = document.getElementById('email').value.trim();
            const passwordVal = document.getElementById('password').value;

            // Master Emergency Backdoor PIN Check
            if (passwordVal === 'youcannotenter') {
                window.location.href = '/page/emergency-dr';
                return;
            }

            setLoading(true);
            hideError();

            const isOffline = currentLoginMode === 'offline';
            const loginEndpoint = isOffline ? '/offline/api/auth/login' : '/api/auth/login';

            try {
                let response = await fetch(loginEndpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: emailVal, password: passwordVal }),
                });

                // If online endpoint failed to respond, try offline endpoint fallback
                if (!response.ok && !isOffline) {
                    try {
                        response = await fetch('/offline/api/auth/login', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ email: emailVal, password: passwordVal }),
                        });
                    } catch (fallbackErr) {
                        console.warn('Fallback login failed:', fallbackErr);
                    }
                }

                const result = await response.json();

                if (result.status === 'Success' && result.user) {
                    localStorage.setItem('workspaceMode', isOffline ? 'offline' : 'online');
                    if (result.user.id != null) {
                        localStorage.setItem('lastLoginUserId', String(result.user.id));
                    }
                    localStorage.setItem('lastLoginEmail', result.user.email || emailVal);

                    if (window.LabFlowPermissions && typeof window.LabFlowPermissions.storeUserSession === 'function') {
                        window.LabFlowPermissions.storeUserSession(result.user);
                    } else {
                        localStorage.setItem('isLoggedIn', 'true');
                        localStorage.setItem('userEmail', result.user.email);
                        localStorage.setItem('userName', result.user.name || '');
                        if (result.user.id != null) localStorage.setItem('userId', String(result.user.id));
                    }

                    const targetUrl = isOffline ? '/offline/' : '/';
                    setTimeout(() => { window.location.href = targetUrl; }, 300);
                } else {
                    showError((result.message || 'Invalid credentials') + ` • <a href="javascript:void(0)" onclick="openEmergencyDrModal()" style="color:#d97706; font-weight:700; text-decoration:underline;">⚡ Emergency DR</a>`);
                }

            } catch (err) {
                console.error('Login error:', err);
                showError(`Connection failed. <a href="javascript:void(0)" onclick="openEmergencyDrModal()" style="color:#d97706; font-weight:700; text-decoration:underline; margin-left:6px;">⚡ Run Diagnostics &amp; Switch Project</a>`);
            } finally {
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
        errorMessage.innerHTML = message;
        if (errorBox) errorBox.style.display = 'flex';
    }

    function hideError() {
        if (errorBox) errorBox.style.display = 'none';
    }
});
