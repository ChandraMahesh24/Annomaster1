"""
migrate_v1_to_v2.py
Move old data/projects/<name>/ into the new workspace structure.
Usage:
  python scripts/migrate_v1_to_v2.py --owner-email you@example.com --workspace-name "My Workspace"
"""
import argparse, sys, shutil
from pathlib import Path

BASE = Path(__file__).parent.parent
OLD  = BASE / 'data' / 'projects'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-email',    required=True)
    parser.add_argument('--workspace-name', default='Migrated Workspace')
    args = parser.parse_args()

    if not OLD.exists():
        print("No old data/projects found — nothing to migrate."); sys.exit(0)

    # Bootstrap Flask app to use DB
    sys.path.insert(0, str(BASE))
    from app import create_app, db
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember
    import re, time

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=args.owner_email).first()
        if not user:
            print(f"User {args.owner_email} not found. Register first."); sys.exit(1)

        slug = re.sub(r'[^a-z0-9]+', '_', args.workspace_name.lower()).strip('_')
        if Workspace.query.filter_by(folder_name=slug).first():
            slug = f"{slug}_{int(time.time()) % 100000}"

        ws = Workspace(name=args.workspace_name, folder_name=slug)
        db.session.add(ws)
        db.session.flush()
        db.session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role='owner'))  # type: ignore[call-arg]

        ws_projects = BASE / 'workspace' / slug / 'projects'
        ws_projects.mkdir(parents=True, exist_ok=True)

        for proj in sorted(OLD.iterdir()):
            if proj.is_dir():
                dest = ws_projects / proj.name
                shutil.copytree(str(proj), str(dest), dirs_exist_ok=True)
                print(f"  Migrated: {proj.name}")

        db.session.commit()
        print(f"\nDone. Workspace '{args.workspace_name}' (folder: {slug}) created.")
        print(f"Owner: {user.email}")

if __name__ == '__main__':
    main()
