/**
 * Dynamic multi-criteria advanced search (AND logic).
 * Usage: AdvancedSearch.mount('#advanced-search-root', { onChange: loadRecords, categories: [] });
 */
(function (global) {
    const FIELD_LABELS = {
        patient_name: 'Patient Name',
        mr_no: 'MR Number',
        patient_token: 'Token No',
        relation_name: 'Relation Name',
        user: 'Registered By (User)',
        category: 'Test Category',
        test_name: 'Test Name',
        mobile: 'Mobile',
    };

    const DEFAULT_FIELDS = Object.keys(FIELD_LABELS);

    let usersCache = null;
    let usersLoading = null;

    function newRowId() {
        if (global.crypto && typeof global.crypto.randomUUID === 'function') {
            return global.crypto.randomUUID();
        }
        return `r${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    async function loadRegistrarUsers() {
        if (usersCache) return usersCache;
        if (usersLoading) return usersLoading;
        usersLoading = fetch('/api/metadata/registrar-users')
            .then(r => r.json())
            .then(data => {
                usersCache = (data && data.users) ? data.users : [];
                return usersCache;
            })
            .catch(() => {
                usersCache = [];
                return usersCache;
            })
            .finally(() => { usersLoading = null; });
        return usersLoading;
    }

    function getState(root) {
        if (!root._advSearchState) {
            root._advSearchState = {
                rows: [{ id: newRowId(), field: 'patient_name', value: '', user_id: '' }],
                maxRows: 5,
                categories: [],
                onChange: null,
            };
        }
        return root._advSearchState;
    }

    function valuePlaceholder(field) {
        const map = {
            patient_name: 'e.g. Ali Khan',
            mr_no: 'e.g. 100029',
            patient_token: 'e.g. 15',
            relation_name: 'e.g. Ahmed',
            user: 'Pick user below or type name',
            category: 'Select or type category',
            test_name: 'e.g. CBC',
            mobile: 'e.g. 0300…',
        };
        return map[field] || 'Enter value';
    }

    function buildUserValueHtml(row, users) {
        const options = ['<option value="">— Select registered user —</option>']
            .concat(users.map(u => {
                const label = escapeHtml(u.user || u.name || `User #${u.user_id}`);
                const uid = u.user_id != null ? String(u.user_id) : '';
                const selected = row.user_id && String(row.user_id) === uid ? ' selected' : '';
                return `<option value="${escapeHtml(uid)}" data-name="${label}"${selected}>${label}</option>`;
            }))
            .join('');

        return `
            <div class="user-value-wrap">
                <select class="adv-user-select" data-row-id="${row.id}">
                    ${options}
                </select>
                <span class="user-or-label">Or type name</span>
                <input type="text" class="adv-value-input" data-row-id="${row.id}"
                    value="${escapeHtml(row.value)}" placeholder="e.g. rehan">
            </div>
        `;
    }

    function buildCategoryValueHtml(row, categories) {
        const opts = ['<option value="">— Select category —</option>']
            .concat(categories.map(c => {
                const sel = row.value === c ? ' selected' : '';
                return `<option value="${escapeHtml(c)}"${sel}>${escapeHtml(c)}</option>`;
            }))
            .join('');
        return `
            <div class="user-value-wrap">
                <select class="adv-category-select" data-row-id="${row.id}">${opts}</select>
                <span class="user-or-label">Or type</span>
                <input type="text" class="adv-value-input" data-row-id="${row.id}"
                    value="${escapeHtml(row.value)}" placeholder="Category name">
            </div>
        `;
    }

    function render(root) {
        const state = getState(root);
        const fieldOptions = DEFAULT_FIELDS.map(f =>
            `<option value="${f}"${state.rows.some(r => r.field === f) ? '' : ''}>${FIELD_LABELS[f]}</option>`
        ).join('');

        const rowsHtml = state.rows.map(row => {
            const fieldOpts = DEFAULT_FIELDS.map(f =>
                `<option value="${f}"${row.field === f ? ' selected' : ''}>${FIELD_LABELS[f]}</option>`
            ).join('');

            let valueCell = `<input type="text" class="adv-value-input" data-row-id="${row.id}"
                value="${escapeHtml(row.value)}" placeholder="${escapeHtml(valuePlaceholder(row.field))}">`;

            if (row.field === 'user' && usersCache) {
                valueCell = buildUserValueHtml(row, usersCache);
            } else if (row.field === 'category' && state.categories.length) {
                valueCell = buildCategoryValueHtml(row, state.categories);
            }

            return `
                <div class="adv-search-row" data-row-id="${row.id}">
                    <select class="adv-field-select" data-row-id="${row.id}">${fieldOpts}</select>
                    ${valueCell}
                    <button type="button" class="adv-search-btn danger adv-remove-row" data-row-id="${row.id}"
                        title="Remove" ${state.rows.length <= 1 ? 'disabled' : ''}>×</button>
                </div>
            `;
        }).join('');

        root.innerHTML = `
            <div class="adv-search-panel">
                <div class="adv-search-head">
                    <h4>Advanced Search</h4>
                </div>
                <p class="adv-search-hint">Combine filters (all must match). Example: User <strong>rehan</strong> + Token <strong>15</strong>.</p>
                <div class="adv-search-rows">${rowsHtml}</div>
                <div class="adv-search-actions">
                    <button type="button" class="adv-search-btn" id="adv-add-row">+ Add filter</button>
                    <button type="button" class="adv-search-btn primary" id="adv-apply">Apply search</button>
                    <button type="button" class="adv-search-btn" id="adv-clear-rows">Clear filters</button>
                </div>
                <div class="adv-search-chips" id="adv-chips"></div>
            </div>
        `;

        bindEvents(root);
        renderChips(root);
    }

    function syncRowFromDom(root, rowId) {
        const state = getState(root);
        const row = state.rows.find(r => r.id === rowId);
        if (!row) return;

        const fieldSel = root.querySelector(`.adv-field-select[data-row-id="${rowId}"]`);
        if (fieldSel) row.field = fieldSel.value;

        const textInput = root.querySelector(`.adv-value-input[data-row-id="${rowId}"]`);
        const userSel = root.querySelector(`.adv-user-select[data-row-id="${rowId}"]`);
        const catSel = root.querySelector(`.adv-category-select[data-row-id="${rowId}"]`);

        if (row.field === 'user') {
            if (userSel && userSel.value) {
                row.user_id = userSel.value;
                const opt = userSel.options[userSel.selectedIndex];
                row.value = (opt && opt.dataset.name) ? opt.dataset.name.replace(/&amp;/g, '&') : '';
            } else if (textInput) {
                row.user_id = '';
                row.value = textInput.value.trim();
            }
        } else if (row.field === 'category' && catSel && catSel.value) {
            row.value = catSel.value;
            row.user_id = '';
        } else if (textInput) {
            row.value = textInput.value.trim();
            row.user_id = '';
        }
    }

    function syncAllRows(root) {
        getState(root).rows.forEach(r => syncRowFromDom(root, r.id));
    }

    function renderChips(root) {
        const state = getState(root);
        const chips = root.querySelector('#adv-chips');
        if (!chips) return;
        syncAllRows(root);
        const active = state.rows.filter(r => (r.value || '').trim() || r.user_id);
        if (!active.length) {
            chips.innerHTML = '';
            return;
        }
        chips.innerHTML = active.map(r => {
            const label = FIELD_LABELS[r.field] || r.field;
            const val = r.field === 'user' && r.user_id
                ? (r.value || `ID ${r.user_id}`)
                : r.value;
            return `<span class="adv-search-chip">${escapeHtml(label)}: ${escapeHtml(val)}
                <button type="button" data-remove-chip="${r.id}" aria-label="Remove">×</button></span>`;
        }).join('');
    }

    function getFilters(root) {
        if (!root) return [];
        syncAllRows(root);
        return getState(root).rows
            .filter(r => (r.value || '').trim() || r.user_id)
            .map(r => {
                const out = { field: r.field, value: (r.value || '').trim() || String(r.user_id) };
                if (r.field === 'user' && r.user_id) out.user_id = r.user_id;
                return out;
            });
    }

    function clear(root) {
        const state = getState(root);
        state.rows = [{ id: newRowId(), field: 'patient_name', value: '', user_id: '' }];
        render(root);
    }

    function triggerChange(root) {
        const state = getState(root);
        if (typeof state.onChange === 'function') state.onChange();
    }

    function bindEvents(root) {
        const state = getState(root);

        root.querySelector('#adv-add-row')?.addEventListener('click', () => {
            if (state.rows.length >= state.maxRows) return;
            state.rows.push({ id: newRowId(), field: 'patient_token', value: '', user_id: '' });
            render(root);
        });

        root.querySelector('#adv-clear-rows')?.addEventListener('click', () => {
            clear(root);
            triggerChange(root);
        });

        root.querySelector('#adv-apply')?.addEventListener('click', () => {
            syncAllRows(root);
            renderChips(root);
            triggerChange(root);
        });

        root.addEventListener('change', async (e) => {
            const rowId = e.target.dataset?.rowId;
            if (!rowId) return;

            if (e.target.classList.contains('adv-field-select')) {
                const row = state.rows.find(r => r.id === rowId);
                if (row) {
                    row.field = e.target.value;
                    row.value = '';
                    row.user_id = '';
                }
                if (row && row.field === 'user' && !usersCache) await loadRegistrarUsers();
                render(root);
                return;
            }

            syncRowFromDom(root, rowId);
            renderChips(root);
        });

        root.addEventListener('input', (e) => {
            if (!e.target.classList.contains('adv-value-input')) return;
            syncRowFromDom(root, e.target.dataset.rowId);
            renderChips(root);
        });

        root.addEventListener('click', (e) => {
            const removeId = e.target.closest('.adv-remove-row')?.dataset?.rowId
                || e.target.closest('[data-remove-chip]')?.getAttribute('data-remove-chip');
            if (!removeId) return;
            if (state.rows.length <= 1) {
                clear(root);
            } else {
                state.rows = state.rows.filter(r => r.id !== removeId);
                render(root);
            }
            triggerChange(root);
        });
    }

    async function mount(selectorOrEl, options = {}) {
        const root = typeof selectorOrEl === 'string'
            ? document.querySelector(selectorOrEl)
            : selectorOrEl;
        if (!root) return null;

        const state = getState(root);
        state.maxRows = options.maxRows || 5;
        state.categories = options.categories || [];
        state.onChange = options.onChange || null;
        if (options.fields) {
            // reserved for future field subsets
        }

        await loadRegistrarUsers();
        render(root);
        return root;
    }

    global.AdvancedSearch = {
        mount,
        getFilters,
        clear,
        loadRegistrarUsers,
        FIELD_LABELS,
    };
})(window);
