#!/usr/bin/env python
"""
One-command launcher for AnnoMaster-next (FastAPI backend + React/Vite frontend).

Like the original app's run.py, but this project is two processes, so this
starts BOTH together and streams their output with [backend]/[frontend] tags.

    python run.py            # run backend + frontend together
    python run.py backend    # backend only  (http://localhost:8000)
    python run.py frontend   # frontend only (http://localhost:5173)

On start it: checks backend/.env exists, runs `alembic upgrade head` to bring the
DB schema up to date, `npm install`s the frontend if node_modules is missing,
then launches. Press Ctrl+C once to stop everything cleanly.

Open the app at  →  http://localhost:5173
(The frontend proxies /api to the backend on :8000, so use the 5173 URL.)
"""
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'
IS_WIN = os.name == 'nt'

# The default Windows console is cp1252 and chokes on the arrows/✓ that both this
# script and Vite print. Force UTF-8 (replace anything unencodable) so a stray
# glyph never crashes the launcher.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _run(cmd, cwd):
    """Popen with a shell on Windows (so `npm`/`npm.cmd` resolves), line-buffered."""
    return subprocess.Popen(
        cmd, cwd=str(cwd), shell=IS_WIN,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )


def _pump(proc, tag):
    """Forward a child's output to our console, tagged, until it closes."""
    for line in proc.stdout:
        sys.stdout.write(f'[{tag}] {line}')
        sys.stdout.flush()


def _preflight():
    if not (BACKEND / '.env').exists():
        print('!! backend/.env is missing — copy backend/.env.example to backend/.env first.')
        sys.exit(1)
    # Bring the DB schema up to date (idempotent).
    print('== running alembic upgrade head ...')
    r = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=str(BACKEND))
    if r.returncode != 0:
        print('!! alembic upgrade failed — see the error above.')
        sys.exit(1)


def _ensure_npm():
    if not (FRONTEND / 'node_modules').exists():
        print('== node_modules missing — running npm install (first run only) ...')
        r = subprocess.run('npm install', cwd=str(FRONTEND), shell=True)
        if r.returncode != 0:
            print('!! npm install failed.')
            sys.exit(1)


def backend_cmd():
    # --reload = hot reload on code changes (dev). Matches the old app's debug run.
    return [sys.executable, '-m', 'uvicorn', 'app.main:app',
            '--reload', '--host', '0.0.0.0', '--port', '8000']


def main():
    what = (sys.argv[1] if len(sys.argv) > 1 else 'both').lower()
    if what not in ('both', 'backend', 'frontend'):
        print(__doc__)
        sys.exit(1)

    procs = []
    try:
        if what in ('both', 'backend'):
            _preflight()
        if what in ('both', 'frontend'):
            _ensure_npm()

        if what in ('both', 'backend'):
            print('== starting backend  → http://localhost:8000')
            procs.append(('backend', _run(backend_cmd(), BACKEND)))
        if what in ('both', 'frontend'):
            print('== starting frontend → http://localhost:5173  (open this one)')
            procs.append(('frontend', _run('npm run dev', FRONTEND)))

        threads = [threading.Thread(target=_pump, args=(p, tag), daemon=True)
                   for tag, p in procs]
        for t in threads:
            t.start()

        # Wait for any child to exit; if one dies, tear the rest down.
        while True:
            for tag, p in procs:
                code = p.poll()
                if code is not None:
                    print(f'\n== {tag} exited (code {code}) — shutting down the rest.')
                    return
            for t in threads:
                t.join(timeout=0.3)
    except KeyboardInterrupt:
        print('\n== Ctrl+C — stopping ...')
    finally:
        for tag, p in procs:
            if p.poll() is None:
                p.terminate()
        for tag, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == '__main__':
    main()
