from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)




# ── The port (annomaster-next) now has its OWN one-command launcher: ──────────
#   cd D:\anno\annomaster__30_04_2026\annomaster\annomaster-next
#   python run.py            # backend + frontend together → open http://localhost:5173
#   python run.py backend    # backend only  (:8000)
#   python run.py frontend   # frontend only (:5173)
# (or double-click annomaster-next\run.bat