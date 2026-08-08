document.addEventListener("DOMContentLoaded", async () => {
    await setupShiftDropdown();

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
        let defaultShift = localStorage.getItem("defaultShift") || "MORNING";

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

            // Combine individual tests and group tests into a unified structure
            // Dynamic check based on system settings (group_only vs group_and_single)
            const showIndividualTests = Boolean(data.allow_single_tests || data.test_selection_mode === 'group_and_single');

            // Filter out '#'-prefixed rows — those are subheading markers for print layout only
            const individualTests = showIndividualTests
                ? (data.tests || [])
                    .filter(t => !t.name.startsWith('#'))
                    .map(t => ({
                        id: t.id,
                        name: t.name,
                        status: t.status,
                        value: t.id // Individual tests use their ID as value
                    }))
                : [];

            const groupTests = (data.group_test || []).map(t => ({
                id: t.id, // Not really used for value, but kept for reference
                name: t.group_name, // Use group_name as display name
                status: t.status,
                value: JSON.stringify(t.component_ids) // Use component_ids array as value
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
