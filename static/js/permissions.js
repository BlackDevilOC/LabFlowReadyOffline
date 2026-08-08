/**
 * Apply sidebar visibility from stored user permissions (localStorage).
 */
(function (global) {
    const ROUTE_PERMISSION = {
        '/register': 'register',
        '/update-results': 'update_results',
        '/page/fitness': 'fitness',
        '/page/print-records': 'print',
        '/page/lab-print-records': 'print',
        '/page/fluid-reports': 'fluid_reports',
    };

    function getStoredPermissions() {
        try {
            const raw = global.localStorage.getItem('userPermissions');
            if (!raw) return null;
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }

    function canAccess(permKey) {
        const perms = getStoredPermissions();
        if (!perms) return true;
        return !!perms[permKey];
    }

    function applySidebarPermissions() {
        document.querySelectorAll('.nav-item[href]').forEach(link => {
            const href = link.getAttribute('href') || '';
            if (href === '#' || href.startsWith('/page/admin')) return;
            const perm = ROUTE_PERMISSION[href];
            if (!perm) return;
            const li = link.closest('li');
            if (!canAccess(perm)) {
                if (li) li.style.display = 'none';
                else link.style.display = 'none';
            } else {
                if (li) li.style.display = '';
                else link.style.display = '';
            }
        });
        const adminBtn = document.getElementById('sidebarAdminBtn');
        if (adminBtn) {
            const li = adminBtn.closest('li');
            const show = canAccess('admin') || canAccess('manage_users') || canAccess('manage_tests');
            if (li) li.style.display = show ? '' : 'none';
        }
    }

    global.LabFlowPermissions = {
        getStoredPermissions,
        canAccess,
        applySidebarPermissions,
        storeUserSession(user) {
            if (!user) return;
            global.localStorage.setItem('isLoggedIn', 'true');
            global.localStorage.setItem('userEmail', user.email || '');
            global.localStorage.setItem('userName', user.name || '');
            if (user.id != null) global.localStorage.setItem('userId', String(user.id));
            if (user.permissions) {
                global.localStorage.setItem('userPermissions', JSON.stringify(user.permissions));
            } else {
                global.localStorage.removeItem('userPermissions');
            }
            if (user.default_shift) {
                global.localStorage.setItem('defaultShift', user.default_shift);
            } else {
                global.localStorage.removeItem('defaultShift');
            }
            if (user.default_shift_id != null && user.default_shift_id !== '') {
                global.localStorage.setItem('defaultShiftId', String(user.default_shift_id));
            } else {
                global.localStorage.removeItem('defaultShiftId');
            }
        },
        clearSession() {
            ['isLoggedIn', 'userEmail', 'userName', 'userId', 'userPermissions', 'defaultShift', 'defaultShiftId'].forEach(k => {
                global.localStorage.removeItem(k);
            });
        },
    };

    document.addEventListener('DOMContentLoaded', applySidebarPermissions);
})(window);
