"""Isolated live-app checks. Regression coverage for the four reviewed defects."""
import tempfile
import unittest
from pathlib import Path

from app import create_app, db
from config import Config
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.utils.security import generate_token
from app.core.paths import label_path_for_image
from app.core.yolo import parse_yolo_label, write_yolo_label, is_valid_annotation_file


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='annomaster-review-')
        self.root = Path(self.tmp.name)

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            WORKSPACE_ROOT = self.root / 'workspace'
            SECRET_KEY = 'isolated-review-secret-key-long-enough'
            JWT_SECRET = SECRET_KEY
            RATELIMIT_ENABLED = False

        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        users = []
        for name in ('owner', 'editor', 'viewer', 'outsider'):
            user = User(username=name, email=f'{name}@example.test')
            user.set_password('test-password-123')
            db.session.add(user)
            users.append(user)
        self.ws = Workspace(name='Test', folder_name='WS-TEST', public_id='WS-TEST')
        db.session.add(self.ws)
        db.session.flush()
        for user, role in zip(users, ('owner', 'editor', 'viewer')):
            db.session.add(WorkspaceMember(workspace_id=self.ws.id, user_id=user.id, role=role))
        db.session.commit()
        self.headers = {u.username: {'Authorization': 'Bearer ' + generate_token(u.id)} for u in users}
        self.base = f'/api/workspaces/{self.ws.id}/projects/demo'
        self.pd = TestConfig.WORKSPACE_ROOT / 'WS-TEST/projects/demo'
        self.rel = 'Active_Work/job_test/images/frame.jpg'
        (self.pd / self.rel).parent.mkdir(parents=True)
        (self.pd / self.rel).write_bytes(b'test fixture')
        self.box = dict(class_id=0, x_center=.5, y_center=.5, width=.2, height=.2)

    def tearDown(self):
        from app.core.db_index import close_project
        close_project(self.pd)
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()
        self.tmp.cleanup()

    def post(self, route, role='owner', **data):
        return self.client.post(self.base + route, headers=self.headers[role], json=data)


class LiveAppReview(ReviewFixture):
    def test_health_and_pages(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        for page in ('/login', '/register', '/forgot-password'):
            self.assertEqual(self.client.get(page).status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/', headers=self.headers['owner']).status_code, 200)
        for name in ('workspace/dashboard.html', 'pages/annotate.html', 'pages/settings.html'):
            self.app.jinja_env.get_template(name).render()

    def test_auth_and_membership(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.get('/api/auth/me', headers=self.headers['owner']).status_code, 200)
        self.assertEqual(self.client.get(self.base + '/annotations', headers=self.headers['outsider']).status_code, 403)
        self.assertEqual(self.post('/annotations', role='viewer', path=self.rel, bboxes=[]).status_code, 403)

    def test_login(self):
        for password, status in (('incorrect', 401), ('test-password-123', 200)):
            response = self.client.post('/api/auth/login', json={'email': 'owner@example.test', 'password': password})
            self.assertEqual(response.status_code, status)

    def test_suggestions_separate_from_ground_truth(self):
        suggested = dict(self.box, state='suggested', id='s1')
        self.assertEqual(self.post('/annotations', path=self.rel, bboxes=[self.box, suggested]).status_code, 200)
        lbl = label_path_for_image(self.pd / self.rel)
        self.assertEqual(len(parse_yolo_label(lbl)), 1)
        self.assertTrue(is_valid_annotation_file(lbl))
        result = self.client.get(self.base + '/annotations', headers=self.headers['owner'], query_string={'path': self.rel}).get_json()
        self.assertEqual(len(result['suggestions']), 1)
        self.assertEqual(result['bboxes'][0]['state'], 'confirmed')

    def test_lock_blocks_regular_save(self):
        self.assertEqual(self.post('/locks/acquire', path=self.rel).status_code, 200)
        self.assertEqual(self.post('/annotations', role='editor', path=self.rel, bboxes=[self.box]).status_code, 409)

    def test_reset_token_single_use(self):
        from app.core.password_reset import make_token, verify_token
        user = User.query.filter_by(username='owner').one()
        token = make_token(user)
        self.assertIsNotNone(verify_token(token))
        user.set_password('new-test-password')
        db.session.commit()
        self.assertIsNone(verify_token(token))

    def test_regression_image_path_must_stay_in_project(self):
        sentinel = self.root / 'sentinel.txt'
        sentinel.write_text('private fixture', encoding='utf-8')
        response = self.client.get(self.base + '/image', headers=self.headers['viewer'], query_string={'path': str(sentinel)})
        try:
            self.assertIn(response.status_code, (400, 403, 404))
        finally:
            response.close()

    def test_regression_null_must_respect_lock(self):
        self.post('/annotations', path=self.rel, bboxes=[self.box])
        self.post('/locks/acquire', path=self.rel)
        response = self.post('/null', role='editor', path=self.rel)
        self.assertEqual(response.status_code, 409)
        response = self.client.delete(self.base + '/null', headers=self.headers['editor'], json={'path': self.rel})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(parse_yolo_label(label_path_for_image(self.pd / self.rel))), 1)
        self.assertEqual(self.post('/null', path=self.rel).status_code, 200)
        self.assertEqual(self.client.delete(self.base + '/null', headers=self.headers['owner'], json={'path': self.rel}).status_code, 200)

    def test_regression_writer_reader_agree_on_box_size(self):
        lbl = self.root / 'oversized.txt'
        with self.assertRaises(ValueError):
            write_yolo_label(lbl, [dict(self.box, width=2)])
        self.assertFalse(lbl.exists())

    def test_regression_invalid_json_shape_is_client_error(self):
        self.app.config['PROPAGATE_EXCEPTIONS'] = False
        response = self.client.post('/api/auth/login', json=['unexpected'])
        self.assertEqual(response.status_code, 400)

    def test_path_variants_rejected_for_reads_and_writes(self):
        paths = [str(self.root / 'sentinel.txt'), '../outside.jpg', r'..\outside.jpg',
                 'C:/private.jpg', r'\\server\share\image.jpg', 'C:private.jpg',
                 self.rel.replace('images/', 'images/../images/'), '', 'file.jpg:stream']
        for path in paths:
            with self.subTest(path=path):
                for route in ('/image', '/thumbnail', '/annotations'):
                    r = self.client.get(self.base + route, headers=self.headers['owner'], query_string={'path': path})
                    self.assertEqual(r.status_code, 400, route)
                    r.close()
                for route in ('/annotations', '/null', '/locks/acquire', '/cover-from-path'):
                    self.assertEqual(self.post(route, path=path, bboxes=[self.box]).status_code, 400, route)
                self.assertEqual(self.post('/datasets/images/delete', paths=[self.rel, path]).status_code, 400)
                self.assertTrue((self.pd / self.rel).exists())
                from app.api.ai_annotate import _resolve_image
                from werkzeug.exceptions import BadRequest
                with self.assertRaises(BadRequest):
                    _resolve_image('WS-TEST', 'demo', path)
        response = self.client.get(self.base + '/image', headers=self.headers['owner'], query_string={'path': self.rel})
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_invalid_labels_preserve_existing_ground_truth(self):
        self.post('/annotations', path=self.rel, bboxes=[self.box])
        lbl = label_path_for_image(self.pd / self.rel)
        before = lbl.read_bytes()
        bad_boxes = [dict(self.box, width=2), dict(self.box, height=float('nan')),
                     dict(self.box, class_id=-1), dict(self.box, class_id=.5),
                     dict(self.box, width=.00000001), dict(self.box, type='polygon', points=[]),
                     dict(self.box, width='0.2'), 'invalid']
        for bad in bad_boxes:
            with self.subTest(box=bad):
                self.assertEqual(self.post('/annotations', path=self.rel, bboxes=[self.box, bad]).status_code, 400)
                self.assertEqual(lbl.read_bytes(), before)
                with self.assertRaises(ValueError):
                    write_yolo_label(lbl, [bad])
                self.assertEqual(lbl.read_bytes(), before)

    def test_json_validation(self):
        for body in ([], ['x'], 'text', 3, None, {'email': 42, 'password': 'password'}, {'email': 'x', 'password': []}):
            with self.subTest(body=body):
                r = self.client.post('/api/auth/login', json=body)
                self.assertEqual(r.status_code, 400)
                self.assertIsNotNone(r.get_json())
        self.assertEqual(self.client.post('/api/auth/login', data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.base + '/annotations', headers=self.headers['owner'], json=['x']).status_code, 400)

    def test_valid_polygon_round_trip_and_clear(self):
        polygon = dict(class_id=2, type='polygon', points=[dict(x=0, y=0), dict(x=1, y=0), dict(x=.5, y=1)])
        self.assertEqual(self.post('/annotations', path=self.rel, bboxes=[polygon]).status_code, 200)
        lbl = label_path_for_image(self.pd / self.rel)
        self.assertEqual(parse_yolo_label(lbl), [polygon])
        self.assertTrue(is_valid_annotation_file(lbl))
        self.assertEqual(self.post('/annotations', path=self.rel, bboxes=[]).status_code, 200)
        self.assertFalse(lbl.exists())

    def test_backslash_lock_matches_forward_slash_save(self):
        self.assertEqual(self.post('/locks/acquire', path=self.rel.replace('/', '\\')).status_code, 200)
        self.assertEqual(self.post('/annotations', role='editor', path=self.rel, bboxes=[self.box]).status_code, 409)

    def test_symlink_escape(self):
        link = self.pd / 'outside'
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlink creation unavailable: {exc}')
        try:
            from app.core.paths import resolve_project_path
            from werkzeug.exceptions import BadRequest
            with self.assertRaises(BadRequest):
                resolve_project_path(self.pd, 'outside/sentinel.txt')
        finally:
            link.unlink()


if __name__ == '__main__':
    unittest.main()
