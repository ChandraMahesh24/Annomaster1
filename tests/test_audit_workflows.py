"""API workflow audit with temporary files/databases; no browser claims."""
from datetime import datetime, timedelta
from unittest.mock import patch

from test_review import ReviewFixture
from app import db
from app.models.user import User
from app.models.image import Image
from app.models.upload_batch import UploadBatch
from app.models.assignment import Assignment
from app.models.annotation_lock import AnnotationLock
from app.models.audit_log import AuditLog
from app.core.password_reset import make_token
from app.core.storage import save_versions, load_versions
import io
import zipfile
import yaml
from pathlib import Path
from app.core.yolo import write_yolo_label
from app.core.storage import save_project_meta


class AuditWorkflows(ReviewFixture):
    def test_reviewed_split_validates_ratios_and_permissions(self):
        self.seed_tracking()
        row=Image.query.filter_by(workspace_id=self.ws.id, project='demo').first()
        row.is_annotated=True
        db.session.commit()
        url=self.base+'/split'
        response=self.request('POST',url,json={'train':0,'val':1,'test':0,'shuffle':False})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()['val'],1)
        self.assertEqual(row.split,'valid')
        media=self.request('GET',self.base+'/media').get_json()['media']
        self.assertTrue(any(item['split']=='valid' for item in media),media)
        self.assertEqual(self.request('POST',url,json={'train':2,'val':0,'test':0}).status_code,400)
        self.assertEqual(self.request('POST',url,role='viewer',json={'train':1,'val':0,'test':0}).status_code,403)

    def test_windows_annotation_path_updates_central_review_state(self):
        self.seed_tracking()
        row=Image.query.filter_by(workspace_id=self.ws.id, project='demo').first()
        row.rel_path=self.rel.replace('/', '\\')
        db.session.commit()
        self.assertEqual(self.post('/annotations',path=self.rel,bboxes=[self.box]).status_code,200)
        self.assertTrue(row.is_annotated)
        self.assertEqual(self.post('/null',path=self.rel).status_code,200)
        self.assertTrue(row.is_null)

    def request(self, method, url, role='owner', **kwargs):
        return self.client.open(url, method=method, headers=self.headers[role], **kwargs)

    def test_registration_logout_login(self):
        payload = dict(username='New Person', email=' New@Example.test ', password='Valid-password-123')
        response = self.client.post('/api/auth/register', json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['user']['email'], 'new@example.test')
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/register', json=payload).status_code, 409)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json=payload).status_code, 200)

    def test_all_protected_api_routes_reject_anonymous_requests(self):
        public = {'auth.register', 'auth.login', 'auth.logout', 'auth.forgot_password',
                  'auth.reset_password', 'auth.reset_password_check'}
        adapter = self.app.url_map.bind('localhost')
        values = dict(workspace_id=self.ws.id, project='demo', user_id=1,
                      uid=1, batch_id=1, assignment_id=1, version_id='missing',
                      dataset_id='missing', model_name='missing.pt')
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith('/api/') or rule.endpoint in public:
                continue
            for method in sorted(rule.methods - {'OPTIONS', 'HEAD'}):
                url = adapter.build(rule.endpoint, {key: values.get(key, 'missing') for key in rule.arguments}, method=method)
                with self.subTest(method=method, route=rule.rule):
                    kwargs = {'json': {'path': self.rel}} if method != 'GET' else {}
                    response = self.client.open(url, method=method, **kwargs)
                    self.assertEqual(response.status_code, 401)

    def test_account_delete_cleans_sole_owner_workspace(self):
        self.seed_tracking()
        response = self.request('DELETE', '/api/auth/delete-account')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(User.query.filter_by(username='owner').first())
        for model in (Image, Assignment, UploadBatch, AnnotationLock):
            self.assertEqual(model.query.filter_by(workspace_id=self.ws.id).count(), 0)

    def test_registration_rejects_invalid_email_and_lengths(self):
        for email, username in [('not-email', 'valid'), ('a@b.test', 'x' * 101)]:
            with self.subTest(email=email, username=username):
                self.assertEqual(self.client.post('/api/auth/register', json={
                    'email': email, 'username': username, 'password': 'Valid-password-123',
                }).status_code, 400)

    def test_profile_update_validation_does_not_partially_commit(self):
        r = self.request('POST', '/api/auth/update-profile', json={'username': 'Renamed', 'email': 'bad-email'})
        self.assertEqual(r.status_code, 400)
        user = User.query.filter_by(email='owner@example.test').one()
        self.assertEqual(user.username, 'owner')
        r = self.request('POST', '/api/auth/update-profile', json={'username': 'Renamed', 'email': 'renamed@example.test', 'bio': 'Test bio'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['user']['username'], 'Renamed')

    def test_password_change_validation_and_login(self):
        for old, new, status in [('wrong', 'Valid-password-123', 401), ('test-password-123', 'short', 400), ('test-password-123', 'New-password-123', 200)]:
            self.assertEqual(self.request('POST', '/api/auth/change-password', json={'current_password': old, 'new_password': new}).status_code, status)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post('/api/auth/login', json={'email': 'owner@example.test', 'password': 'test-password-123'}).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json={'email': 'owner@example.test', 'password': 'New-password-123'}).status_code, 200)

    def test_reset_api_single_use_and_no_enumeration(self):
        self.app.config.update(MAIL_SERVER='smtp.example.test', MAIL_FROM='sender@example.test')
        with patch('app.core.password_reset.send_reset_link') as send:
            a = self.client.post('/api/auth/forgot-password', json={'email': 'owner@example.test'})
            b = self.client.post('/api/auth/forgot-password', json={'email': 'unknown@example.test'})
            self.assertEqual(a.status_code, 200)
            self.assertEqual(a.get_json(), b.get_json())
            send.assert_called_once()
        user = User.query.filter_by(username='owner').one()
        token = make_token(user)
        self.assertTrue(self.client.post('/api/auth/reset-password/check', json={'token': token}).get_json()['valid'])
        self.assertEqual(self.client.post('/api/auth/reset-password', json={'token': token, 'password': 'Reset-password-123'}).status_code, 200)
        self.assertFalse(self.client.post('/api/auth/reset-password/check', json={'token': token}).get_json()['valid'])
        self.assertEqual(self.client.post('/api/auth/reset-password', json={'token': token, 'password': 'Other-password-123'}).status_code, 400)

    def test_reset_without_mail_returns_same_service_error_for_all_addresses(self):
        self.app.config.update(MAIL_SERVER='', MAIL_FROM='', MAIL_USERNAME='')
        with patch('app.core.password_reset.send_reset_link') as send:
            a = self.client.post('/api/auth/forgot-password', json={'email': 'owner@example.test'})
            b = self.client.post('/api/auth/forgot-password', json={'email': 'unknown@example.test'})
        self.assertEqual(a.status_code, 503)
        self.assertEqual(a.get_json(), b.get_json())
        self.assertEqual(a.get_json()['code'], 'mail_not_configured')
        send.assert_not_called()

    def test_workspace_membership_crud_and_owner_guard(self):
        url = f'/api/workspaces/{self.ws.id}'
        outsider = User.query.filter_by(username='outsider').one()
        self.assertEqual(self.request('POST', url + '/invite', json={'email': outsider.email, 'role': 'editor'}).status_code, 201)
        self.assertEqual(self.request('POST', url + '/invite', json={'email': outsider.email, 'role': 'editor'}).status_code, 409)
        self.assertEqual(self.request('PUT', url + f'/members/{outsider.id}/role', json={'role': 'viewer'}).status_code, 200)
        owner = User.query.filter_by(username='owner').one()
        self.assertEqual(self.request('PUT', url + f'/members/{owner.id}/role', json={'role': 'viewer'}).status_code, 400)
        self.assertEqual(self.request('DELETE', url + f'/members/{outsider.id}').status_code, 200)
        self.assertEqual(self.request('GET', url + '/members', role='outsider').status_code, 403)

    def seed_tracking(self, project='demo'):
        user = User.query.filter_by(username='owner').one()
        batch = UploadBatch(workspace_id=self.ws.id, project=project, batch_name='Audit')
        db.session.add(batch)
        db.session.flush()
        db.session.add(Image(workspace_id=self.ws.id, project=project, batch_id=batch.id, filename='frame.jpg', rel_path=self.rel))
        db.session.add(Assignment(workspace_id=self.ws.id, project=project, batch_id=batch.id, assigned_to=user.id))
        db.session.add(AnnotationLock(workspace_id=self.ws.id, project=project, image_path=self.rel, locked_by=user.id, expires_at=datetime.utcnow() + timedelta(minutes=1)))
        db.session.add(AuditLog(workspace_id=self.ws.id, project=project, user_id=user.id, action='audit.fixture'))
        db.session.commit()

    def test_project_delete_clears_tracking_and_preserves_other_project(self):
        self.seed_tracking()
        self.seed_tracking('other')
        self.assertEqual(self.request('DELETE', self.base, role='editor').status_code, 403)
        self.assertEqual(self.request('DELETE', self.base).status_code, 200)
        for model in (Image, Assignment, UploadBatch, AnnotationLock):
            self.assertEqual(model.query.filter_by(workspace_id=self.ws.id, project='demo').count(), 0, model.__name__)
            self.assertEqual(model.query.filter_by(workspace_id=self.ws.id, project='other').count(), 1, model.__name__)
        self.assertFalse(self.pd.exists())
        self.assertEqual(self.request('POST', f'/api/workspaces/{self.ws.id}/projects', json={'name': 'demo'}).status_code, 201)
        self.assertEqual(Image.query.filter_by(workspace_id=self.ws.id, project='demo').count(), 0)

    def test_project_delete_filesystem_failure_keeps_tracking(self):
        self.seed_tracking()
        from app.core.projects import ProjectOpError
        with patch('app.api.projects.delete_project', side_effect=ProjectOpError('file busy')):
            self.assertEqual(self.request('DELETE', self.base).status_code, 400)
        self.assertEqual(Image.query.filter_by(workspace_id=self.ws.id, project='demo').count(), 1)

    def test_workspace_delete_clears_tracking(self):
        self.seed_tracking()
        self.assertEqual(self.request('DELETE', f'/api/workspaces/{self.ws.id}').status_code, 200)
        for model in (Image, Assignment, UploadBatch, AnnotationLock):
            self.assertEqual(model.query.filter_by(workspace_id=self.ws.id).count(), 0, model.__name__)

    def test_every_registered_page_http_and_assets(self):
        for url in ('/login', '/register', '/forgot-password', '/forgot-password?token=invalid', '/', '/settings', '/pages/upload',
                    '/pages/annotate?workspace_id=1&project=demo', f'/workspace/{self.ws.id}/members'):
            with self.subTest(page=url):
                self.assertEqual(self.request('GET', url, follow_redirects=True).status_code, 200)
        from html.parser import HTMLParser
        class Assets(HTMLParser):
            def __init__(self):
                super().__init__()
                self.paths = []
            def handle_starttag(self, tag, attrs):
                data = dict(attrs)
                for key in ('src', 'href'):
                    if data.get(key, '').startswith('/static/'):
                        self.paths.append(data[key])
        for path in self.app.jinja_env.list_templates():
            parser = Assets()
            parser.feed(self.app.jinja_env.get_template(path).render(token=''))
            for asset in parser.paths:
                response = self.client.get(asset)
                self.assertEqual(response.status_code, 200, (path, asset))
                response.close()

    def test_version_build_failure_does_not_publish_success(self):
        with patch('app.core.versions._build_version_folder', side_effect=OSError('disk full')):
            response = self.post('/versions', name='test')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(load_versions('WS-TEST', 'demo'), [])

    def test_missing_version_folder_never_downloads_working_directory(self):
        from app.core.versions import download_version_zip
        sentinel = self.root / 'outside-sentinel.txt'
        sentinel.write_text('must survive', encoding='utf-8')
        for folder_path in ('', str(self.root), str(self.root / 'missing')):
            with self.subTest(folder_path=folder_path):
                save_versions('WS-TEST', 'demo', [{'id': 'broken', 'name': 'Broken', 'folder_path': folder_path}])
                # Safety: prevent filesystem enumeration even on the unfixed code.
                with patch('app.core.versions.Path.rglob', return_value=[]) as scan:
                    self.assertIsNone(download_version_zip('WS-TEST', 'demo', 'broken'))
                    scan.assert_not_called()
                info = self.request('GET', self.base + '/versions/broken/info')
                self.assertFalse(info.get_json()['exists'])
                self.assertEqual(self.request('GET', self.base + '/versions/broken/download').status_code, 404)
                # Never allow an unsafe deletion even if this regresses.
                with patch('shutil.rmtree') as remove:
                    response = self.client.delete(self.base + '/versions', headers=self.headers['owner'], json={'id': 'broken'})
                    self.assertEqual(response.status_code, 200)
                    remove.assert_not_called()
                self.assertTrue(sentinel.exists())

    def test_invalid_version_split_returns_client_error(self):
        for ratios in ({'train': 2, 'val': .2}, {'train': .8, 'val': .8}, {'train': 'wrong'}, {'train': float('nan')}):
            with self.subTest(ratios=ratios):
                self.assertEqual(self.post('/versions', name='Bad split', split_ratio=ratios).status_code, 400)

    def test_auth_links_and_claims_are_honest(self):
        for route in ('/login', '/register', '/forgot-password'):
            html = self.client.get(route).get_data(as_text=True)
            self.assertNotIn('href="#"', html)
            self.assertNotIn('socialLogin(', html)
            self.assertNotIn('SOC 2 Type II', html)
            self.assertNotIn('Keep me signed in for 30 days', html)
        self.assertEqual(self.client.get('/help').status_code, 200)

    def test_real_image_upload_annotate_dataset_version_download(self):
        from PIL import Image as PILImage
        image = io.BytesIO()
        PILImage.new('RGB', (32, 24), 'green').save(image, format='PNG')
        image.seek(0)
        response = self.client.post(self.base + '/upload', headers=self.headers['owner'],
                                    data={'file': (image, 'sample.png')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        batch = response.get_json()
        row = Image.query.filter_by(workspace_id=self.ws.id, filename='sample.png').one()
        save_project_meta('WS-TEST', 'demo', {'name': 'demo', 'classes': [{'id': 0, 'name': 'object', 'color': '#22c55e'}]})
        self.assertEqual(self.post('/annotations', path=row.rel_path, bboxes=[self.box]).status_code, 200)
        r = self.post(f"/uploads/{batch['upload_id']}/add_to_dataset", train=1, val=0, test=0)
        self.assertEqual(r.status_code, 200)
        db.session.refresh(row)
        self.assertEqual(row.status, 'in_dataset')
        version = self.post('/versions', name='Real snapshot', split_ratio={'train': 1, 'val': 0, 'test': 0, 'shuffle': False})
        self.assertEqual(version.status_code, 200)
        record = version.get_json()['version']
        self.assertEqual(record['total_images'], 1)
        response = self.request('GET', self.base + f"/versions/{record['id']}/download")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            paths = archive.namelist()
            self.assertEqual(sum(p.endswith('/images/sample.png') for p in paths), 1)
            self.assertEqual(sum(p.endswith('/labels/sample.txt') for p in paths), 1)
            self.assertFalse(any(p.endswith('.suggestions.json') for p in paths))
        response.close()

    def test_stats_class_counts_carry_class_id(self):
        """The Classes page keys counts by class id; without 'id' every class read 0."""
        from PIL import Image as PILImage
        image = io.BytesIO()
        PILImage.new('RGB', (32, 24), 'green').save(image, format='PNG')
        image.seek(0)
        response = self.client.post(self.base + '/upload', headers=self.headers['owner'],
                                    data={'file': (image, 'counted.png')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        row = Image.query.filter_by(workspace_id=self.ws.id, filename='counted.png').one()
        save_project_meta('WS-TEST', 'demo', {'name': 'demo', 'classes': [
            {'id': 0, 'name': 'object', 'color': [34, 197, 94]}, {'id': 3, 'name': 'sparse', 'color': [1, 2, 3]}]})
        self.assertEqual(self.post('/annotations', path=row.rel_path, bboxes=[self.box, self.box]).status_code, 200)
        stats = self.request('GET', self.base + '/stats').get_json()
        by_id = {c['id']: c for c in stats['class_counts']}
        self.assertEqual(set(by_id), {0, 3})
        self.assertEqual((by_id[0]['count'], by_id[0]['images']), (2, 1))
        self.assertEqual((by_id[3]['count'], by_id[3]['images']), (0, 0))
        self.assertEqual(stats['labelled_images'], 1)   # images with >= 1 box
        self.assertEqual(stats['total_boxes'], 2)

    def test_dataset_background_and_validation_split_filters(self):
        legacy = self.pd / 'Completed_Datasets/job_filters/valid'
        (legacy / 'images').mkdir(parents=True)
        (legacy / 'labels').mkdir()
        (legacy / 'images/background.jpg').write_bytes(b'fixture')
        (legacy / 'labels/background.txt').write_text('')
        (legacy / 'images/labeled.jpg').write_bytes(b'fixture')
        write_yolo_label(legacy / 'labels/labeled.txt', [self.box])
        response = self.request('GET', self.base + '/datasets/images?class_id=__null__')
        self.assertEqual([i['name'] for i in response.get_json()['items']], ['background.jpg'])
        for split in ('val', 'valid'):
            response = self.request('GET', self.base + '/datasets/images?split=' + split)
            self.assertEqual(response.get_json()['pagination']['total'], 2)

    def test_export_preserves_sparse_ids_and_excludes_suggestions(self):
        save_project_meta('WS-TEST', 'demo', {'name': 'demo', 'classes': [{'id': 2, 'name': 'object', 'color': '#22c55e'}]})
        legacy = self.pd / 'Completed_Datasets/job_legacy/train'
        (legacy / 'images').mkdir(parents=True)
        (legacy / 'labels').mkdir()
        (legacy / 'images/frame.jpg').write_bytes(b'fixture image')
        write_yolo_label(legacy / 'labels/frame.txt', [dict(self.box, class_id=2)])
        (legacy / 'labels/frame.suggestions.json').write_text('{"private":"not ground truth"}')
        response = self.post('/export')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertFalse(any(p.endswith('.suggestions.json') for p in archive.namelist()))
            names = yaml.safe_load(archive.read('data.yaml'))['names']
            self.assertEqual(names[2], 'object')
            self.assertIn('train/images/frame.jpg', archive.namelist())
            self.assertIn('train/labels/frame.txt', archive.namelist())
        response.close()

    def test_batch_media_reports_explicit_null_images(self):
        from app.core.storage import save_uploads
        save_uploads('WS-TEST', 'demo', [{'upload_id': 1, 'job_name': 'job_test'}])
        self.assertEqual(self.post('/null', path=self.rel).status_code, 200)
        response = self.request('GET', self.base + '/uploads/1/media')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.replace('\\', '/') for p in response.get_json()['null_paths']], [self.rel])
        self.assertEqual(response.get_json()['annotated'], [])

    def test_export_specific_dataset_excludes_other_datasets(self):
        for dataset in ('first', 'second'):
            root = self.pd / 'Completed_Datasets' / dataset / 'train'
            (root / 'images').mkdir(parents=True)
            (root / 'images' / (dataset+'.jpg')).write_bytes(b'image fixture')
            write_yolo_label(root / 'labels' / (dataset+'.txt'), [self.box])
        response = self.post('/export', dataset_id='first')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertIn('train/images/first.jpg', archive.namelist())
            self.assertNotIn('train/images/second.jpg', archive.namelist())
        response.close()

    def test_retained_duplicate_uploads_exist_in_both_indexes(self):
        from PIL import Image as PILImage
        image = io.BytesIO()
        PILImage.new('RGB', (32,24), 'orange').save(image,format='PNG')
        payload = image.getvalue()
        for name in ('same-first.png', 'same-second.png'):
            response = self.client.post(self.base+'/upload', headers=self.headers['owner'],
                data={'file': (io.BytesIO(payload),name)},content_type='multipart/form-data')
            self.assertEqual(response.status_code,200)
        rows = Image.query.filter_by(workspace_id=self.ws.id,project='demo').all()
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r.rel_path for r in rows}),2)
        from app.core.db_index import get_media_page
        indexed = get_media_page(self.pd,1,50)['media']
        self.assertEqual({m['name'] for m in indexed},{'same-first.png','same-second.png'})
