"""Design-system guard: fail when styling bypasses the central tokens.

python scripts/check_design_tokens.py          # exit 1 and list violations
(also runs inside `python -m unittest discover -s tests`)

Checked in every stylesheet except tokens.css, every template, and the live
JS (main.js, features/*.js, core/*.js — CSS-declaration syntax only):

  font-family   must be var(--font-sans|--font-mono) / inherit / an icon font
  font-size     must not be a raw px/rem value ≥ 8px (use --fs-N / --text-*)
  var(--x, #c)  colour fallbacks are forbidden (they pin one theme)
  colour        no #hex / rgb() / rgba() literals in CSS rules or inline
                style attributes — use a semantic token. Pure-black alpha
                (rgba(0,0,0,a)) is allowed: shadows and photo scrims are
                dark in every theme.

Deliberate exceptions (theme-preview swatches, the auth brand palette that
must match its WebGL scene, marks drawn on top of user photos, the iOS 16px
input minimum) are fenced in the source with
    ds-allow-start: <reason>   …   ds-allow-end
inside any comment syntax, or `ds-allow` on a single line. The reason is
mandatory so every exception documents itself. Comments are ignored, so
explanatory text may mention colours freely.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FONT_FAMILY = re.compile(r'font-family\s*:\s*([^;}"]+)')
FONT_SIZE = re.compile(r'font-size\s*:\s*(\d+(?:\.\d+)?|\.\d+)(px|rem)\b')
# geometry: raw px radius / spacing and raw durations must go through the knobs
RADIUS = re.compile(r'(?<![\w-])border(?:-(?:top|bottom)-(?:left|right))?-radius\s*:\s*([^;{}"]+)')
SPACING = re.compile(r'(?<![\w-])(?:padding|margin)(?:-[a-z-]+)?\s*:\s*([^;{}"]+)|(?<![\w-])(?:gap|row-gap|column-gap)\s*:\s*([^;{}"]+)')
MOTION = re.compile(r'(?<![\w-])(?:transition|animation)(?:-duration)?\s*:\s*([^;{}"]+)')
RAW_PX = re.compile(r'(?<![\w.(-])\d*\.?\d*[1-9]\d*px\b')
RAW_DUR = re.compile(r'(?<![\w.(-])\d*\.?\d*[1-9]\d*m?s\b')
FALLBACK = re.compile(r'var\(--[\w-]+\s*,\s*(#|rgba?\()')
COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d[^)]*\)')
BLACK = re.compile(r'rgba?\(\s*0\s*,\s*0\s*,\s*0\s*[,)]')
OK_FAMILY = re.compile(r"^\s*(var\(--font-(sans|mono)\)|inherit|'Font Awesome[^']*')\s*(!important)?\s*$")
CSS_COMMENT = re.compile(r'/\*.*?\*/', re.S)
HTML_COMMENT = re.compile(r'<!--.*?-->|\{#.*?#\}', re.S)
STYLE_ATTR = re.compile(r'style="([^"]*)"')


def _blank(match):
    # keep line numbers (and any ds-allow markers) stable
    text = match.group(0)
    keep = ' ds-allow-start ' if 'ds-allow-start' in text else ''
    keep += ' ds-allow-end ' if 'ds-allow-end' in text else ''
    keep += ' ds-allow ' if re.search(r'ds-allow(?![-\w])', text) else ''
    return keep + '\n' * text.count('\n')


def targets():
    css = sorted(p for p in (ROOT / 'static/css').glob('*.css') if p.name != 'tokens.css')
    tpl = sorted((ROOT / 'templates').rglob('*.html'))
    js = [ROOT / 'static/js/main.js', *sorted((ROOT / 'static/js/features').glob('*.js')),
          *sorted((ROOT / 'static/js/core').glob('*.js'))]
    return css + tpl + js


def scan(path):
    raw = path.read_text(encoding='utf-8')
    kind = path.suffix
    text = CSS_COMMENT.sub(_blank, raw) if kind in ('.css', '.html') else raw
    if kind == '.html':
        text = HTML_COMMENT.sub(_blank, text)
    problems, allowed = [], False
    for no, line in enumerate(text.splitlines(), 1):
        if 'ds-allow-start' in line:
            allowed = True
        if 'ds-allow-end' in line:
            allowed = False
            continue
        if allowed or re.search(r'ds-allow(?![-\w])', line):
            continue
        for m in FONT_FAMILY.finditer(line):
            if not OK_FAMILY.match(m.group(1)) and kind != '.js' or (
                    kind == '.js' and re.search(r"'(Sora|Inter|JetBrains Mono|Outfit)'", m.group(1))):
                problems.append((no, 'font-family literal', m.group(0).strip()))
        for m in FONT_SIZE.finditer(line):
            px = float(m.group(1)) * (16 if m.group(2) == 'rem' else 1)
            if px >= 8:
                problems.append((no, 'raw font-size', m.group(0)))
        if kind in ('.css', '.html'):
            chunks = [line] if kind == '.css' else STYLE_ATTR.findall(line)
            for chunk in chunks:
                for m in RADIUS.finditer(chunk):
                    if RAW_PX.search(m.group(1)):
                        problems.append((no, 'raw border-radius', m.group(0).strip()[:60]))
                for m in SPACING.finditer(chunk):
                    if RAW_PX.search(m.group(1) or m.group(2) or ''):
                        problems.append((no, 'raw spacing', m.group(0).strip()[:60]))
                for m in MOTION.finditer(chunk):
                    if RAW_DUR.search(m.group(1)):
                        problems.append((no, 'raw duration', m.group(0).strip()[:60]))
        for m in FALLBACK.finditer(line):
            problems.append((no, 'colour fallback in var()', m.group(0)))
        if kind == '.css':
            scope = [line]
        elif kind == '.html':
            scope = STYLE_ATTR.findall(line)
        else:
            scope = []
        for chunk in scope:
            for m in COLOUR.finditer(chunk):
                if not BLACK.match(m.group(0)):
                    problems.append((no, 'colour literal', m.group(0)))
    return problems


def run():
    report = {}
    for path in targets():
        found = scan(path)
        if found:
            report[path.relative_to(ROOT).as_posix()] = found
    return report


def main():
    report = run()
    total = sum(len(v) for v in report.values())
    for name, rows in report.items():
        for no, rule, text in rows:
            print(f'{name}:{no}: {rule}: {text}')
    print(f'{total} design-token violation(s) in {len(report)} file(s)')
    raise SystemExit(1 if total else 0)


if __name__ == '__main__':
    main()
