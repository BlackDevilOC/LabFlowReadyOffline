(function () {
  const cfg = window.LABFLOW_PORTAL_CONFIG || {};
  const supabaseUrl = (cfg.supabaseUrl || "").replace(/\/$/, "");
  const functionName = cfg.functionName || "patient-portal";
  const hospitalName = cfg.hospitalName || "Lab Results Portal";

  const loginView = document.getElementById("login-view");
  const reportView = document.getElementById("report-view");
  const loginForm = document.getElementById("login-form");
  const loginError = document.getElementById("login-error");
  const loginBtn = document.getElementById("login-btn");
  const reportContent = document.getElementById("reportContent");
  const hospitalEl = document.getElementById("hospital-name");

  if (hospitalEl) hospitalEl.textContent = hospitalName;

  function portalApiUrl() {
    return `${supabaseUrl}/functions/v1/${functionName}`;
  }

  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
  }

  function fmtRange(minV, maxV) {
    const min =
      minV === null || minV === undefined || minV === "" ? null : String(minV);
    const max =
      maxV === null || maxV === undefined || maxV === "" ? null : String(maxV);
    if (min && max) return `${escapeHtml(min)} - ${escapeHtml(max)}`;
    if (min && !max) return `&ge; ${escapeHtml(min)}`;
    if (!min && max) return `&le; ${escapeHtml(max)}`;
    return "";
  }

  function toParamList(testValues) {
    const values =
      testValues && typeof testValues === "object"
        ? Object.values(testValues)
        : [];
    return values.filter((v) => v && typeof v === "object");
  }

  function groupByCategoryAndTest(rows) {
    const out = {};
    for (const r of rows) {
      const cat = (r.category || "General").trim() || "General";
      if (!out[cat]) out[cat] = {};
      const tname = (r.test_name || "Test").trim() || "Test";
      if (!out[cat][tname]) out[cat][tname] = { params: [], remarks: "" };
      out[cat][tname].params.push(...toParamList(r.test_values));
      const rm = (r.remarks || "").trim();
      if (rm) {
        const existing = out[cat][tname].remarks;
        out[cat][tname].remarks = existing ? `${existing}; ${rm}` : rm;
      }
    }
    return out;
  }

  function renderParamRow(p) {
    const name = p.name || p.label || "";
    const value =
      p.value !== null && p.value !== undefined ? String(p.value) : "";
    return `
      <tr class="test-row">
        <td class="test-name-cell">${escapeHtml(name)}</td>
        <td class="result-cell">${escapeHtml(value)}</td>
        <td class="unit-cell">${escapeHtml(p.unit || "")}</td>
        <td class="range-cell">${fmtRange(p.normal_min, p.normal_max)}</td>
      </tr>`;
  }

  function renderReport(patient, tests) {
    const now = new Date();
    const grouped = groupByCategoryAndTest(tests);
    const categories = Object.keys(grouped).sort();

    if (categories.length === 0) {
      reportContent.innerHTML =
        '<p class="empty-msg">No completed results are available yet. Please check back later or contact the lab.</p>';
      return;
    }

    const sal = patient.salutation ? `${patient.salutation} ` : "";
    let html = "";

    categories.forEach((category, index) => {
      const testMap = grouped[category];
      const testNames = Object.keys(testMap).sort();
      const isLast = index === categories.length - 1;

      html += `
        <div class="category-wrapper ${isLast ? "last-category" : ""}">
          <table class="category-table">
            <thead class="repeating-header">
              <tr>
                <td colspan="4" class="header-cell">
                  <div class="patient-info-boxes">
                    <div class="patient-info-box">
                      <div class="info-row"><span class="info-label">Lab No:</span> <span class="info-value">${escapeHtml(patient.mr_no)}</span></div>
                      <div class="info-row"><span class="info-label">Name:</span> <span class="info-value">${escapeHtml(sal)}${escapeHtml(patient.patient_name || "")}</span></div>
                      <div class="info-row"><span class="info-label">Age / Sex:</span> <span class="info-value">${escapeHtml(String(patient.age ?? ""))} / ${escapeHtml(patient.gender || "")}</span></div>
                      <div class="info-row"><span class="info-label">Shift:</span> <span class="info-value">${escapeHtml(patient.shift || "—")}</span></div>
                    </div>
                    <div class="patient-info-box">
                      <div class="info-row"><span class="info-label">Token:</span> <span class="info-value">${escapeHtml(patient.patient_token || "—")}</span></div>
                      <div class="info-row"><span class="info-label">Reported:</span> <span class="info-value">${escapeHtml(now.toLocaleString())}</span></div>
                    </div>
                  </div>
                  <span class="category-title">${escapeHtml(category)}</span>
                </td>
              </tr>
              <tr class="column-headers-row">
                <th class="col-test-name">TEST NAME</th>
                <th class="col-result">RESULT</th>
                <th class="col-unit">UNIT</th>
                <th class="col-range">NORMAL RANGE</th>
              </tr>
            </thead>
            <tbody>`;

      testNames.forEach((tname) => {
        const block = testMap[tname];
        html += `<tr class="group-title-row"><td colspan="4" class="group-name">${escapeHtml(tname)}</td></tr>`;
        block.params.forEach((p) => {
          html += renderParamRow(p);
        });
        if (block.remarks) {
          html += `<tr class="test-row"><td colspan="4"><em>Remarks: ${escapeHtml(block.remarks)}</em></td></tr>`;
        }
      });

      html += `</tbody></table></div>`;
    });

    html += `
      <footer class="report-footer">
        <div class="sig-section">
          <div class="footer-info">
            <p>Online report — ${escapeHtml(hospitalName)}</p>
            <p>Printed: ${escapeHtml(now.toLocaleString())}</p>
            <p>LabFlow Patient Portal</p>
          </div>
          <div class="sig-block">
            <div class="sig-line"></div>
            <span class="sig-text">Authorized signature</span>
          </div>
        </div>
      </footer>`;

    reportContent.innerHTML = html;
  }

  function showLogin(msg) {
    loginView.hidden = false;
    reportView.hidden = true;
    if (msg) {
      loginError.textContent = msg;
      loginError.hidden = false;
    } else {
      loginError.hidden = true;
      loginError.textContent = "";
    }
  }

  function showReport() {
    loginView.hidden = true;
    reportView.hidden = false;
  }

  async function fetchResults(mrNo, token, pin) {
    const body = { pin };
    if (mrNo) body.mr_no = mrNo;
    if (token) body.patient_token = token;

    const res = await fetch(portalApiUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error("Invalid response from server.");
    }

    if (!res.ok || data.status !== "ok") {
      throw new Error(data.message || "Could not load results.");
    }
    return data;
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.hidden = true;
    loginBtn.disabled = true;
    loginBtn.textContent = "Loading…";

    const mrRaw = document.getElementById("mr_no").value.trim();
    const token = document.getElementById("patient_token").value.trim();
    const pin = document.getElementById("pin").value.trim();

    try {
      if (!supabaseUrl) {
        throw new Error("Portal is not configured (missing supabaseUrl).");
      }
      const mrNo = mrRaw ? parseInt(mrRaw, 10) : null;
      if (!token && (mrNo === null || Number.isNaN(mrNo))) {
        throw new Error("Enter a valid lab number or patient token.");
      }

      const data = await fetchResults(
        mrNo !== null && !Number.isNaN(mrNo) ? mrNo : null,
        token || null,
        pin,
      );
      showReport();
      renderReport(data.patient, data.tests || []);
    } catch (err) {
      showLogin(err.message || "Login failed.");
    } finally {
      loginBtn.disabled = false;
      loginBtn.textContent = "View results";
    }
  });

  document.getElementById("btn-print").addEventListener("click", () => {
    window.print();
  });

  document.getElementById("btn-logout").addEventListener("click", () => {
    loginForm.reset();
    showLogin();
  });

  if (!supabaseUrl) {
    showLogin("Missing config.js — copy config.example.js and set supabaseUrl.");
  }
})();
