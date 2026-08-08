/**
 * Shared page-size control and lab row grouping (one row per patient).
 */
(function (global) {
    const PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 75, 100];
    const STORAGE_KEY = 'labflowListPageSize';

    function getPageSize() {
        const v = parseInt(global.localStorage.getItem(STORAGE_KEY) || '15', 10);
        return PAGE_SIZE_OPTIONS.includes(v) ? v : 15;
    }

    function setPageSize(n) {
        const v = parseInt(n, 10);
        if (PAGE_SIZE_OPTIONS.includes(v)) {
            global.localStorage.setItem(STORAGE_KEY, String(v));
        }
    }

    function bindPageSizeSelect(selectEl, onChange) {
        if (!selectEl) return getPageSize();
        selectEl.innerHTML = PAGE_SIZE_OPTIONS.map(n => {
            const sel = n === getPageSize() ? ' selected' : '';
            return `<option value="${n}"${sel}>${n}</option>`;
        }).join('');
        selectEl.addEventListener('change', () => {
            setPageSize(selectEl.value);
            if (typeof onChange === 'function') onChange(getPageSize());
        });
        return getPageSize();
    }

    function getShortTestName(fullName) {
        if (!fullName) return '';
        const match = String(fullName).match(/\(([^)]+)\)/);
        if (match) {
            const short = match[1].trim();
            if (short.length <= 8) return short;
        }
        const lower = String(fullName).toLowerCase();
        if (lower.includes('complete blood count') || lower === 'cbc') return 'CBC';
        if (lower.includes('liver function') || lower === 'lft') return 'LFT';
        if (lower.includes('renal function') || lower === 'rft') return 'RFT';
        if (lower.includes('urine')) return 'U.RE';
        if (lower.includes('hiv')) return 'HIV';
        if (lower.includes('hbsag')) return 'HBsAg';
        if (lower.includes('hcv')) return 'HCV';
        if (lower.includes('widal')) return 'WIDAL';
        if (lower.includes('lipid')) return 'LIPID';
        if (lower.includes('thyroid')) return 'TFT';
        if (String(fullName).length > 12) {
            const words = String(fullName).split(/\s+/);
            if (words.length > 1) return words.map(w => w[0].toUpperCase()).join('');
            return String(fullName).substring(0, 10) + '...';
        }
        return fullName;
    }

    /** Group test_results_all rows → one object per mr_no, newest patients first. */
    function groupLabRowsByPatient(rows) {
        const grouped = {};
        (rows || []).forEach(r => {
            const mr = r.mr_no;
            if (mr == null || mr === '') return;
            if (!grouped[mr]) {
                grouped[mr] = {
                    id: r.id,
                    mr_no: mr,
                    patient_name: r.patient_name,
                    relation_type: r.relation_type || '',
                    relation_name: r.relation_name || '',
                    age: r.age,
                    gender: r.gender,
                    shift: r.shift || '',
                    mobile: r.mobile,
                    patient_token: r.patient_token,
                    created_at: r.created_at,
                    tests: [],
                    status: 'Completed',
                };
            }
            const g = grouped[mr];
            const tNew = new Date(r.created_at || 0).getTime();
            const tOld = new Date(g.created_at || 0).getTime();
            if (tNew > tOld) {
                g.created_at = r.created_at;
                g.id = r.id;
            }
            g.tests.push({
                id: r.id,
                test_name: r.test_name,
                category: r.category,
                status: r.status,
                remarks: r.remarks,
            });
            if (r.status === 'Pending') g.status = 'Pending';
        });
        return Object.values(grouped).sort(
            (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)
        );
    }

    function renderTestBadges(tests) {
        return (tests || []).map(t => {
            const done = t.status === 'Completed';
            const style = done
                ? 'background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;'
                : 'background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;';
            const shortName = getShortTestName(t.test_name);
            return `<span style="margin:2px;padding:2px 8px;border-radius:4px;display:inline-block;font-size:11px;font-weight:bold;${style}">${shortName}</span>`;
        }).join(' ');
    }

    global.ListPagination = {
        PAGE_SIZE_OPTIONS,
        getPageSize,
        setPageSize,
        bindPageSizeSelect,
        groupLabRowsByPatient,
        getShortTestName,
        renderTestBadges,
    };
})(window);
