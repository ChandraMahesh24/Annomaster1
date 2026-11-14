"""Pixel-diff two design-system snapshot sets from browser_audit.py ds-snapshots.

python scripts/compare_design_snapshots.py before after [--threshold 0.001]

Reports, per page/theme/viewport, the fraction of pixels whose RGB differs by
more than 8/255 in any channel. A token refactor that changes nothing visible
should stay at (near) zero; any row above the threshold is listed for review.
Exit 1 when a row exceeds the threshold, so it can gate a migration step.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.audit-browser' / 'ds'


def diff_fraction(a_path, b_path):
    a = Image.open(a_path).convert('RGB')
    b = Image.open(b_path).convert('RGB')
    if a.size != b.size:
        return 1.0, None
    diff = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 8 else 0)
    box = diff.getbbox()
    changed = diff.histogram()[255]
    return changed / (a.size[0] * a.size[1]), box


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    before, after = (args + ['before', 'after'])[:2]
    threshold = 0.001
    if '--threshold' in sys.argv:
        threshold = float(sys.argv[sys.argv.index('--threshold') + 1])
    rows = []
    for a_path in sorted((BASE / before).glob('*.png')):
        b_path = BASE / after / a_path.name
        if not b_path.exists():
            rows.append(dict(name=a_path.stem, status='MISSING'))
            continue
        frac, box = diff_fraction(a_path, b_path)
        rows.append(dict(name=a_path.stem, changed=round(frac, 5), box=box,
                         status='SAME' if frac <= threshold else 'CHANGED'))
        if frac > threshold:
            out = BASE / f'diff-{before}-vs-{after}'
            out.mkdir(exist_ok=True)
            a = Image.open(a_path).convert('RGB')
            b = Image.open(b_path).convert('RGB')
            if a.size == b.size:
                mask = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 8 else 0)
                red = Image.new('RGB', a.size, (255, 0, 64))
                Image.composite(red, b, mask).save(out / a_path.name)
    changed = [r for r in rows if r['status'] != 'SAME']
    report = dict(before=before, after=after, threshold=threshold, total=len(rows),
                  same=len(rows) - len(changed), changed=changed)
    (BASE / f'compare-{before}-vs-{after}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'{len(rows)} snapshots, {len(rows) - len(changed)} unchanged, {len(changed)} changed (> {threshold:.3%})')
    for r in changed:
        print(f"  {r['status']:8} {r['name']:40} {r.get('changed', '')} box={r.get('box')}")
    raise SystemExit(1 if changed else 0)


if __name__ == '__main__':
    main()
