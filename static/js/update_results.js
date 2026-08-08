const PAGE_SIZE = 15;
let allPatients = [];
let filteredPatients = [];
let currentPage = 1;

async function loadPatients() {
    setLoading(true);
    try {
        // Fetching recent 200 patients for the queue list
        // Alternatively, use /api/patient/basic/all
        const res = await fetch('/api/patient/basic/200');
        if (!res.ok) throw new Error("Failed to fetch patients");
        const data = await res.json();
        allPatients = data.Response || [];
    } catch (e) {
        console.error("Error loading patients:", e);
        allPatients = [];
    }
    applyFilters();
    setLoading(false);
}

function applyFilters() {
    const searchInput = document.getElementById('search-input');
    const search = searchInput ? searchInput.value.trim().toLowerCase() : '';
    
    filteredPatients = allPatients.filter(p => {
        const name = (p.patient_name || '').toLowerCase();
        const mr = (p.mr_no || '').toLowerCase();
        return name.includes(search) || mr.includes(search);
    });
    
    currentPage = 1;
    renderTable();
    renderPagination();
}

function renderTable() {
    const tbody = document.getElementById('records-tbody');
    const start = (currentPage - 1) * PAGE_SIZE;
    const page = filteredPatients.slice(start, start + PAGE_SIZE);

    const showingLabel = document.getElementById('showing-label');
    if (showingLabel) {
        showingLabel.textContent = `Showing ${filteredPatients.length} patient${filteredPatients.length !== 1 ? 's' : ''}`;
    }

    if (page.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="4" class="table-empty">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path>
                    <circle cx="9" cy="7" r="4"></circle>
                    <line x1="19" y1="8" x2="19" y2="14"></line>
                    <line x1="22" y1="11" x2="16" y2="11"></line>
                </svg>
                <p>No patients found in the queue</p>
            </td></tr>`;
        return;
    }

    tbody.innerHTML = page.map(p => {
        const shiftClass = getShiftClass(p.shift);
        return `
        <tr>
            <td class="col-mr"><span class="mr-badge">${escapeHtml(p.mr_no || '—')}</span></td>
            <td class="col-name">${escapeHtml(p.patient_name || 'Unknown')}</td>
            <td class="col-shift">
                ${p.shift ? `<span class="shift-badge ${shiftClass}">${escapeHtml(p.shift)}</span>` : '—'}
            </td>
            <td class="col-actions">
                <div class="action-btns">
                    <button class="action-btn btn-enter-results" onclick="openEnterResults(${p.id})">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 20h9"></path>
                            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                        </svg>
                        Update Results
                    </button>
                    <button class="action-btn btn-edit-info" onclick="openEditInfo(${p.id})">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="3"></circle>
                            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                        </svg>
                        Update Info
                    </button>
                </div>
            </td>
        </tr>`;
    }).join('');
}

function renderPagination() {
    const total = Math.ceil(filteredPatients.length / PAGE_SIZE);
    const pg = document.getElementById('pagination');
    if (!pg) return;
    
    if (total <= 1) { 
        pg.innerHTML = ''; 
        return; 
    }

    let html = '';
    
    // Prev Button
    html += `<button class="pg-btn" ${currentPage === 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">‹</button>`;
    
    for (let i = 1; i <= total; i++) {
        if (total > 7 && i > 2 && i < total - 1 && Math.abs(i - currentPage) > 1) {
            if (i === 3 || i === total - 2) {
                html += `<span class="pg-btn" style="cursor:default">…</span>`;
            }
            continue;
        }
        html += `<button class="pg-btn ${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
    }
    
    // Next Button
    html += `<button class="pg-btn" ${currentPage === total ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">›</button>`;
    
    pg.innerHTML = html;
}

function goPage(p) {
    currentPage = p;
    renderTable();
    renderPagination();
}

function setLoading(isLoading) {
    const tbody = document.getElementById('records-tbody');
    if (isLoading && tbody) {
        tbody.innerHTML = `<tr><td colspan="4" class="table-loading">Loading patients queue…</td></tr>`;
    }
}

function getShiftClass(shift) {
    if (!shift) return '';
    const s = shift.toLowerCase();
    if (s.includes('morning')) return 'shift-morning';
    if (s.includes('evening')) return 'shift-evening';
    if (s.includes('night')) return 'shift-night';
    return '';
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

// Action Button Handlers
function openEnterResults(patientId) {
    // For now this is just an alert. We will implement the new full-screen entry page next.
    console.log("Enter results for patient", patientId);
    alert("This will navigate to the new Data Entry Page for Patient ID: " + patientId);
}

function openEditInfo(patientId) {
    console.log("Edit info for patient", patientId);
    alert("This will open the Update Info screen for Patient ID: " + patientId);
}

// Event Listeners setup
document.addEventListener('DOMContentLoaded', () => {
    loadPatients();
    
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        let searchTimer;
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(applyFilters, 300);
        });
    }

    const clearBtn = document.getElementById('btn-clear-filters');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (searchInput) searchInput.value = '';
            applyFilters();
        });
    }
});
