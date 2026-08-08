(function () {
    'use strict';

    const VIEW = document.querySelector('.analytics-page')?.dataset.view || 'overview';
    const CHARTS = {};
    const COLORS = {
        primary: '#2563eb',
        teal: '#0d9488',
        amber: '#d97706',
        rose: '#e11d48',
        slate: '#64748b',
        palette: ['#2563eb', '#0d9488', '#7c3aed', '#db2777', '#ea580c', '#0891b2', '#4f46e5', '#059669', '#ca8a04', '#dc2626'],
    };

    const state = {
        dateFrom: '',
        dateTo: '',
        preset: 'today',
        loading: false,
    };

    function todayIso() {
        return new Date().toISOString().slice(0, 10);
    }

    function startOfWeekIso() {
        const d = new Date();
        const day = d.getDay();
        const diff = day === 0 ? 6 : day - 1;
        d.setDate(d.getDate() - diff);
        return d.toISOString().slice(0, 10);
    }

    function startOfMonthIso() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
    }

    function userEmail() {
        return localStorage.getItem('userEmail') || '';
    }

    const ADMIN_PASSWORD = 'youcannotenter';

    function isAdminAuthed() {
        return sessionStorage.getItem('admin_authed') === 'true';
    }

    function ensureAdminAuthed() {
        if (isAdminAuthed()) return true;
        const pwd = prompt('Enter admin password:');
        if (pwd === null) return false;
        if (pwd === ADMIN_PASSWORD) {
            sessionStorage.setItem('admin_authed', 'true');
            return true;
        }
        alert('Incorrect password.');
        return false;
    }

    function apiHeaders() {
        const headers = { Accept: 'application/json', 'X-Admin-Password': ADMIN_PASSWORD };
        const email = userEmail();
        if (email) headers['X-User-Email'] = email;
        return headers;
    }

    function setLoading(on) {
        state.loading = on;
        const overlay = document.getElementById('analyticsLoading');
        if (overlay) overlay.classList.toggle('visible', on);
    }

    function applyPreset(preset) {
        state.preset = preset;
        const today = todayIso();
        if (preset === 'today') {
            state.dateFrom = today;
            state.dateTo = today;
        } else if (preset === 'week') {
            state.dateFrom = startOfWeekIso();
            state.dateTo = today;
        } else if (preset === 'month') {
            state.dateFrom = startOfMonthIso();
            state.dateTo = today;
        }
        document.getElementById('dateFrom').value = state.dateFrom;
        document.getElementById('dateTo').value = state.dateTo;
        document.querySelectorAll('.preset-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.preset === preset);
        });
    }

    function syncCustomPreset() {
        state.preset = 'custom';
        state.dateFrom = document.getElementById('dateFrom').value;
        state.dateTo = document.getElementById('dateTo').value;
        document.querySelectorAll('.preset-btn').forEach((btn) => btn.classList.remove('active'));
    }

    async function fetchAnalytics(endpoint, refresh) {
        const params = new URLSearchParams({
            date_from: state.dateFrom,
            date_to: state.dateTo,
        });
        if (refresh) params.set('refresh', 'true');
        const res = await fetch(`/api/v1/admin/analytics/${endpoint}?${params}`, {
            headers: apiHeaders(),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Request failed (${res.status})`);
        }
        const json = await res.json();
        return json.data;
    }

    function destroyChart(key) {
        if (CHARTS[key]) {
            CHARTS[key].destroy();
            delete CHARTS[key];
        }
    }

    function showEmpty(canvasId, message) {
        destroyChart(canvasId);
        const wrap = document.querySelector(`#${canvasId}`)?.closest('.chart-canvas-wrap');
        if (!wrap) return;
        wrap.innerHTML = `<div class="chart-empty">${message || 'No data for the selected date range.'}</div>`;
    }

    function ensureCanvas(wrapEl, canvasId) {
        if (!wrapEl.querySelector('canvas')) {
            wrapEl.innerHTML = `<canvas id="${canvasId}"></canvas>`;
        }
        return document.getElementById(canvasId);
    }

    function renderLineChart(canvasId, labels, values, label, color) {
        const wrap = document.querySelector(`#${canvasId}`)?.closest('.chart-canvas-wrap');
        if (!wrap) return;
        if (!labels.length) {
            showEmpty(canvasId);
            return;
        }
        const canvas = ensureCanvas(wrap, canvasId);
        destroyChart(canvasId);
        CHARTS[canvasId] = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label,
                    data: values,
                    borderColor: color || COLORS.primary,
                    backgroundColor: (color || COLORS.primary) + '22',
                    fill: true,
                    tension: 0.3,
                    pointRadius: labels.length > 31 ? 0 : 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                return `${label}: ${ctx.parsed.y}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { maxTicksLimit: 12, font: { size: 10 } } },
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                },
            },
        });
    }

    function renderBarChart(canvasId, labels, values, label, horizontal) {
        const wrap = document.querySelector(`#${canvasId}`)?.closest('.chart-canvas-wrap');
        if (!wrap) return;
        if (!labels.length) {
            showEmpty(canvasId);
            return;
        }
        const canvas = ensureCanvas(wrap, canvasId);
        destroyChart(canvasId);
        CHARTS[canvasId] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label,
                    data: values,
                    backgroundColor: labels.map((_, i) => COLORS.palette[i % COLORS.palette.length]),
                    borderRadius: 6,
                }],
            },
            options: {
                indexAxis: horizontal ? 'y' : 'x',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                return `${label}: ${ctx.parsed[horizontal ? 'x' : 'y']}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { beginAtZero: true, ticks: { precision: 0 } },
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                },
            },
        });
    }

    function renderDoughnutChart(canvasId, labels, values) {
        const wrap = document.querySelector(`#${canvasId}`)?.closest('.chart-canvas-wrap');
        if (!wrap) return;
        const total = values.reduce((a, b) => a + b, 0);
        if (!total) {
            showEmpty(canvasId);
            return;
        }
        const canvas = ensureCanvas(wrap, canvasId);
        destroyChart(canvasId);
        CHARTS[canvasId] = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: labels.map((_, i) => COLORS.palette[i % COLORS.palette.length]),
                    borderWidth: 2,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '58%',
                plugins: {
                    legend: { position: 'right', labels: { boxWidth: 12, font: { size: 10 } } },
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                const pct = ((ctx.parsed / total) * 100).toFixed(1);
                                return `${ctx.label}: ${ctx.parsed} (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    }

    function setKpis(containerId, entries) {
        const el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = entries.map(([label, value, hint]) => `
            <div class="kpi-card">
                <div class="label">${label}</div>
                <div class="value">${value}</div>
                ${hint ? `<div class="hint">${hint}</div>` : ''}
            </div>
        `).join('');
    }

    function setCacheBadge(fromCache) {
        const badge = document.getElementById('cacheBadge');
        if (!badge) return;
        badge.style.display = fromCache ? 'inline-block' : 'none';
    }

    function renderOperatorTable(rows) {
        const tbody = document.querySelector('#operatorTable tbody');
        if (!tbody) return;
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="3">No registrations in selected range.</td></tr>';
            return;
        }
        tbody.innerHTML = rows.map((r) => `
            <tr>
                <td>${escapeHtml(r.operator)}</td>
                <td>${r.registrations}</td>
                <td>${escapeHtml(r.primary_shift || '—')}</td>
            </tr>
        `).join('');
    }

    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function loadOverview(refresh) {
        const data = await fetchAnalytics('overview', refresh);
        const k = data.kpis || {};
        setKpis('kpiGrid', [
            ['Patients Registered', k.total_patients ?? 0, 'Distinct registrations'],
            ['Tests Recorded', k.total_tests ?? 0, 'Ordered / logged tests'],
            ['Completed', k.completed_tests ?? 0, `${k.completion_rate_pct ?? 0}% completion`],
            ['Pending', k.pending_tests ?? 0, 'Awaiting results'],
            ['Avg Tests / Patient', k.avg_tests_per_patient ?? 0, 'Operational density'],
            ['Active Operators', k.unique_operators ?? 0, 'Registration staff'],
        ]);
        setCacheBadge(data.from_cache);

        const regSeries = data.registration_series || [];
        renderLineChart(
            'chartRegistrations',
            regSeries.map((x) => x.date),
            regSeries.map((x) => x.count),
            'Registrations',
            COLORS.primary,
        );

        const cats = data.category_volume || [];
        renderBarChart(
            'chartCategories',
            cats.map((x) => x.category),
            cats.map((x) => x.count),
            'Tests',
            false,
        );

        const ratio = data.result_ratio || {};
        renderDoughnutChart(
            'chartResultRatio',
            ['Normal', 'Abnormal', 'Unclassified'],
            [ratio.normal || 0, ratio.abnormal || 0, ratio.unclassified || 0],
        );
    }

    async function loadTelemetry(refresh) {
        const data = await fetchAnalytics('telemetry', refresh);
        const k = data.kpis || {};
        setKpis('kpiGrid', [
            ['Total Registrations', k.total_registrations ?? 0, 'In selected period'],
            ['Avg Daily Volume', k.avg_daily_registrations ?? 0, 'Registrations / day'],
            ['Peak Hour', k.peak_hour ?? '—', `${k.peak_hour_count ?? 0} registrations`],
            ['Active Operators', k.active_operators ?? 0, 'Staff attribution'],
        ]);
        setCacheBadge(data.from_cache);

        const regSeries = data.registration_series || [];
        renderLineChart(
            'chartRegistrations',
            regSeries.map((x) => x.date),
            regSeries.map((x) => x.count),
            'Daily Registrations',
            COLORS.teal,
        );

        const hourly = data.hourly_series || [];
        renderLineChart(
            'chartHourly',
            hourly.map((x) => x.hour),
            hourly.map((x) => x.count),
            'Registrations by Hour',
            COLORS.amber,
        );

        const ops = data.operator_throughput || [];
        renderBarChart(
            'chartOperators',
            ops.slice(0, 12).map((x) => x.operator),
            ops.slice(0, 12).map((x) => x.registrations),
            'Registrations',
            true,
        );

        renderOperatorTable(ops);
    }

    async function loadTests(refresh) {
        const data = await fetchAnalytics('tests', refresh);
        const k = data.kpis || {};
        setKpis('kpiGrid', [
            ['Total Tests', k.total_tests ?? 0, 'All categories'],
            ['Completed', k.completed_tests ?? 0, 'Result entry done'],
            ['Pending', k.pending_tests ?? 0, 'Still open'],
            ['Normal Parameters', k.normal_parameters ?? 0, 'Within reference range'],
            ['Abnormal Parameters', k.abnormal_parameters ?? 0, `${k.abnormal_rate_pct ?? 0}% of classifiable`],
        ]);
        setCacheBadge(data.from_cache);

        const cats = data.category_volume || [];
        renderBarChart(
            'chartCategories',
            cats.map((x) => x.category),
            cats.map((x) => x.count),
            'Volume',
            false,
        );

        const top = data.top_tests || [];
        renderDoughnutChart(
            'chartTopTests',
            top.map((x) => x.test_name),
            top.map((x) => x.count),
        );

        const ratio = data.result_ratio || {};
        renderDoughnutChart(
            'chartResultRatio',
            ['Normal', 'Abnormal', 'Unclassified'],
            [ratio.normal || 0, ratio.abnormal || 0, ratio.unclassified || 0],
        );
    }

    async function refreshData(forceRefresh) {
        syncCustomPreset();
        if (!state.dateFrom || !state.dateTo) {
            alert('Please select a valid date range.');
            return;
        }
        if (state.dateFrom > state.dateTo) {
            alert('Start date must be on or before end date.');
            return;
        }
        setLoading(true);
        try {
            if (VIEW === 'telemetry') await loadTelemetry(forceRefresh);
            else if (VIEW === 'tests') await loadTests(forceRefresh);
            else await loadOverview(forceRefresh);
        } catch (err) {
            console.error(err);
            alert(err.message || 'Failed to load analytics.');
        } finally {
            setLoading(false);
        }
    }

    async function exportPdf() {
        syncCustomPreset();
        const params = new URLSearchParams({
            date_from: state.dateFrom,
            date_to: state.dateTo,
        });
        const name = localStorage.getItem('userName');
        if (name) params.set('pathologist_name', name);
        setLoading(true);
        try {
            const res = await fetch(`/api/v1/admin/analytics/export/pdf?${params}`, {
                headers: apiHeaders(),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Export failed (${res.status})`);
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `LabFlow_Analytics_${state.dateFrom}_to_${state.dateTo}.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            alert(err.message || 'PDF export failed.');
        } finally {
            setLoading(false);
        }
    }

    function wireNav() {
        document.querySelectorAll('.analytics-nav-item').forEach((link) => {
            link.addEventListener('click', (e) => {
                if (link.dataset.view === VIEW) {
                    e.preventDefault();
                    refreshData(false);
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (localStorage.getItem('isLoggedIn') !== 'true') {
            window.location.href = '/login';
            return;
        }

        const analyticsView = document.getElementById('analyticsView');
        const accessDenied = document.getElementById('analyticsAccessDenied');

        if (!ensureAdminAuthed()) {
            if (analyticsView) analyticsView.style.display = 'none';
            if (accessDenied) accessDenied.style.display = 'flex';
            return;
        }

        if (analyticsView) analyticsView.style.display = 'block';
        if (accessDenied) accessDenied.style.display = 'none';

        applyPreset('today');
        wireNav();

        document.querySelectorAll('.preset-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                applyPreset(btn.dataset.preset);
                refreshData(false);
            });
        });

        document.getElementById('dateFrom').addEventListener('change', () => {
            syncCustomPreset();
            refreshData(false);
        });
        document.getElementById('dateTo').addEventListener('change', () => {
            syncCustomPreset();
            refreshData(false);
        });
        document.getElementById('btnRefresh').addEventListener('click', () => refreshData(true));
        document.getElementById('btnExportPdf').addEventListener('click', exportPdf);

        refreshData(false);
    });
})();
