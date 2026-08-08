/**
 * Common remarks picker (loaded from fetcheddata/remarks.json after login).
 */
(function (global) {
    const EMPTY = { global: [], by_test_name: {}, by_category: {}, items: [] };

    let pickerUi = null;
    let activeTextarea = null;

    function normalizeText(s) {
        return String(s || '').trim();
    }

    async function loadCache() {
        if (loadCache._data) return loadCache._data;
        try {
            const res = await fetch('/fetcheddata/remarks.json', { cache: 'no-store' });
            if (!res.ok) throw new Error('not found');
            loadCache._data = await res.json();
        } catch {
            loadCache._data = { ...EMPTY };
        }
        return loadCache._data;
    }

    function clearCache() {
        loadCache._data = null;
    }

    function suggestionsFor(record, limit) {
        const data = loadCache._data || EMPTY;
        const test = normalizeText(record?.test_name);
        const cat = normalizeText(record?.category);
        const merged = [];
        const seen = new Set();

        const addList = (list) => {
            (list || []).forEach((item) => {
                const text = typeof item === 'string' ? item : item?.text;
                const t = normalizeText(text);
                if (!t || seen.has(t.toLowerCase())) return;
                seen.add(t.toLowerCase());
                merged.push({
                    text: t,
                    usage_count: typeof item === 'object' ? (item.usage_count || 0) : 0,
                });
            });
        };

        if (test && data.by_test_name?.[test]) addList(data.by_test_name[test]);
        if (cat && data.by_category?.[cat]) addList(data.by_category[cat]);
        addList(data.global);

        merged.sort((a, b) => (b.usage_count || 0) - (a.usage_count || 0));
        if (typeof limit === 'number' && limit > 0) return merged.slice(0, limit);
        return merged;
    }

    function insertIntoTextarea(textarea, text) {
        if (!textarea) return;
        const t = normalizeText(text);
        if (!t) return;
        const cur = textarea.value.trim();
        textarea.value = cur ? `${cur}; ${t}` : t;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.focus();
    }

    function ensurePickerUi() {
        if (pickerUi) return pickerUi;

        const overlay = document.createElement('div');
        overlay.id = 'remarks-picker-overlay';
        overlay.className = 'remarks-picker-overlay';
        overlay.innerHTML = `
            <div class="remarks-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="remarks-picker-title">
                <div class="remarks-picker-header">
                    <h4 id="remarks-picker-title">Common remarks</h4>
                    <button type="button" class="remarks-picker-close" aria-label="Close">&times;</button>
                </div>
                <p class="remarks-picker-context" id="remarks-picker-context"></p>
                <input type="search" class="remarks-picker-search" placeholder="Search remarks…" autocomplete="off">
                <div class="remarks-picker-list" role="listbox"></div>
                <p class="remarks-picker-empty">No remarks match your search.</p>
            </div>
        `;
        document.body.appendChild(overlay);

        const dialog = overlay.querySelector('.remarks-picker-dialog');
        const closeBtn = overlay.querySelector('.remarks-picker-close');
        const search = overlay.querySelector('.remarks-picker-search');
        const listEl = overlay.querySelector('.remarks-picker-list');
        const emptyEl = overlay.querySelector('.remarks-picker-empty');
        const contextEl = overlay.querySelector('#remarks-picker-context');

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closePicker();
        });
        closeBtn.addEventListener('click', closePicker);
        dialog.addEventListener('click', (e) => e.stopPropagation());

        search.addEventListener('input', () => {
            renderPickerList(listEl, emptyEl, pickerUi._currentList || [], search.value);
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay.classList.contains('open')) closePicker();
        });

        pickerUi = { overlay, search, listEl, emptyEl, contextEl, _currentList: [] };
        return pickerUi;
    }

    function closePicker() {
        if (!pickerUi) return;
        pickerUi.overlay.classList.remove('open');
        pickerUi.search.value = '';
        activeTextarea = null;
        pickerUi._currentList = [];
    }

    function renderPickerList(listEl, emptyEl, list, query) {
        const q = normalizeText(query).toLowerCase();
        const filtered = q
            ? list.filter((item) => item.text.toLowerCase().includes(q))
            : list;

        listEl.innerHTML = '';
        if (!filtered.length) {
            emptyEl.style.display = 'block';
            listEl.style.display = 'none';
            return;
        }
        emptyEl.style.display = 'none';
        listEl.style.display = 'block';

        const popular = filtered.filter((i) => (i.usage_count || 0) > 0);
        const rest = filtered.filter((i) => !(i.usage_count || 0));

        const appendSection = (title, items) => {
            if (!items.length) return;
            const heading = document.createElement('div');
            heading.className = 'remarks-picker-section';
            heading.textContent = title;
            listEl.appendChild(heading);

            items.forEach((item) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'remarks-picker-item';
                btn.setAttribute('role', 'option');
                btn.title = item.text;

                const label = document.createElement('span');
                label.className = 'remarks-picker-item-text';
                label.textContent = item.text;
                btn.appendChild(label);

                if (item.usage_count > 0) {
                    const badge = document.createElement('span');
                    badge.className = 'remarks-picker-badge';
                    badge.textContent = item.usage_count >= 50 ? 'Popular' : `${item.usage_count}×`;
                    btn.appendChild(badge);
                }

                btn.addEventListener('click', () => {
                    insertIntoTextarea(activeTextarea, item.text);
                    closePicker();
                });
                listEl.appendChild(btn);
            });
        };

        if (!q && popular.length) {
            appendSection('Most used', popular);
            if (rest.length) appendSection('All remarks', rest);
        } else {
            appendSection(q ? 'Results' : 'All remarks', filtered);
        }
    }

    function openPicker(record, textarea) {
        const ui = ensurePickerUi();
        const list = suggestionsFor(record);
        activeTextarea = textarea;
        ui._currentList = list;

        const test = normalizeText(record?.test_name);
        ui.contextEl.textContent = test
            ? `For: ${test} · ${list.length} suggestion${list.length === 1 ? '' : 's'}`
            : `${list.length} lab-wide suggestion${list.length === 1 ? '' : 's'}`;

        renderPickerList(ui.listEl, ui.emptyEl, list, '');
        ui.search.value = '';
        ui.overlay.classList.add('open');
        requestAnimationFrame(() => ui.search.focus());
    }

    function attachToWrap(wrap, record) {
        if (!wrap) return;
        const textarea = wrap.querySelector('.remarks-field');
        const btn = wrap.querySelector('.remarks-pick-btn');
        if (!textarea || !btn) return;

        btn.disabled = false;
        btn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            await loadCache();
            const list = suggestionsFor(record);
            if (!list.length) {
                alert('No common remarks configured. Ask admin to add remarks or sync cache.');
                return;
            }
            openPicker(record, textarea);
        };
    }

    function initAllIn(container) {
        if (!container) return;
        container.querySelectorAll('.test-remarks-wrap').forEach((wrap) => {
            const id = wrap.querySelector('.remarks-field')?.dataset?.recordId;
            const rec = global.__patientRecordsForRemarks?.find(
                (r) => String(r.id) === String(id)
            );
            if (rec) attachToWrap(wrap, rec);
        });
    }

    global.LabFlowRemarks = {
        loadCache,
        clearCache,
        suggestionsFor,
        insertIntoTextarea,
        attachToWrap,
        initAllIn,
        closePicker,
    };
})(window);
