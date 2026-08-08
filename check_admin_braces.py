from pathlib import Path
path = Path('d:/rehan/LABFLOW2.0/LabFlowReady/templates/admin_panel.html')
text = path.read_text(encoding='utf-8')
start = text.find('<script>')
end = text.rfind('</script>')
print('start', start, 'end', end)
script = text[start + len('<script>'):end]
balance = 0
for i, line in enumerate(script.splitlines(), 1):
    balance += line.count('{') - line.count('}')
    if balance < 0:
        print('negative at line', i, 'balance', balance, 'line:', line)
        break
print('final balance', balance)
print('\n--- tail 40 lines ---')
lines = script.splitlines()
for idx, line in enumerate(lines[-40:], start=len(lines)-39):
    print(idx, line)
