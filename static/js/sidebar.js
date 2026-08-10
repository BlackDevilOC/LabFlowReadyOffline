document.addEventListener('DOMContentLoaded', () => {
    const navItems = document.querySelectorAll('.nav-item');
    const currentPath = window.location.pathname;

    // 1. Highlight active menu items based on URL
    const currentFullUrl = currentPath + window.location.search;
    navItems.forEach(item => {
        const href = item.getAttribute('href');
        let isActive = false;

        if (href && href !== '#') {
            if (currentPath === href || currentFullUrl === href) {
                isActive = true;
            } else if (href === '/page/fluid-reports') {
                // Highlight 'Fluid Reports' for any individual fluid pages
                const fluidPaths = ['/page/ascitic-fluid', '/page/csf-fluid', '/page/pleural-fluid'];
                if (fluidPaths.includes(currentPath)) {
                    isActive = true;
                }
            } else if (href.includes('sync-history') && currentPath.includes('sync-history')) {
                isActive = true;
            }
        }

        if (isActive) {
            item.classList.add('active');

            // If the active item is inside a submenu, auto-expand the parent dropdown
            const parentDropdown = item.closest('.sidebar-dropdown');
            if (parentDropdown) {
                parentDropdown.classList.add('open');
            }
        }
    });

    // 2. Handle simple navigation item clicks (excluding dropdown toggle itself)
    navItems.forEach(item => {
        item.addEventListener('click', function (e) {
            if (this.classList.contains('dropdown-toggle')) {
                return; // Dropdown toggle click is handled separately below
            }
            // Remove active class from all items
            navItems.forEach(nav => nav.classList.remove('active'));

            // Add active class to clicked item
            this.classList.add('active');
        });
    });

    // 3. Handle Collapsible Dropdown Toggles
    const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            const parentDropdown = this.closest('.sidebar-dropdown');
            if (parentDropdown) {
                parentDropdown.classList.toggle('open');
            }
        });
    });

    // 4. Admin panel (password based)
    const adminBtn = document.getElementById('sidebarAdminBtn');
    if (adminBtn) {
        adminBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const pwd = prompt('Enter admin password:');
            if (pwd === null) return;
            if (pwd === 'youcannotenter') {
                sessionStorage.setItem('admin_authed', 'true');
                const isOfflinePage = window.location.pathname.startsWith('/offline');
                const adminPath = isOfflinePage ? '/offline/page/admin' : '/page/admin';
                window.location.href = adminPath;
            } else {
                alert('Incorrect password.');
            }
        });
    }
});
