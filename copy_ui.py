import re

with open('templates/fitness_records.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('Fitness Records', 'Update Test Results')
content = content.replace('View and print all fitness examination reports', 'Select a patient to enter test results or edit basic info')
content = content.replace('New Fitness Report', 'New Patient')
content = content.replace('href="/page/fitness"', 'href="/register"')

content = content.replace("let url = '/api/fitness/records?';", "let url = '/api/patient/basic/200?';")
content = content.replace("allRecords = data.records || [];", "allRecords = data.Response || [];")

action_html_old = """<td class="col-actions" style="text-align:right;">
                    <button class="print-btn" onclick="printRecord(${JSON.stringify(r).replace(/"/g, '&quot;')})">
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="6 9 6 2 18 2 18 9"></polyline>
                            <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                            <rect x="6" y="14" width="12" height="8"></rect>
                        </svg>
                        Print
                    </button>
                </td>"""

action_html_new = """<td class="col-actions" style="text-align:right; display:flex; gap:8px; justify-content:flex-end;">
                    <button class="print-btn" style="background:#2563eb" onclick="window.location.href='/page/enter-results/' + r.id">
                        Update Results
                    </button>
                    <button class="print-btn" style="background:#64748b" onclick="window.location.href='/page/edit-info/' + r.id">
                        Update Info
                    </button>
                </td>"""

content = content.replace(action_html_old, action_html_new)
content = content.replace('<span class="type-badge type-fitness">Fitness</span>', '<span class="type-badge type-fitness" style="background:#eff6ff;color:#2563eb;">Lab Test</span>')
content = content.replace('<th class="col-type">Report Type</th>', '<th class="col-type">Type</th>')

with open('templates/update_results.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')
