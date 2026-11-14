"""Regenerate the source inventory without importing the app or opening live data."""
import ast
import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag in ('button', 'a', 'input', 'select', 'textarea', 'form', 'dialog'):
            self.items.append({'tag': tag, **dict(attrs), 'status': 'NOT TESTED'})


def inventory():
    routes = []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'route':
                    methods = ['GET']
                    for kw in dec.keywords:
                        if kw.arg == 'methods':
                            methods = ast.literal_eval(kw.value)
                    routes.append(dict(route=ast.literal_eval(dec.args[0]), methods=methods,
                                       handler=node.name, file=path.relative_to(ROOT).as_posix(),
                                       line=node.lineno, status='NOT TESTED'))
    templates = []
    for path in sorted((ROOT / 'templates').rglob('*.html')):
        parser = Controls()
        parser.feed(path.read_text(encoding='utf-8-sig'))
        templates.append(dict(file=path.relative_to(ROOT).as_posix(), controls=parser.items))
    return dict(routes=routes, templates=templates)


if __name__ == '__main__':
    result = inventory()
    destination = ROOT / 'docs' / 'audit-source-inventory.json'
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"{len(result['routes'])} route declarations; {len(result['templates'])} templates; "
          f"{sum(len(t['controls']) for t in result['templates'])} static controls. {destination}")
