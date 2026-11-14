"""Preserve the latest browser evidence without disposable account/token fixtures."""
import json
from datetime import date
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
phases = {}
for path in sorted((ROOT / '.audit-browser').glob('*-results.json')):
    data = json.loads(path.read_text(encoding='utf-8'))
    phases[path.stem.removesuffix('-results')] = data
counts = Counter(row['status'] for data in phases.values() for row in data['results'])
result = {
    'date': date.today().isoformat(),
    'environment': 'Installed Chrome, Python Playwright, disposable Flask/SQLite/workspace on loopback5055',
    'scope': 'Selected assertions and workflow groups, NOT exhaustive control coverage. OBSERVED is not PASS.',
    'viewports': {'desktop': [1440, 900], 'tablet': [768, 1024], 'mobile': [390, 844]},
    'counts': dict(counts),
    'phases': phases,
}
destination = ROOT / 'docs/audit-browser-results.json'
destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(dict(counts))
print(destination)
