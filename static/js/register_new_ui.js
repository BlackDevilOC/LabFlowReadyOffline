document.addEventListener("DOMContentLoaded", async () => {
    const MAX_TESTS = 8;

    // ── User hydration ──────────────────────────────────────────────────
    const userEmailInput = document.getElementById("userEmailInput");
    const userNameInput  = document.getElementById("userNameInput");
    const userIdInput    = document.getElementById("userIdInput");

    const storedEmail  = localStorage.getItem("userEmail") || "";
    const storedName   = (localStorage.getItem("userName") || "").trim();
    const storedUserId = localStorage.getItem("userId") || "";
    const displayUser  = storedName || (storedEmail.includes("@") ? storedEmail.split("@")[0] : storedEmail) || "Anonymous";

    if (userEmailInput) userEmailInput.value = storedEmail || "Anonymous";
    if (userNameInput)  userNameInput.value  = displayUser;
    if (userIdInput)    userIdInput.value    = storedUserId;

    // ── Shift & Registration Options dropdowns ──────────────────────────
    await setupShiftDropdown();
    await setupRegistrationOptions();

    async function setupRegistrationOptions() {
        let options = null;
        try {
            const res = await fetch("/fetcheddata/registration_options.json", { cache: "no-store" });
            if (res.ok) {
                options = await res.json();
            }
        } catch (err) {
            console.warn("registration_options.json not loaded:", err);
        }

        const salutations = (options && Array.isArray(options.salutations) && options.salutations.length) ? options.salutations : [
            { value: "Mr.", label: "Mr.", default_gender: "MALE" },
            { value: "Mrs.", label: "Mrs.", default_gender: "FEMALE" },
            { value: "Miss.", label: "Miss.", default_gender: "FEMALE" },
            { value: "Baby", label: "Baby", default_gender: "" }
        ];

        const relations = (options && Array.isArray(options.relations) && options.relations.length) ? options.relations : [
            { value: "S", label: "S/O" },
            { value: "D", label: "D/O" },
            { value: "W", label: "W/O" }
        ];

        const genders = (options && Array.isArray(options.genders) && options.genders.length) ? options.genders : [
            { value: "MALE", label: "MALE" },
            { value: "FEMALE", label: "FEMALE" },
            { value: "OTHER", label: "OTHER" }
        ];

        const defaultVals = (options && options.default_values) || {};

        const salutationSelect = document.getElementById("salutation");
        const relationSelect = document.getElementById("relation");
        const genderSelect = document.getElementById("gender");

        if (relationSelect) {
            const currentRelVal = relationSelect.value;
            relationSelect.innerHTML = `<option value="">Select</option>` + relations.map(r => {
                const val = typeof r === "string" ? r : (r.value || r.label);
                const lbl = typeof r === "string" ? r : (r.label || r.value);
                return `<option value="${val}">${lbl}</option>`;
            }).join("");

            if (defaultVals.relation) {
                relationSelect.value = defaultVals.relation;
            } else if (currentRelVal) {
                relationSelect.value = currentRelVal;
            }
        }

        if (genderSelect) {
            const currentGenVal = genderSelect.value;
            genderSelect.innerHTML = `<option value="">SELECT</option>` + genders.map(g => {
                const val = typeof g === "string" ? g : (g.value || g.label);
                const lbl = typeof g === "string" ? g : (g.label || g.value);
                return `<option value="${val.toUpperCase()}">${lbl.toUpperCase()}</option>`;
            }).join("");

            if (defaultVals.gender) {
                genderSelect.value = defaultVals.gender.toUpperCase();
            } else if (currentGenVal) {
                genderSelect.value = currentGenVal;
            }
        }

        if (salutationSelect) {
            const currentSalVal = salutationSelect.value;
            salutationSelect.innerHTML = `<option value="">Select</option>` + salutations.map(s => {
                const val = typeof s === "string" ? s : (s.value || s.label);
                const lbl = typeof s === "string" ? s : (s.label || s.value);
                const genderAttr = (typeof s === "object" && s.default_gender) ? ` data-gender="${s.default_gender}"` : "";
                const relationAttr = (typeof s === "object" && s.default_relation) ? ` data-relation="${s.default_relation}"` : "";
                return `<option value="${val}"${genderAttr}${relationAttr}>${lbl}</option>`;
            }).join("");

            if (defaultVals.salutation) {
                salutationSelect.value = defaultVals.salutation;
            } else if (currentSalVal) {
                salutationSelect.value = currentSalVal;
            }

            const updateSalutationBindingsLive = () => {
                const selectedOpt = salutationSelect.options[salutationSelect.selectedIndex];
                if (!selectedOpt) return;
                const defGender = selectedOpt.getAttribute("data-gender") || "";
                const defRel = selectedOpt.getAttribute("data-relation") || "";

                if (defGender && genderSelect) {
                    genderSelect.value = defGender.toUpperCase();
                    genderSelect.dispatchEvent(new Event("change", { bubbles: true }));
                }

                if (defRel && relationSelect) {
                    relationSelect.value = defRel;
                    relationSelect.dispatchEvent(new Event("change", { bubbles: true }));
                }
            };

            salutationSelect.addEventListener("change", updateSalutationBindingsLive);
            salutationSelect.addEventListener("input", updateSalutationBindingsLive);

            // Live sync immediately on page load
            if (salutationSelect.value) {
                updateSalutationBindingsLive();
            }
        }
    }

    async function setupShiftDropdown() {
        const select = document.getElementById("shift");
        if (!select) return;

        let shifts = [];
        let defaultShift = localStorage.getItem("defaultShift") || localStorage.getItem("userShift") || "";

        try {
            const [shiftsRes, prefsRes] = await Promise.all([
                fetch("/fetcheddata/shifts.json", { cache: "no-store" }),
                fetch("/fetcheddata/user_preferences.json", { cache: "no-store" }),
            ]);
            if (shiftsRes.ok) {
                const data = await shiftsRes.json();
                shifts = data.shifts || [];
            }
            if (prefsRes.ok) {
                const prefs = await prefsRes.json();
                if (prefs.default_shift) defaultShift = prefs.default_shift;
            }
        } catch (err) {
            console.warn("Shift cache not available:", err);
        }

        if (!shifts.length) {
            shifts = [
                { shift: "MORNING" },
                { shift: "EVENING" },
                { shift: "NIGHT" },
                { shift: "HOLIDAY" },
                { shift: "OPD" },
            ];
        }

        select.innerHTML = shifts
            .map((s) => {
                const label = (s.shift || s.name || "").trim();
                return `<option value="${label}">${label}</option>`;
            })
            .join("");

        select.value = defaultShift;
        if (!select.value) {
            const match = Array.from(select.options).find(
                (o) => o.value.toUpperCase() === String(defaultShift).toUpperCase()
            );
            if (match) select.value = match.value;
        }
    }

    // ── State ────────────────────────────────────────────────────────────
    let allTests = [];
    let selectedTests = []; // array of { name, value }
    let categoriesOrder = [];
    let customCategories = {};
    let categoryItemsOrder = {};
    let popularOrder = [];
    let quickPresets = [];
    let categoryStyles = {};
    let regularPreset = [];
    let autoSelectRegular = false;

    // ── Fetch tests & config ────────────────────────────────────────────
    async function fetchTests() {
        try {
            const response = await fetch("/tests");
            if (!response.ok) return [];
            const data = await response.json();

            categoriesOrder = data.categories_order || [];
            customCategories = data.custom_categories || {};
            categoryItemsOrder = data.category_items_order || {};
            popularOrder = data.popular_order || categoryItemsOrder["Popular"] || [];
            quickPresets = data.quick_presets || [];
            categoryStyles = data.category_styles || {};
            regularPreset = data.regular_preset || [];
            autoSelectRegular = Boolean(data.auto_select_regular);

            // Migration fallback
            if (!quickPresets.length && regularPreset.length) {
                quickPresets = [{
                    id: "preset_regular",
                    name: "Regular Package",
                    tests: regularPreset,
                    auto_select: autoSelectRegular
                }];
            }

            const isStatusActive = (st) => {
                if (st === undefined || st === null) return true;
                if (typeof st === "boolean") return st;
                if (typeof st === "number") return st === 1;
                const s = String(st).trim().toLowerCase();
                return s === "active" || s === "true" || s === "1";
            };

            const showIndividualTests = Boolean(
                data.allow_single_tests || data.test_selection_mode === "group_and_single"
            );

            const groupTests = (data.group_test || [])
                .filter((t) => isStatusActive(t.status) && !(t.group_name || '').startsWith('#'))
                .map((t) => {
                    const customCat = customCategories[t.group_name] || customCategories[`group_${t.id}`];
                    return {
                        id: t.id,
                        name: t.group_name,
                        status: t.status,
                        value: JSON.stringify(t.component_ids),
                        category: customCat || "Group Test",
                        isGroup: true,
                    };
                });

            const activeGroupNames = new Set(groupTests.map((g) => (g.name || '').trim().toLowerCase()));

            const individualTests = showIndividualTests
                ? (data.tests || [])
                      .filter((t) => !t.name.startsWith("#") && isStatusActive(t.status) && !activeGroupNames.has((t.name || '').trim().toLowerCase()))
                      .map((t) => {
                          const customCat = customCategories[t.name] || customCategories[String(t.id)];
                          return {
                              id: t.id,
                              name: t.name,
                              status: t.status,
                              value: String(t.id),
                              category: customCat || t.category || "General",
                              isGroup: false,
                          };
                      })
                : [];

            return [...groupTests, ...individualTests];
        } catch (error) {
            console.error("Error fetching tests:", error);
            return [];
        }
    }

    // ── DOM refs ─────────────────────────────────────────────────────────
    const grid             = document.getElementById("testCheckboxGrid");
    const searchInput      = document.getElementById("testSearchInput");
    const clearAllBtn      = document.getElementById("clearAllBtn");
    const stripPills       = document.getElementById("stripPills");
    const badge            = document.getElementById("selectedCountBadge");
    const selectionInfo    = document.getElementById("selectionInfo");
    const quickPresetBar   = document.getElementById("quickPresetBar");

    // ── Render Quick Presets Bar ─────────────────────────────────────────
    function renderQuickPresetsBar() {
        if (!quickPresetBar) return;
        if (!quickPresets.length) {
            quickPresetBar.style.display = "none";
            return;
        }
        quickPresetBar.style.display = "flex";

        const buttons = quickPresets.map((preset, idx) => `
            <button type="button" class="btn-preset-chip" data-idx="${idx}">
                ⚡ ${escapeHtml(preset.name)}
            </button>
        `).join("");

        quickPresetBar.innerHTML = `
            <span class="preset-label">⚡ Quick Presets:</span>
            <div class="preset-buttons-wrap">${buttons}</div>
        `;

        quickPresetBar.querySelectorAll(".btn-preset-chip").forEach((btn) => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.idx);
                applyQuickPreset(quickPresets[idx]);
            });
        });
    }

    function applyQuickPreset(preset) {
        if (!preset || !preset.tests) return;
        const testVals = preset.tests;

        const targets = allTests.filter((t) =>
            t.status === true &&
            (testVals.includes(String(t.id)) || testVals.includes(t.name) || testVals.includes(t.value))
        );

        selectedTests = [];
        targets.slice(0, MAX_TESTS).forEach((t) => {
            selectedTests.push({ name: t.name, value: String(t.value) });
        });

        syncHiddenInputs();
        updatePills();
        updateBadge();
        refreshCardStates();
    }

    // ── Render checkbox grid ─────────────────────────────────────────────
    function renderGrid(tests) {
        if (!tests.length) {
            grid.innerHTML = `<p class="no-results-msg">No active tests found.</p>`;
            return;
        }

        // Group by category
        const categories = {};
        tests.forEach((t) => {
            const cat = t.category || "General";
            if (!categories[cat]) categories[cat] = [];
            categories[cat].push(t);
        });

        // Order categories: custom/categoriesOrder first, then Group Test, then General
        const allCatKeys = Object.keys(categories);
        const orderedCats = allCatKeys.sort((a, b) => {
            const idxA = categoriesOrder.indexOf(a);
            const idxB = categoriesOrder.indexOf(b);
            if (idxA !== -1 && idxB !== -1) return idxA - idxB;
            if (idxA !== -1) return -1;
            if (idxB !== -1) return 1;
            if (a === "Group Test" && b === "General") return -1;
            if (a === "General" && b === "Group Test") return 1;
            if (a === "Group Test") return -1;
            if (b === "Group Test") return 1;
            if (a === "General") return 1;
            if (b === "General") return -1;
            return a.localeCompare(b);
        });

        // Helper to sort tests within a category according to category_items_order / popular_order
        const sortCatItems = (catName, itemsList) => {
            const explicitOrder = categoryItemsOrder[catName] || (catName === "Popular" ? popularOrder : null);
            if (!explicitOrder || !Array.isArray(explicitOrder) || !explicitOrder.length) {
                return itemsList;
            }
            const orderMap = {};
            explicitOrder.forEach((nameOrId, idx) => {
                orderMap[String(nameOrId).trim().toLowerCase()] = idx;
            });
            return [...itemsList].sort((a, b) => {
                const nameA = (a.name || '').trim().toLowerCase();
                const nameB = (b.name || '').trim().toLowerCase();
                const idA = String(a.id || '').trim().toLowerCase();
                const idB = String(b.id || '').trim().toLowerCase();

                const posA = (nameA in orderMap) ? orderMap[nameA] : ((idA in orderMap) ? orderMap[idA] : 9999);
                const posB = (nameB in orderMap) ? orderMap[nameB] : ((idB in orderMap) ? orderMap[idB] : 9999);

                if (posA !== posB) return posA - posB;
                return (a.name || '').localeCompare(b.name || '');
            });
        };

        grid.innerHTML = orderedCats
            .map((cat) => {
                const sortedItems = sortCatItems(cat, categories[cat]);
                const items = sortedItems
                    .map((t) => buildCard(t))
                    .join("");
                
                const styleMode = categoryStyles[cat] || (cat === "General" ? "simple" : "fancy");
                const isSimple = styleMode === "simple";

                if (isSimple) {
                    return `
                        <div class="test-category-block style-simple">
                            <div class="category-label simple-header">${escapeHtml(cat)}</div>
                            <div class="test-checkbox-items">${items}</div>
                        </div>`;
                } else {
                    return `
                        <div class="test-category-block style-fancy cat-${slugify(cat)}">
                            <div class="category-label fancy-header">
                                <span>${escapeHtml(cat)}</span>
                                <span class="fancy-cat-count">${categories[cat].length}</span>
                            </div>
                            <div class="test-checkbox-items">${items}</div>
                        </div>`;
                }
            })
            .join("");

        // Attach click handlers
        grid.querySelectorAll(".test-checkbox-card").forEach((card) => {
            card.addEventListener("click", () => toggleTest(card));
        });
    }

    function buildCard(test) {
        const isSelected = selectedTests.some((s) => s.value === String(test.value));
        const isDisabled = !isSelected && selectedTests.length >= MAX_TESTS;
        const selectedClass = isSelected ? "selected" : "";
        const disabledClass = isDisabled ? "disabled" : "";
        const groupBadge    = test.isGroup ? `<span class="cb-group-badge">Group</span>` : "";

        return `
            <div class="test-checkbox-card ${selectedClass} ${disabledClass}"
                 data-value="${test.value}"
                 data-name="${escapeAttr(test.name)}"
                 data-group="${test.isGroup ? '1' : '0'}"
                 title="${escapeAttr(test.name)}">
                <div class="cb-check"></div>
                <span class="cb-label">${escapeHtml(test.name)}</span>
                ${groupBadge}
            </div>`;
    }

    function toggleTest(card) {
        const val  = card.dataset.value;
        const name = card.dataset.name;
        const idx  = selectedTests.findIndex((s) => s.value === val);

        if (idx >= 0) {
            // Deselect
            selectedTests.splice(idx, 1);
        } else {
            // Select
            if (selectedTests.length >= MAX_TESTS) return;
            selectedTests.push({ name, value: val });
        }

        syncHiddenInputs();
        updatePills();
        updateBadge();
        refreshCardStates();
    }

    function refreshCardStates() {
        grid.querySelectorAll(".test-checkbox-card").forEach((card) => {
            const val = card.dataset.value;
            const isSelected = selectedTests.some((s) => s.value === val);
            const isDisabled  = !isSelected && selectedTests.length >= MAX_TESTS;

            card.classList.toggle("selected",  isSelected);
            card.classList.toggle("disabled",  isDisabled);
        });
    }

    // ── Hidden inputs sync ───────────────────────────────────────────────
    function syncHiddenInputs() {
        for (let i = 1; i <= MAX_TESTS; i++) {
            const el = document.getElementById(`h_test_${i}`);
            if (el) el.value = selectedTests[i - 1]?.value || "";
        }
    }

    // ── Pills strip ──────────────────────────────────────────────────────
    function updatePills() {
        if (!selectedTests.length) {
            stripPills.innerHTML = `<span class="strip-empty">No tests selected yet</span>`;
            return;
        }
        stripPills.innerHTML = selectedTests
            .map((t, i) => `
                <span class="test-pill" data-idx="${i}">
                    ${escapeHtml(t.name)}
                    <span class="pill-remove" data-idx="${i}" title="Remove">×</span>
                </span>`)
            .join("");

        stripPills.querySelectorAll(".pill-remove").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.dataset.idx);
                selectedTests.splice(idx, 1);
                syncHiddenInputs();
                updatePills();
                updateBadge();
                refreshCardStates();
            });
        });
    }

    // ── Badge & info ─────────────────────────────────────────────────────
    function updateBadge() {
        const n = selectedTests.length;
        badge.textContent = `${n} selected`;
        badge.classList.toggle("has-items", n > 0);
        if (selectionInfo) {
            if (n === 0) {
                selectionInfo.textContent = `Select up to ${MAX_TESTS} tests`;
            } else if (n >= MAX_TESTS) {
                selectionInfo.textContent = `Maximum ${MAX_TESTS} tests selected`;
            } else {
                selectionInfo.textContent = `${n} of ${MAX_TESTS} tests selected`;
            }
        }
    }

    // ── Search ───────────────────────────────────────────────────────────
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            const q = searchInput.value.toLowerCase().trim();
            const filtered = q
                ? allTests.filter((t) => t.status === true && t.name.toLowerCase().includes(q))
                : allTests.filter((t) => t.status === true);
            renderGrid(filtered);
            refreshCardStates();
        });
    }

    // ── Clear All ────────────────────────────────────────────────────────
    if (clearAllBtn) {
        clearAllBtn.addEventListener("click", () => {
            selectedTests = [];
            syncHiddenInputs();
            updatePills();
            updateBadge();
            refreshCardStates();
        });
    }

    // ── Form submit guard ────────────────────────────────────────────────
    const form = document.getElementById("newRegisterForm");
    if (form) {
        form.addEventListener("submit", (e) => {
            if (selectedTests.length === 0) {
                e.preventDefault();
                alert("Please select at least one test before saving.");
            }
        });
    }

    // ── Helpers ──────────────────────────────────────────────────────────
    function escapeHtml(str) {
        return String(str || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function escapeAttr(str) {
        return String(str || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function slugify(str) {
        return String(str || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    }

    // ── Bootstrap ────────────────────────────────────────────────────────
    grid.innerHTML = `<div class="loading-tests"><div class="spinner"></div><span>Loading available tests…</span></div>`;

    allTests = await fetchTests();
    const activeTests = allTests.filter((t) => t.status === true);

    renderQuickPresetsBar();

    if (activeTests.length > 0) {
        renderGrid(activeTests);
        
        // Auto select preset if configured
        const autoPreset = quickPresets.find(p => p.auto_select);
        if (autoPreset) {
            applyQuickPreset(autoPreset);
        } else if (autoSelectRegular || (regularPreset && regularPreset.length > 0)) {
            if (quickPresets.length > 0) applyQuickPreset(quickPresets[0]);
        }
    } else {
        grid.innerHTML = `<p class="no-results-msg">No active tests available. Please check the admin panel.</p>`;
    }

    updateBadge();
    updatePills();
});
