"""Change class IDs project-wide (core/class_reindex.py + /classes/reindex).

Scenario from the user: jcb 0, road 1, tree 2, 1_staff 3; move tree to 0.
"""
import json
import os
import zipfile
from datetime import datetime, timedelta
from unittest.mock import patch

import yaml

from test_review import ReviewFixture
from app import db
from app.core import class_reindex
from app.core.storage import save_project_meta, load_project_meta
from app.models.annotation_lock import AnnotationLock
from app.models.user import User

CLASSES = [{'id': 0, 'name': 'jcb', 'color': [1, 1, 1]}, {'id': 1, 'name': 'road', 'color': [2, 2, 2]},
           {'id': 2, 'name': 'tree', 'color': [3, 3, 3]}, {'id': 3, 'name': '1_staff', 'color': [4, 4, 4]}]
ACTIVE = ('0 0.100000 0.200000 0.050000 0.060000\n'
          '2 0.300000 0.400000 0.070000 0.080000\n'
          '  2   0.1 0.1 0.2 0.1 0.2 0.2\n'          # polygon, odd spacing
          '3 0.5 0.5 0.1 0.1\n')
DONE = '0 0.5 0.5 0.1 0.1\n2 0.6 0.6 0.1 0.1\n1 0.7 0.7 0.1 0.1\n'
VERSION = '2 0.5 0.5 0.1 0.1\n'


class ClassReindex(ReviewFixture):
    def setUp(self):
        super().setUp()
        save_project_meta('WS-TEST', 'demo', {'name': 'demo', 'classes': [dict(c) for c in CLASSES]})
        self.active = self.pd / 'Active_Work/job_test/labels/frame.txt'
        self.active.parent.mkdir(parents=True, exist_ok=True)
        self.active.write_bytes(ACTIVE.encode())          # exact bytes (LF)
        self.sidecar = self.pd / 'Active_Work/job_test/labels/frame.suggestions.json'
        self.sidecar.write_text(json.dumps({'version': 1, 'boxes': [
            {'id': 's1', 'state': 'suggested', 'class_id': 2, 'x_center': .5, 'y_center': .5, 'width': .1, 'height': .1},
            {'id': 's2', 'state': 'rejected', 'class_id': 0, 'x_center': .4, 'y_center': .4, 'width': .1, 'height': .1}]}),
            encoding='utf-8')
        self.done = self.pd / 'Completed_Datasets/job_x/train/labels/b.txt'
        self.done.parent.mkdir(parents=True)
        self.done.write_bytes(DONE.replace('\n', '\r\n').encode())   # Windows line endings (CRLF)
        self.version = self.pd / 'Versions/v1/train/labels/c.txt'
        self.version.parent.mkdir(parents=True)
        self.version.write_bytes(VERSION.encode())
        self.examples = self.pd / 'prompt_examples.json'
        self.examples.write_text(json.dumps({'version': 1, 'examples': [
            {'id': 'ex1', 'class_id': 2, 'positive': True, 'image': 'x.jpg', 'box': [0, 0, 1, 1]}]}), encoding='utf-8')
        (self.pd / 'data.yaml').write_text(yaml.dump({'names': ['jcb', 'road', 'tree', '1_staff'], 'nc': 4}),
                                           encoding='utf-8')

    def reindex(self, mapping, role='owner', dry_run=False):
        return self.post('/classes/reindex', role=role, mapping=mapping, dry_run=dry_run)

    def ids(self):
        return {c['name']: c['id'] for c in load_project_meta('WS-TEST', 'demo')['classes']}

    # ── the user's case ────────────────────────────────────────────────────
    def test_dry_run_previews_and_writes_nothing(self):
        before = {p: p.read_bytes() for p in (self.active, self.done, self.sidecar, self.examples)}
        r = self.reindex({'2': 0, '0': 2}, dry_run=True)
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertEqual(d['mapping'], {'0': 2, '2': 0})
        self.assertEqual(d['boxes'], 2 + 3)                      # jcb x2, tree x3 (incl. polygon)
        self.assertEqual(d['files'], 4)                          # 2 label files, sidecar, examples
        self.assertEqual([(c['name'], c['new_id']) for c in d['classes']],
                         [('jcb', 2), ('road', 1), ('tree', 0), ('1_staff', 3)])
        for p, raw in before.items():
            self.assertEqual(p.read_bytes(), raw, p)
        self.assertEqual(self.ids()['tree'], 2)
        self.assertFalse((self.pd / '_backups').exists())

    def test_swap_tree_and_jcb_rewrites_everything_but_versions(self):
        r = self.reindex({'2': 0, '0': 2})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.ids(), {'tree': 0, 'road': 1, 'jcb': 2, '1_staff': 3})
        self.assertEqual(self.active.read_bytes().decode(),
                         '2 0.100000 0.200000 0.050000 0.060000\n'
                         '0 0.300000 0.400000 0.070000 0.080000\n'
                         '  0   0.1 0.1 0.2 0.1 0.2 0.2\n'      # coordinates/spacing untouched
                         '3 0.5 0.5 0.1 0.1\n')
        self.assertEqual(self.done.read_bytes(), b'2 0.5 0.5 0.1 0.1\r\n0 0.6 0.6 0.1 0.1\r\n1 0.7 0.7 0.1 0.1\r\n')  # CRLF kept
        self.assertEqual(self.version.read_bytes(), VERSION.encode())   # immutable snapshot
        side = json.loads(self.sidecar.read_text(encoding='utf-8'))['boxes']
        self.assertEqual([b['class_id'] for b in side], [0, 2])
        self.assertEqual(json.loads(self.examples.read_text(encoding='utf-8'))['examples'][0]['class_id'], 0)
        self.assertEqual(yaml.safe_load((self.pd / 'data.yaml').read_text(encoding='utf-8'))['names'],
                         ['tree', 'road', 'jcb', '1_staff'])
        # backup zip holds the originals at project-relative paths
        backup = self.pd / r.get_json()['backup']
        with zipfile.ZipFile(backup) as z:
            self.assertEqual(z.read('Active_Work/job_test/labels/frame.txt').decode(), ACTIVE)
            self.assertIn('project.json', z.namelist())
            self.assertEqual(json.loads(z.read('MAPPING.json'))['mapping'], {'0': 2, '2': 0})
        # the stats the Classes page shows follow the new IDs
        counts = {c['id']: c['count'] for c in self.client.get(self.base + '/stats', headers=self.headers['owner'])
                  .get_json()['class_counts']}
        self.assertEqual(counts[0], 2)          # tree's two boxes in Active_Work (Completed is not in /stats media)

    def test_shift_moves_tree_to_zero_and_others_up(self):
        r = self.reindex({'2': 0, '0': 1, '1': 2})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.ids(), {'tree': 0, 'jcb': 1, 'road': 2, '1_staff': 3})
        self.assertEqual(self.done.read_bytes(), b'1 0.5 0.5 0.1 0.1\r\n0 0.6 0.6 0.1 0.1\r\n2 0.7 0.7 0.1 0.1\r\n')

    # ── refusals ───────────────────────────────────────────────────────────
    def test_invalid_mappings_are_refused_and_change_nothing(self):
        raw = self.active.read_bytes()
        for mapping, needle in (({'2': 0}, 'share ID 0'), ({'9': 0}, 'no class with ID 9'),
                                ({'2': 2}, 'Nothing to change'), ({'2': -1}, 'negative'), ({'2': 'x'}, 'whole numbers')):
            r = self.reindex(mapping)
            self.assertEqual(r.status_code, 422, (mapping, r.get_json()))
            self.assertIn(needle, r.get_json()['error'])
        self.assertEqual(self.reindex({}).status_code, 400)
        self.assertEqual(self.active.read_bytes(), raw)
        self.assertEqual(self.ids()['tree'], 2)

    def test_orphan_labels_of_a_deleted_class_block_that_id(self):
        # a deleted class 7 still has a box in Completed_Datasets
        self.done.write_bytes((DONE + '7 0.1 0.1 0.1 0.1\n').encode())
        r = self.reindex({'3': 7})
        self.assertEqual(r.status_code, 422)
        self.assertIn('left over from a deleted class', r.get_json()['error'])
        self.assertEqual(self.reindex({'3': 8}).status_code, 200)        # a clean free ID is fine

    def test_permissions_and_other_users_locks(self):
        self.assertEqual(self.reindex({'2': 0, '0': 2}, role='viewer').status_code, 403)
        editor = User.query.filter_by(username='editor').one()
        db.session.add(AnnotationLock(workspace_id=self.ws.id, project='demo', image_path='Active_Work/job_test/images/frame.jpg',
                                      locked_by=editor.id, expires_at=datetime.utcnow() + timedelta(seconds=60)))
        db.session.commit()
        r = self.reindex({'2': 0, '0': 2})
        self.assertEqual(r.status_code, 409)
        self.assertIn('editor', r.get_json()['error'])
        self.assertEqual(self.ids()['tree'], 2)
        self.assertEqual(self.reindex({'2': 0, '0': 2}, dry_run=True).status_code, 200)   # preview still allowed
        AnnotationLock.query.delete(); db.session.commit()
        owner = User.query.filter_by(username='owner').one()
        db.session.add(AnnotationLock(workspace_id=self.ws.id, project='demo', image_path='x', locked_by=owner.id,
                                      expires_at=datetime.utcnow() + timedelta(seconds=60)))
        db.session.commit()
        self.assertEqual(self.reindex({'2': 0, '0': 2}).status_code, 200)               # own lock is fine

    def test_failed_write_rolls_every_file_back(self):
        originals = {p: p.read_bytes() for p in (self.active, self.done, self.sidecar, self.examples,
                                                  self.pd / 'project.json', self.pd / 'data.yaml')}
        real_replace, calls = os.replace, {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] == 3:
                raise OSError('disk full')
            return real_replace(src, dst)
        with patch('app.core.class_reindex.os.replace', side_effect=flaky):
            with self.assertRaises(OSError):
                class_reindex.apply('WS-TEST', 'demo', {'2': 0, '0': 2})
        for p, raw in originals.items():
            self.assertEqual(p.read_bytes(), raw, p)
        self.assertFalse(list(self.pd.rglob('*.reindex.tmp')))
