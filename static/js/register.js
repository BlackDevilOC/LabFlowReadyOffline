document.addEventListener("DOMContentLoaded", async () => {
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

            if (salutationSelect.value) {
                updateSalutationBindingsLive();
            }
        }
    }

    // Select all test dropdowns
    const testSelects = document.querySelectorAll(".test-select");
    const userEmailInput = document.getElementById("userEmailInput");
    const userNameInput = document.getElementById("userNameInput");
    const userIdInput = document.getElementById("userIdInput");

    // Populate logged-in user for audit + patients.user / patients.user_id
    const storedEmail = localStorage.getItem('userEmail') || '';
    const storedName = (localStorage.getItem('userName') || '').trim();
    const storedUserId = localStorage.getItem('userId') || '';
    const displayUser = storedName || (storedEmail.includes('@') ? storedEmail.split('@')[0] : storedEmail) || 'Anonymous';

    if (userEmailInput) {
        userEmailInput.value = storedEmail || 'Anonymous';
    }
    if (userNameInput) {
        userNameInput.value = displayUser;
    }
    if (userIdInput) {
        userIdInput.value = storedUserId;
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

    // Function to fetch tests from API
    async function fetchTests() {
        try {
            const response = await fetch("/tests");
            if (!response.ok) {
                console.error("Failed to fetch tests:", response.statusText);
                return [];
            }
            const data = await response.json();

            const isStatusActive = (st) => {
                if (st === undefined || st === null) return true;
                if (typeof st === "boolean") return st;
                if (typeof st === "number") return st === 1;
                const s = String(st).trim().toLowerCase();
                return s === "active" || s === "true" || s === "1";
            };

            // Combine individual tests and group tests into a unified structure
            // Dynamic check based on system settings (group_only vs group_and_single)
            const showIndividualTests = Boolean(data.allow_single_tests || data.test_selection_mode === 'group_and_single');

            // Filter out '#'-prefixed rows and inactive tests
            const individualTests = showIndividualTests
                ? (data.tests || [])
                    .filter(t => !t.name.startsWith('#') && isStatusActive(t.status))
                    .map(t => ({
                        id: t.id,
                        name: t.name,
                        status: t.status,
                        value: t.id // Individual tests use their ID as value
                    }))
                : [];

            const groupTests = (data.group_test || [])
                .filter(t => isStatusActive(t.status))
                .map(t => ({
                    id: t.id,
                    name: t.group_name,
                    status: t.status,
                    value: JSON.stringify(t.component_ids)
                }));

            return [...individualTests, ...groupTests];
        } catch (error) {
            console.error("Error fetching tests:", error);
            return [];
        }
    }

    // Function to populate a dropdown
    function populateDropdown(selectElement, tests) {
        // Clear existing options except the first one (placeholder)
        // Keep the first option: <option value="">--SELECT TEST--</option>
        while (selectElement.options.length > 1) {
            selectElement.remove(1);
        }

        tests.forEach(test => {
            if (test.status === true) { // Only show active tests
                const option = document.createElement("option");
                option.value = test.value;
                option.textContent = test.name;
                selectElement.appendChild(option);
            }
        });
    }

    // Main execution
    const tests = await fetchTests();

    if (tests.length > 0) {
        testSelects.forEach(select => {
            populateDropdown(select, tests);
        });
    } else {
        console.warn("No active tests found or API error.");
    }
});
