document.addEventListener('DOMContentLoaded', () => {
    // 1. Basic Auth Guard (Client-side)
    const path = window.location.pathname;
    const isLoginPage = path === '/login' || path === '/offline/login';
    const isOfflinePath = path.startsWith('/offline');
    const isAdminPage = /\/page\/admin/.test(path);
    const adminAuthed = sessionStorage.getItem('admin_authed') === 'true';

    if (isOfflinePath) {
        localStorage.setItem('workspaceMode', 'offline');
        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('userEmail', 'offline@labflow.com');
        localStorage.setItem('userName', 'Offline User');
    }

    const isAuthenticated = localStorage.getItem('isLoggedIn') === 'true';

    // Allow admin console after login-page admin password (no full user login required)
    if (!isLoginPage && !isAuthenticated && !(isAdminPage && adminAuthed)) {
        window.location.href = isOfflinePath ? '/offline/login' : '/login';
        return;
    }

    // Update user profile name if logged in
    if (isAuthenticated) {
        const userNameElement = document.querySelector('.user-name');
        const storedName = localStorage.getItem('userName');
        const userEmail = localStorage.getItem('userEmail');

        if (userNameElement) {
            if (storedName && storedName.trim() !== '') {
                userNameElement.textContent = storedName;
            } else if (userEmail) {
                // Fallback: Show only the part before @
                userNameElement.textContent = userEmail.split('@')[0];
            }
        }
    }

    // Handle logout link
    const logoutBtn = document.querySelector('.logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            if (window.LabFlowPermissions) {
                LabFlowPermissions.clearSession();
            } else {
                localStorage.removeItem('isLoggedIn');
                localStorage.removeItem('userEmail');
                localStorage.removeItem('userName');
                localStorage.removeItem('userId');
                localStorage.removeItem('userPermissions');
            }
            // Allow default navigation to /logout
        });
    }

    const userMenuToggle = document.getElementById('userMenuToggle');
    const userDropdown = document.getElementById('userDropdown');

    if (userMenuToggle && userDropdown) {
        userMenuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            userDropdown.classList.toggle('show');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!userMenuToggle.contains(e.target) && !userDropdown.contains(e.target)) {
                userDropdown.classList.remove('show');
            }
        });
    }

    // ── Global Keyboard Shortcut: Ctrl + S (Focus Search Box) ────────────────
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            e.preventDefault();
            const searchBox = document.querySelector(
                '#online-test-search-filter, #offline-sync-search, #offline-sync-log-search, #logDateFilter, #search-input, #search, .search-input, input[type="search"], input[id*="search"], input[class*="search"], input[placeholder*="Search"], input[placeholder*="search"]'
            );
            if (searchBox) {
                searchBox.focus();
                if (typeof searchBox.select === 'function') {
                    searchBox.select();
                }
            }
        }
    });
});
