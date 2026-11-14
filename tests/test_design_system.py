"""Design-system contract checks (no browser, no database).

Fails when styling bypasses the central tokens (see DESIGN_SYSTEM.md) or when
a page stops using the shared <head> partial.
"""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    spec = importlib.util.spec_from_file_location('check_design_tokens', ROOT / 'scripts/check_design_tokens.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DesignTokenGuard(unittest.TestCase):
    def test_no_hardcoded_fonts_sizes_or_colours(self):
        report = _load_checker().run()
        lines = [f'{f}:{n}: {rule}: {txt}' for f, rows in report.items() for n, rule, txt in rows]
        self.assertEqual(lines, [], 'Styling bypasses tokens.css:\n' + '\n'.join(lines[:40]))

    def test_checker_catches_violations(self):
        """The guard must actually detect each rule (guards against a silently broken regex)."""
        checker = _load_checker()
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.css'
            bad.write_text(".x { font-family: 'Sora', sans-serif; font-size: 12px; color: #123456;"
                           " background: var(--bg, #fff); box-shadow: 0 1px 2px rgba(0,0,0,.4); }\n"
                           "/* a comment may say #abcdef */\n"
                           ".y { color: #fff; } /* ds-allow: test exception */\n"
                           ".z { border-radius: 8px; padding: 4px 6px; transition: color .2s; margin: 0; }\n",
                           encoding='utf-8')
            rules = sorted({rule for _, rule, _ in checker.scan(bad)})
        self.assertEqual(rules, ['colour fallback in var()', 'colour literal', 'font-family literal',
                                 'raw border-radius', 'raw duration', 'raw font-size', 'raw spacing'])

    def test_every_page_uses_shared_head(self):
        pages = ['auth/login.html', 'auth/register.html', 'auth/forgot_password.html', 'pages/help.html',
                 'pages/settings.html', 'pages/annotate.html', 'workspace/dashboard.html', 'workspace/members.html']
        for page in pages:
            src = (ROOT / 'templates' / page).read_text(encoding='utf-8')
            with self.subTest(page=page):
                self.assertIn("{% include 'layout/head_assets.html' %}", src)
                # fonts/tokens must come only from the partial
                self.assertNotIn('fonts.googleapis.com', src)
                self.assertNotRegex(src, r'href="/static/css/(tokens|base|components|modes)\.css')

    def test_rendered_cascade_order(self):
        from app import create_app
        app = create_app()
        with app.app_context():
            html = app.jinja_env.get_template('pages/annotate.html').render()
        order = [m.group(1) for m in re.finditer(r'/static/css/([\w-]+)\.css\?v=\d+', html)]
        self.assertEqual(order[:3], ['tokens', 'base', 'components'])
        self.assertEqual(order[-1], 'modes')

    def test_every_used_custom_property_is_defined(self):
        """A misspelled or deleted token silently falls back to nothing; catch it."""
        sources = list((ROOT / 'static/css').glob('*.css')) + list((ROOT / 'templates').rglob('*.html')) + \
            [p for p in (ROOT / 'static/js').rglob('*.js') if p.name != 'canvas.js']
        text = {p: p.read_text(encoding='utf-8') for p in sources}
        defined = set()
        for t in text.values():
            defined |= set(re.findall(r'(--[\w-]+)\s*:', t))
            defined |= set(re.findall(r"setProperty\(\s*['\"`](--[\w-]+)", t))
        missing = {}
        for p, t in text.items():
            if p.suffix != '.css':
                continue
            code = re.sub(r'/\*.*?\*/', '', t, flags=re.S)      # comments may mention tokens
            for name in set(re.findall(r'var\((--[\w-]+)', code)) - defined:
                missing.setdefault(name, p.name)
        self.assertEqual(missing, {}, 'var(--x) used but never defined')

    def test_typography_scale_is_complete(self):
        tokens = (ROOT / 'static/css/tokens.css').read_text(encoding='utf-8')
        used = set()
        for path in list((ROOT / 'static/css').glob('*.css')) + list((ROOT / 'templates').rglob('*.html')) + \
                [ROOT / 'static/js/main.js', *(ROOT / 'static/js/features').glob('*.js')]:
            used |= set(re.findall(r'var\(--fs-(\d+)\)', path.read_text(encoding='utf-8')))
        missing = sorted(n for n in used if f'--fs-{n}:' not in tokens)
        self.assertEqual(missing, [], 'size steps used but not defined in tokens.css')


if __name__ == '__main__':
    unittest.main()
