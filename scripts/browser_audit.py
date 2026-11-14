"""Real Chromium/Chrome audit against a disposable app; artifacts in .audit-browser.

python scripts/browser_audit.py [probe|auth|dashboard|project|settings|members|ai|media]
Requires playwright (workspace .audit-tools is supported) and installed Chrome.
"""
import json
import re
import sys
import time
import subprocess
import os
import shutil
import urllib.request
from pathlib import Path
sys.stdout.reconfigure(errors='backslashreplace')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.audit-tools'))
from playwright.sync_api import sync_playwright, expect

OUT = ROOT / '.audit-browser'
BASE = 'http://127.0.0.1:5055'
RESULTS = []
EVENTS = []


class BlockedTest(Exception):
    pass


def record(name, action, page):
    try:
        result = action()
        RESULTS.append(dict(name=name, status='PASS', detail=result))
        print('PASS '+name,flush=True)
    except BlockedTest as exc:
        RESULTS.append(dict(name=name,status='BLOCKED',error=str(exc)))
        print('BLOCKED '+name+': '+str(exc),flush=True)
    except Exception as exc:
        RESULTS.append(dict(name=name, status='FAIL', error=str(exc)))
        print('FAIL '+name+': '+str(exc)[:180],flush=True)
        page.screenshot(path=str(OUT / (name.replace('/', '_') + '-failure.png')), full_page=True)
        # Do not let an open failed-test modal block unrelated later cases.
        close = page.locator('.modal-overlay:visible .modal-close, .modal-overlay:visible .modal-x')
        if close.count():
            close.first.click(timeout=1000)


def watch(page):
    page.on('pageerror', lambda err: EVENTS.append(dict(type='pageerror', url=page.url, error=str(err))))
    page.on('console', lambda msg: EVENTS.append(dict(type='console', url=page.url, level=msg.type, message=msg.text)) if msg.type in ('error', 'warning') else None)
    page.on('requestfailed', lambda req: EVENTS.append(dict(type='requestfailed', url=req.url, error=req.failure)))
    page.on('response', lambda resp: EVENTS.append(dict(type='http', url=resp.url, method=resp.request.method,status=resp.status)) if resp.status >= 400 or '/api/' in resp.url else None)


def ui_confirm(page):
    """Accept the shared themed confirmation dialog (UI.confirm in core/ui.js),
    which replaced native confirm() on Dashboard, Members and Settings."""
    dialog = page.locator('[role="alertdialog"]')
    expect(dialog).to_be_visible()
    dialog.locator('.modal-footer .btn').last.click()
    expect(dialog).to_have_count(0)


def login(page):
    page.goto(BASE + '/login')
    page.locator('#email').fill('audit@example.test')
    page.locator('#password').fill('Audit-only-123!')
    page.locator('#submit-btn').click()
    page.wait_for_url(BASE + '/')
    expect(page.locator('#ws-title')).to_have_text('Audit Workspace')


def probe(page):
    routes = [('/login','login'),('/register','register'),('/forgot-password','forgot'),
              ('/forgot-password?token=invalid','reset-invalid'),('/help','help'),('/health','health')]
    for route, name in routes:
        record(name + '-render', lambda route=route: {'status':page.goto(BASE+route).status}, page)
        for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
            page.set_viewport_size(dict(width=width,height=height))
            page.screenshot(path=str(OUT/f'{name}-{device}.png'),full_page=True)
            RESULTS.append(dict(name=f'{name}-{device}-layout',status='PASS' if page.evaluate('document.documentElement.scrollWidth<=innerWidth') else 'FAIL'))
    page.set_viewport_size(dict(width=1440,height=900))
    login(page)
    routes = [('/', 'dashboard'),('/pages/upload?workspace_id=1&project=audit-project','legacy-upload'),
              ('/settings','settings'),('/workspace/1/members','members')]
    routes += [(f'/pages/annotate?workspace_id=1&project=audit-project#{section}',section)
               for section in ('projects','upload','annotate','dataset','versions','classes')]
    for route, name in routes:
        for width, height, device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
            page.set_viewport_size(dict(width=width,height=height))
            page.goto(BASE+route)
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT/f'{name}-{device}.png'), full_page=True)
            info = page.evaluate('''() => ({title:document.title,url:location.href,
                width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
                controls:[...document.querySelectorAll('button,a,input,select,textarea,[role="button"],[onclick]')]
                .filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')
                .map(e=>({tag:e.tagName,id:e.id,text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('title')||'').trim().slice(0,100),href:e.getAttribute('href'),type:e.getAttribute('type'),disabled:e.disabled}))})''')
            RESULTS.append(dict(name=f'{name}-{device}-probe',status='OBSERVED',detail=info))
            if '/pages/annotate' in route:
                expected = route.split('#')[-1] if '#' in route else 'upload'
                record(f'{name}-{device}-active-section',lambda expected=expected: expect(page.locator('#page-'+expected)).to_have_class('page active'),page)
                def footer_scope():
                    footer=page.locator('.status-bar')
                    if expected=='annotate':
                        expect(footer).to_be_visible()
                    else:
                        expect(footer).to_be_hidden()
                        rect=page.locator('#page-'+expected).bounding_box()
                        assert abs(rect['y']+rect['height']-height)<=1,rect
                record(f'{name}-{device}-annotation-footer-scope',footer_scope,page)
            if name=='annotate':
                def canvas_fit():
                    rect=page.locator('#canvasArea').bounding_box()
                    assert rect['width']>=200 and rect['x']+rect['width']<=width+1,rect
                    card=page.locator('#canvasEmpty .empty-card').bounding_box()
                    assert card['x']>=rect['x'] and card['x']+card['width']<=width+1,card
                    groups=[page.locator('.ah-'+name).bounding_box() for name in ('left','center','right')]
                    for a,b in zip(groups,groups[1:]):
                        assert a['y']+a['height']<=b['y']+1 or a['x']+a['width']<=b['x']+1,(a,b)
                    for selector in ('#helpBtn','#statsBtn','#settingsBtn','#exportBtn','#user-menu'):
                        box=page.locator(selector).bounding_box()
                        assert box and box['x']>=0 and box['x']+box['width']<=width+1,(selector,box)
                record(f'annotate-{device}-canvas-accessible',canvas_fit,page)


def auth(page):
    page.goto(BASE+'/login')
    def empty():
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('fill in')
    record('login-empty-submit',empty,page)
    def visibility():
        page.locator('#password').fill('not-a-real-password')
        page.locator('#pw-toggle').click()
        expect(page.locator('#password')).to_have_attribute('type','text')
        page.locator('#pw-toggle').click()
        expect(page.locator('#password')).to_have_attribute('type','password')
    record('login-password-show-hide',visibility,page)
    def theme():
        before = page.locator('html').get_attribute('class') or ''
        page.locator('#theme-btn').click()
        assert (page.locator('html').get_attribute('class') or '') != before
        page.reload()
        assert (page.locator('html').get_attribute('class') or '') != before
    record('login-theme-persistence',theme,page)
    def scene():
        before = page.locator('#mode-btn').inner_text()
        page.locator('#mode-btn').click()
        expect(page.locator('#mode-btn')).not_to_have_text(before)
    record('login-scene-selection',scene,page)
    def invalid():
        page.locator('#email').fill('audit@example.test')
        page.locator('#password').fill('wrong-password')
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('Invalid email or password')
        expect(page.locator('#submit-btn')).to_be_enabled()
    record('login-invalid-credentials',invalid,page)
    def offline():
        page.context.set_offline(True)
        try:
            page.locator('#submit-btn').click()
            expect(page.locator('#err')).to_contain_text('Network error')
            expect(page.locator('#submit-btn')).to_be_enabled()
        finally:
            page.context.set_offline(False)
    record('login-network-failure-recovery',offline,page)
    record('login-success-real-dashboard',lambda:login(page),page)
    # Each link is clicked, not merely fetched.
    for href in ('/forgot-password','/register','/help#data','/help#usage','/health','/'):
        def link(href=href):
            page.goto(BASE+'/login')
            page.locator('a[href="'+href+'"]').first.click()
            page.wait_for_url(BASE+href)
        record('login-link-'+href.replace('/','_'),link,page)
    page.goto(BASE+'/register')
    def register_validation():
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('required')
        page.locator('#username').fill('x')
        page.locator('#email').fill('bad-email')
        page.locator('#password').fill('short')
        page.locator('#confirm').fill('different')
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('valid email')
        page.locator('#email').fill('new-browser@example.test')
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('2 characters')
        page.locator('#username').fill('Browser User')
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('8 characters')
        page.locator('#password').fill('Browser-password-123!')
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('do not match')
        page.locator('#pw-toggle').click()
        expect(page.locator('#confirm')).to_have_attribute('type','text')
        page.locator('#pw-toggle').click()
        expect(page.locator('#pw-hint')).to_have_text('Strong')
    record('register-validation-strength-toggle',register_validation,page)
    def register_success():
        page.locator('#confirm').fill('Browser-password-123!')
        page.locator('#submit-btn').click()
        page.wait_for_url(BASE+'/')
        expect(page.locator('#no-workspace-state')).to_be_visible()
    record('register-success-empty-workspace',register_success,page)
    page.goto(BASE+'/register')
    def duplicate():
        for id,value in dict(username='Browser User',email='new-browser@example.test',password='Browser-password-123!',confirm='Browser-password-123!').items():
            page.locator('#'+id).fill(value)
        page.locator('#submit-btn').click()
        expect(page.locator('#err')).to_contain_text('already registered')
    record('register-duplicate-error',duplicate,page)
    page.goto(BASE+'/forgot-password')
    def forgot():
        page.locator('#request-btn').click()
        expect(page.locator('#request-err')).to_contain_text('valid email')
        page.locator('#email').fill('unknown@example.test')
        page.locator('#request-btn').click()
        expect(page.locator('#request-err')).to_contain_text('administrator must configure')
        expect(page.locator('#view-sent')).to_be_hidden()
        expect(page.locator('#request-btn')).to_be_enabled()
        expect(page.locator('#view-request')).to_be_visible()
    record('forgot-validation-unconfigured-mail-honest-error',forgot,page)
    page.goto(BASE+'/forgot-password?token=invalid')
    def bad_reset():
        expect(page.locator('#view-invalid')).to_be_visible()
        page.get_by_role('button',name='Request a new link').click()
        page.wait_for_url(BASE+'/forgot-password')
        expect(page.locator('#view-request')).to_be_visible()
    record('reset-invalid-link-recovery',bad_reset,page)
    token = json.loads((OUT/'fixtures.json').read_text())['reset_token']
    page.goto(BASE+'/forgot-password?token='+token)
    def reset():
        expect(page.locator('#view-reset')).to_be_visible()
        page.locator('#password').fill('short')
        page.locator('#reset-btn').click()
        expect(page.locator('#reset-err')).to_contain_text('8 characters')
        page.locator('#password').fill('Changed-audit-123!')
        page.locator('#confirm').fill('wrong')
        page.locator('#reset-btn').click()
        expect(page.locator('#reset-err')).to_contain_text('do not match')
        page.locator('#confirm').fill('Changed-audit-123!')
        page.locator('#pw-toggle').click()
        expect(page.locator('#confirm')).to_have_attribute('type','text')
        page.locator('#reset-btn').click()
        expect(page.locator('#view-done')).to_be_visible()
        page.locator('#view-done').get_by_role('button').click()
        page.wait_for_url(BASE+'/login')
        page.locator('#email').fill('audit@example.test')
        page.locator('#password').fill('Changed-audit-123!')
        page.locator('#submit-btn').click()
        page.wait_for_url(BASE+'/')
        page.goto(BASE+'/forgot-password?token='+token)
        expect(page.locator('#view-invalid')).to_be_visible()
    record('reset-valid-password-change-login-single-use',reset,page)


def dashboard(page):
    login(page)
    def search_views_sort():
        page.locator('#project-search').fill('not-found-unique')
        expect(page.locator('#pcard-audit-project')).to_have_count(0)
        page.locator('#project-search').fill('audit')
        expect(page.locator('#pcard-audit-project')).to_be_visible()
        page.locator('#project-search').fill('')
        for view in ('list','grid'):
            page.locator('#view-'+view).click()
            expect(page.locator('#view-'+view)).to_have_class('active')
        for text in ('Name','Progress','Recent'):
            page.locator('.sort-btn').click()
            page.locator('#sort-menu').get_by_role('button',name=text,exact=True).click()
            expect(page.locator('#sort-label')).to_have_text(text)
    record('dashboard-search-sort-view-controls',search_views_sort,page)
    def new_workspace():
        page.locator('button[title="New workspace"]').click()
        modal=page.locator('#modal-create-workspace')
        modal.get_by_role('button',name='Create',exact=True).click()
        expect(page.locator('#ws-create-error')).to_contain_text('required')
        page.locator('#ws-name-input').fill('Browser Workspace')
        page.locator('#ws-name-input').press('Enter')
        expect(page.locator('#ws-title')).to_have_text('Browser Workspace')
        page.locator('#btn-rename-workspace').click()
        page.locator('#ws-rename-input').fill('Renamed Workspace')
        page.locator('#modal-rename-workspace').get_by_role('button',name='Save',exact=True).click()
        expect(page.locator('#ws-title')).to_have_text('Renamed Workspace')
        page.locator('.workspace-item').filter(has_text='Audit Workspace').click()
        expect(page.locator('#ws-title')).to_have_text('Audit Workspace')
    record('dashboard-workspace-create-rename-switch',new_workspace,page)
    def new_project():
        page.locator('#btn-new-project').click()
        modal=page.locator('#modal-create-project')
        modal.get_by_role('button',name='Create Project',exact=True).click()
        expect(page.locator('#project-create-error')).to_contain_text('required')
        page.locator('#project-name-input').fill('browser-project')
        modal.get_by_role('button',name='Create Project',exact=True).click()
        expect(page.locator('#pcard-browser-project')).to_be_visible()
    record('dashboard-project-create-validation',new_project,page)
    def menu(project,label):
        page.locator('#pcard-'+project+' .pc-menu-btn').click()
        page.locator('.kmenu-item').filter(has_text=label).click()
    def rename_duplicate():
        menu('browser-project','Rename…')
        page.locator('#proj-rename-input').fill('browser-renamed')
        page.locator('#modal-rename-project').get_by_role('button',name='Rename',exact=True).click()
        expect(page.locator('#pcard-browser-renamed')).to_be_visible()
        menu('browser-renamed','Duplicate…')
        page.locator('#proj-duplicate-input').fill('browser-copy')
        page.locator('#modal-duplicate-project').get_by_role('button',name='Duplicate',exact=True).click()
        expect(page.locator('#pcard-browser-copy')).to_be_visible()
    record('dashboard-project-menu-rename-duplicate',rename_duplicate,page)
    def share():
        page.locator('#btn-share-workspace').click()
        expect(page.locator('#share-panel')).to_be_visible()
        page.locator('#share-email-input').fill('missing@example.test')
        page.locator('#share-role-select').select_option('viewer')
        page.locator('#share-invite-btn').click()
        expect(page.locator('#share-invite-error')).to_contain_text('No user')
        page.locator('#btn-share-workspace').click()
    record('dashboard-share-panel-validation',share,page)
    def merge():
        menu('browser-copy','Merge into…')
        page.locator('#proj-merge-target').select_option('browser-renamed')
        page.locator('button[onclick="ProjectsFeature.submitMerge()"]').click()
        ui_confirm(page)
        expect(page.locator('#pcard-browser-copy')).to_have_count(0)
        expect(page.locator('#pcard-browser-renamed')).to_be_visible()
    record('dashboard-project-merge',merge,page)
    def move():
        menu('browser-renamed','Move to workspace…')
        page.locator('#proj-move-target').select_option(label='Renamed Workspace')
        page.locator('#modal-move-project').get_by_role('button',name='Move',exact=True).click()
        expect(page.locator('#pcard-browser-renamed')).to_have_count(0)
        page.locator('.workspace-item').filter(has_text='Renamed Workspace').click()
        expect(page.locator('#pcard-browser-renamed')).to_be_visible()
    record('dashboard-project-move-workspace',move,page)
    def delete():
        menu('browser-renamed','Delete project')
        ui_confirm(page)
        expect(page.locator('#pcard-browser-renamed')).to_have_count(0)
        page.locator('.workspace-item').filter(has_text='Renamed Workspace').locator('button').click()
        ui_confirm(page)
        expect(page.locator('#ws-title')).to_have_text('Audit Workspace')
    record('dashboard-project-workspace-delete',delete,page)
    def links():
        page.locator('.rail-nav a[href="/settings"]').click()
        page.wait_for_url(BASE+'/settings')
        page.locator('#nav-brand-link').click()
        page.wait_for_url(BASE+'/')
        page.locator('#pcard-audit-project').click()
        page.wait_for_url('**/pages/annotate?**')
    record('dashboard-settings-brand-project-navigation',links,page)


def settings(page):
    login(page)
    page.goto(BASE+'/settings')
    for tab in ('profile','theme','workspace','security','notifications','language','layout','danger'):
        def tabtest(tab=tab):
            page.locator('#nav-btn-'+tab).click()
            expect(page.locator('#panel-'+tab)).to_be_visible()
            page.screenshot(path=str(OUT/f'settings-{tab}-desktop.png'),full_page=True)
            RESULTS.append(dict(name='settings-'+tab+'-controls',status='OBSERVED',detail=page.locator('#panel-'+tab).evaluate('''e=>[...e.querySelectorAll('button,input,select,textarea,[onclick]')].filter(c=>c.getClientRects().length).map(c=>({tag:c.tagName,id:c.id,text:(c.innerText||c.title||'').trim().slice(0,90),type:c.type,onclick:c.getAttribute('onclick')}))''')))
        record('settings-tab-'+tab,tabtest,page)
    def profile():
        page.locator('#nav-btn-profile').click()
        page.locator('#profile-username').fill('Browser Owner')
        page.locator('#profile-bio').fill('Browser tested bio')
        page.locator('#profile-phone').fill('123456789')
        page.locator('#btn-save-profile').click()
        page.reload()
        expect(page.locator('#profile-username')).to_have_value('Browser Owner')
        expect(page.locator('#profile-bio')).to_have_value('Browser tested bio')
        expect(page.locator('#profile-phone')).to_have_value('123456789')
    record('settings-profile-save-reload',profile,page)
    def password_minimum():
        page.locator('#nav-btn-security').click()
        expect(page.locator('#security-new-pw')).to_have_attribute('placeholder','Min. 8 characters')
    record('settings-password-hint-matches-backend',password_minimum,page)
    def fake2fa():
        page.locator('#nav-btn-security').click()
        control=page.locator('#twofa-switch')
        if control.count() and control.is_enabled():
            page.locator('label.switch').filter(has=control).click()
            page.locator('#twofa-code-input').fill('123456')
            page.get_by_role('button',name='Verify & Enable').click()
            expect(page.locator('#twofa-status-badge')).not_to_have_text('Active')
        else:
            expect(page.locator('#panel-security')).to_contain_text('not available')
    record('settings-no-fake-two-factor-protection',fake2fa,page)
    def fake_sessions():
        expect(page.locator('#sessions-list')).not_to_contain_text('London, United Kingdom')
        expect(page.locator('#sessions-list')).not_to_contain_text('San Francisco')
    record('settings-no-fabricated-sessions',fake_sessions,page)
    def avatars():
        page.locator('#nav-btn-profile').click()
        for title in ('Astronaut','Detective','Coder','Robot','Cat'):
            button=page.locator('button[title="'+title+'"]')
            value=button.inner_text()
            button.click()
            expect(page.locator('#profile-avatar-display')).to_have_text(value)
        page.locator('button[title="Reset to initials"]').click()
        expect(page.locator('#profile-avatar-display')).to_have_text('B')
    record('settings-all-avatar-presets-reset',avatars,page)
    def theme_controls():
        page.locator('#nav-btn-theme').click()
        for mode in ('light','dark','custom'):
            page.locator('#theme-mode-'+mode).click()
            assert page.evaluate("localStorage.getItem('am_theme_mode')")==mode
        for title,color in [('Classic Teal','#00e5b0'),('Electric Violet','#9b51e0'),('Neon Pink','#ff4081'),('Amber Gold','#ffb020'),('Sapphire Blue','#2d9cdb'),('Sunset Crimson','#eb5757')]:
            page.locator('button[title="'+title+'"]').click()
            assert page.evaluate("localStorage.getItem('am_accent_color')")==color
        for id in ('custom-theme-bg','custom-theme-text','custom-accent-picker','card-custom-bg','card-custom-tx','card-custom-border'):
            page.locator('#'+id).evaluate("e=>{e.value='#556677';e.dispatchEvent(new Event('change',{bubbles:true}));}")
        for id,key in [('card-custom-radius','am_card_radius'),('card-custom-shadow','am_card_shadow'),('card-custom-padding','am_card_padding'),('card-custom-hover','am_card_hover')]:
            options=page.locator('#'+id+' option').evaluate_all('es=>es.map(e=>e.value)')
            for value in options:
                page.locator('#'+id).select_option(value)
                assert page.evaluate('(key)=>localStorage.getItem(key)',key)==value
        page.locator('#card-custom-opacity').press('Home')
        page.locator('#card-custom-opacity').press('ArrowRight')
        expect(page.locator('#card-custom-opacity-val')).to_have_text('25%')
        page.locator('#btn-save-theme').click()
        page.reload()
        page.locator('#nav-btn-theme').click()
        expect(page.locator('#card-custom-opacity')).to_have_value('0.25')
        page.locator('button[onclick="SettingsPage.restoreThemeDefaults()"]').click()
        # Previously a native confirm() that Playwright auto-DISMISSED, so the
        # reset never ran. The themed UI.confirm is accepted and verified.
        ui_confirm(page)
        expect(page.locator('#card-custom-opacity')).to_have_value('1')
    record('settings-theme-modes-presets-colors-every-select-option-save-reset',theme_controls,page)
    def preferences():
        page.locator('#nav-btn-notifications').click()
        for id in ('notif-email-digest','notif-email-shared','notif-push-export','notif-push-server'):
            control=page.locator('#'+id)
            old=control.is_checked()
            page.locator('label').filter(has=control).click()
            assert control.is_checked()!=old
        saved=page.evaluate("localStorage.getItem('am_notif_1')")
        assert saved
        page.locator('#nav-btn-language').click()
        for value in page.locator('#language-select option').evaluate_all('es=>es.map(e=>e.value)'):
            page.locator('#language-select').select_option(value)
            assert page.evaluate("localStorage.getItem('am_language_1')")==value
        page.locator('#language-select').select_option('en')
        page.locator('#nav-btn-layout').click()
        for mode in ('compact','expanded'):
            page.locator('#layout-mode-'+mode).click()
            assert page.evaluate("localStorage.getItem('am_layout_mode')")==mode
        page.reload()
        assert page.evaluate("localStorage.getItem('am_notif_1')")==saved
    record('settings-notification-language-layout-preferences',preferences,page)
    def password_validation():
        page.locator('#nav-btn-security').click()
        btn=page.locator('button[onclick="SettingsPage.changePassword()"]')
        btn.click()
        expect(page.locator('#security-pw-error')).to_contain_text('Fill in')
        for id,value in [('security-current-pw','wrong-password'),('security-new-pw','short'),('security-confirm-pw','short')]:
            page.locator('#'+id).fill(value)
        btn.click()
        expect(page.locator('#security-pw-error')).to_contain_text('8 characters')
        page.locator('#security-new-pw').fill('Valid-new-password-123!')
        page.locator('#security-confirm-pw').fill('Mismatch')
        btn.click()
        expect(page.locator('#security-pw-error')).to_contain_text('do not match')
        page.locator('#security-confirm-pw').fill('Valid-new-password-123!')
        btn.click()
        expect(page.locator('#security-pw-error')).to_contain_text('incorrect')
    record('settings-password-required-length-confirmation-current-check',password_validation,page)
    def workspace():
        page.locator('#nav-btn-workspace').click()
        expect(page.locator('#ws-picker')).to_have_value('1')
        page.locator('#ws-rename-input').fill('Settings Workspace')
        page.locator('button[onclick="SettingsPage.renameWorkspace()"]').click()
        expect(page.locator('#ws-picker')).to_contain_text('Settings Workspace')
        page.locator('#ws-invite-email').fill('missing@example.test')
        page.locator('#ws-invite-role').select_option('viewer')
        page.locator('button[onclick="SettingsPage.inviteMember()"]').click()
        expect(page.locator('#panel-workspace')).to_contain_text('No user')
    record('settings-workspace-picker-rename-invite-validation',workspace,page)
    def reset_signout():
        page.locator('#nav-btn-danger').click()
        page.locator('button[onclick="SettingsPage.restoreSystemDefaults()"]').click()
        ui_confirm(page)
        assert (page.evaluate("localStorage.getItem('am_theme_mode')") or 'dark')=='dark'
        page.locator('#nav-btn-security').click()
        page.get_by_role('button',name='Sign out this browser').click()
        page.wait_for_url(BASE+'/login')
        page.goto(BASE+'/settings')
        page.wait_for_url(BASE+'/login')
    record('settings-restore-defaults-real-browser-signout',reset_signout,page)


def project(page):
    from PIL import Image
    login(page)
    url=BASE+'/pages/annotate?workspace_id=1&project=audit-project'
    page.goto(url+'#upload')
    def navigation():
        for id,section in [('rnProjects','projects'),('rnUpload','upload'),('rnAnnotate','annotate'),('rnDataset','dataset'),('rnVersions','versions'),('rnClasses','classes')]:
            page.locator('#'+id).click()
            expect(page.locator('#page-'+section)).to_be_visible()
            assert page.url.endswith('#'+section)
        page.locator('#rnToggleBtn').click()
        page.locator('#rnToggleBtn').click()
    record('project-all-six-section-navigation',navigation,page)
    def classes():
        page.locator('#clsPageName').fill('vehicle')
        page.locator('#clsPageColor').evaluate("e=>{e.value='#3366cc';e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}")
        page.locator('#clsPageAddBtn').click()
        # rename popup (Classes page): click the name, popup shows the old name
        page.locator('#clsPageTableBody .cls-name', has_text='vehicle').click()
        expect(page.locator('#clsRenameModal')).to_be_visible()
        field=page.locator('#clsRenameInput')
        expect(field).to_have_value('vehicle')
        field.fill('renamed-vehicle')
        field.press('Enter')
        expect(page.locator('#clsRenameModal')).to_be_hidden()
        expect(page.locator('#clsPageTableBody .cls-name', has_text='renamed-vehicle')).to_be_visible()
        with page.expect_response('**/classes/sync**') as response:
            page.locator('#clsPageSyncBtn').click()
        assert response.value.status==200
        with page.expect_download() as download:
            page.locator('#clsPageExportBtn').click()
        path=OUT/'classes-export.txt'
        download.value.save_as(path)
        assert 'renamed-vehicle' in path.read_text()
    record('classes-add-color-rename-sync-export',classes,page)
    def upload():
        page.locator('#rnUpload').click()
        files=[]
        for name,color in [('browser-one.png','green'),('browser-two.png','blue')]:
            path=OUT/name
            Image.new('RGB',(640,480),color).save(path)
            files.append(str(path))
        with page.expect_file_chooser() as chooser:
            page.locator('#uocImages').click()
        chooser.value.set_files(files)
        expect(page.locator('.uhp-batch-card')).to_have_count(1,timeout=20000)
        expect(page.locator('.uhp-batch-card')).to_contain_text('2 total',timeout=20000)
        page.locator('#upActiveRefreshBtn').click()
        expect(page.locator('.uhp-batch-card')).to_have_count(1)
        page.locator('.uhp-batch-card .uhp-card-menu').click()
        page.locator('.kmenu-item').filter(has_text='Annotate raw images').click()
        expect(page.locator('#page-annotate')).to_be_visible()
        page.wait_for_function('state.imgW===640 && state.imgH===480')
    record('upload-file-chooser-two-images-open-batch',upload,page)
    def draw():
        page.locator('#bboxModeBtn').click()
        rect=page.locator('#annoCanvas').bounding_box()
        geo=page.evaluate('({x:state.panX,y:state.panY,z:state.zoom})')
        x=rect['x']+geo['x']+100*geo['z'];y=rect['y']+geo['y']+110*geo['z']
        page.mouse.move(x,y)
        page.mouse.down()
        page.mouse.move(x+180*geo['z'],y+130*geo['z'],steps=12)
        page.mouse.up()
        expect(page.locator('#cpConfirm')).to_be_visible()
        page.locator('#cpList .cp-item').first.click()
        page.locator('#cpConfirm').click()
        page.wait_for_function('state.bboxes.length===1')
        page.wait_for_timeout(900)
        rel=page.evaluate('state.filteredMedia[state.currentIdx].path')
        response=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/annotations',params={'path':rel})
        assert len(response.json()['bboxes'])==1,response.json()
        page.reload()
        page.wait_for_function('state.bboxes.length===1')
    record('annotation-mouse-draw-class-confirm-save-reload',draw,page)
    def media_library():
        for mode in ('light','dark'):
            page.evaluate('(m)=>ThemeEngine.setThemeMode(m)',mode)
            for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
                page.set_viewport_size(dict(width=width,height=height))
                page.wait_for_timeout(250)
                if page.locator('#sidebarLeft').evaluate('e=>e.classList.contains("collapsed")'):
                    page.locator('#leftSbExpand').click()
                expect(page.locator('#imageListCount')).to_have_text('2')
                assert page.locator('#totalCount').count()==1
                page.locator('#imageSearch').fill('no-such-image-xyz')
                expect(page.locator('#listEmpty')).to_be_visible()
                page.locator('#clearSearch').click()
                expect(page.locator('#imgListInner .img-item')).to_have_count(2)
                for head,body in [('mlOverviewHead','mlOverviewBody'),('mlFilterHead','mlFilterBody'),('mlUploadHead','mlUploadBody'),('mlImagesHead','mlImagesBody')]:
                    before=page.locator('#'+body).is_visible()
                    page.locator('#'+head).click()
                    page.wait_for_timeout(350)
                    assert page.locator('#'+body).is_visible()!=before,(head,body)
                    page.locator('#'+head).click()
                    page.wait_for_timeout(350)
                panel=page.locator('#sidebarLeft').bounding_box()
                assert panel['x']>=0 and panel['x']+panel['width']<=width+1,panel
                page.screenshot(path=str(OUT/f'media-library-{mode}-{device}.png'),full_page=True)
                page.locator('#leftSbToggle').click()
                expect(page.locator('#leftSbExpand')).to_be_visible()
                canvas=page.locator('#canvasArea').bounding_box()
                assert canvas['width']>=200,canvas
            page.set_viewport_size(dict(width=1440,height=900))
            page.wait_for_timeout(250)
            if page.locator('#sidebarLeft').evaluate('e=>e.classList.contains("collapsed")'):
                page.locator('#leftSbExpand').click()
        page.locator('#imgListInner .img-item').first.click()
        page.wait_for_function('state.bboxes.length===1')
    record('media-library-search-clear-sections-collapse-six-theme-viewports',media_library,page)
    def toggles():
        for id,key in [('toggleGridBtn','showGrid'),('toggleLabelsBtn','showLabels'),('repeatModeBtn','repeatMode'),('zoomLockBtn','zoomLocked')]:
            old=page.evaluate('state.'+key)
            page.locator('#'+id).click()
            assert page.evaluate('state.'+key)!=old,id
            page.locator('#'+id).click()
        for id,mode in [('polyModeBtn','polygon'),('editModeBtn','edit'),('panModeBtn','pan'),('bboxModeBtn','bbox')]:
            page.locator('#'+id).click()
            assert page.evaluate('state.mode')==mode
        old=page.evaluate('state.zoom')
        page.locator('#zoomInBtn').click()
        assert page.evaluate('state.zoom')>old
        page.locator('#zoomOutBtn').click()
        page.locator('#fitBtn').click()
    record('annotation-mode-grid-label-repeat-zoom-controls',toggles,page)
    def annotation_panel_navigation():
        for control,bar in (('#smartDetectBtn','#sdBar'),('#promptAnnotateBtn','#paBar')):
            for target in ('rnDataset','rnVersions','rnClasses','rnUpload','rnProjects'):
                page.locator('#rnAnnotate').click()
                page.locator(control).click()
                expect(page.locator(bar)).to_be_visible()
                page.locator('#'+target).click()
                expect(page.locator('#sdBar')).to_be_hidden()
                expect(page.locator('#paBar')).to_be_hidden()
                page.locator('#rnAnnotate').click()
                expect(page.locator(bar)).to_be_hidden()
        page.locator('#promptAnnotateBtn').click()
        expect(page.locator('#paBar')).to_be_visible()
        page.evaluate('location.hash="dataset"')
        expect(page.locator('#page-dataset')).to_be_visible()
        expect(page.locator('#paBar')).to_be_hidden()
        page.locator('#rnAnnotate').click()
    record('annotation-ai-panels-close-on-all-section-navigation',annotation_panel_navigation,page)
    def annotation_extended():
        page.wait_for_timeout(4500)
        for mode in ('light','dark'):
            page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}',mode)
            page.wait_for_timeout(350)
            page.set_viewport_size(dict(width=1440,height=900))
            for control in ('#toggleLabelsBtn','#toggleGridBtn','#repeatModeBtn'):
                page.locator(control).click()
                toast=page.locator('#toastStack .toast').last
                expect(toast).to_be_visible()
                bg=toast.evaluate('e=>getComputedStyle(e).backgroundColor')
                channels=list(map(int,__import__('re').findall(r'\d+',bg)[:3]))
                assert (min(channels)>200) if mode=='light' else (max(channels)<100),(mode,control,bg)
                page.screenshot(path=str(OUT/f'view-toggle-{mode}-{control[1:]}.png'),full_page=True)
                toast.locator('.toast-x').click()
                page.locator(control).click()
                page.locator('#toastStack .toast').last.locator('.toast-x').click()
            for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
                page.set_viewport_size(dict(width=width,height=height))
                for selector in ('#bboxModeBtn','#polyModeBtn','#editModeBtn','#panModeBtn','#toggleLabelsBtn','#undoBtn','#nullMarkBtn'):
                    page.locator(selector).scroll_into_view_if_needed()
                    box=page.locator(selector).bounding_box()
                    assert box['x']>=0 and box['x']+box['width']<=width+1,(selector,box)
                if mode=='light':
                    colors=page.locator('.right-nav').evaluate('e=>getComputedStyle(e).backgroundColor')
                    assert min(map(int,__import__('re').findall(r'\d+',colors)[:3]))>200,colors
                if width<1024:
                    nav=page.locator('.img-nav-bar').bounding_box()
                    zoom=page.locator('#zoomInBtn').bounding_box()
                    assert nav['y']+nav['height']<zoom['y'],(nav,zoom)
                page.screenshot(path=str(OUT/f'annotation-{mode}-{device}.png'),full_page=True)
        page.set_viewport_size(dict(width=1440,height=900))
        page.locator('#fitBtn').click()
        page.locator('#polyModeBtn').click()
        rect=page.locator('#annoCanvas').bounding_box()
        geo=page.evaluate('({x:state.panX,y:state.panY,z:state.zoom})')
        for x,y in ((350,150),(490,150),(420,300)):
            page.mouse.click(rect['x']+geo['x']+x*geo['z'],rect['y']+geo['y']+y*geo['z'])
        page.keyboard.press('Enter')
        expect(page.locator('#cpConfirm')).to_be_visible()
        page.locator('#cpList .cp-item').first.click()
        page.locator('#cpConfirm').click()
        page.wait_for_function('state.bboxes.length===2')
        if page.locator('#rsbRestoreTab').is_visible():
            page.locator('#rsbRestoreTab').click()
        page.locator('.rp-tab[data-rpt="props"]').click()
        page.locator('#propW').fill('70')
        page.locator('#applyPropsBtn').click()
        assert page.evaluate('(()=>{const p=state.bboxes.find(b=>b.type==="polygon").points.map(p=>p.x);return Math.abs(Math.max(...p)-Math.min(...p)-70)<1})()')
        page.locator('#undoBtn').click()
        page.wait_for_function('state.bboxes.length===2')
        page.locator('.rp-tab[data-rpt="labels"]').click()
        page.locator('#undoBtn').click()
        page.wait_for_function('state.bboxes.length===1')
        page.locator('#redoBtn').click()
        page.wait_for_function('state.bboxes.length===2')
        page.locator('#undoBtn').click()
        page.wait_for_function('state.bboxes.length===1')
        page.locator('#bboxModeBtn').click()
        page.wait_for_timeout(900)
    record('annotation-light-dark-responsive-tool-access-polygon-undo-redo',annotation_extended,page)
    def class_picker_sweep():
        for mode in ('light','dark'):
            page.evaluate('(m)=>ThemeEngine.setThemeMode(m)',mode)
            page.locator('#bboxModeBtn').click()
            page.locator('#fitBtn').click()
            rect=page.locator('#annoCanvas').bounding_box()
            geo=page.evaluate('({x:state.panX,y:state.panY,z:state.zoom})')
            x=rect['x']+geo['x']+350*geo['z']; y=rect['y']+geo['y']+310*geo['z']
            page.mouse.move(x,y); page.mouse.down()
            page.mouse.move(x+80*geo['z'],y+60*geo['z'],steps=8); page.mouse.up()
            expect(page.locator('#clsPopup')).to_be_visible()
            page.locator('#cpSearch').fill('no-class-with-this-name')
            expect(page.locator('#cpList .cp-item')).to_have_count(0)
            page.locator('#cpSearch').fill('')
            page.locator('#cpAddClsToggle').click()
            page.locator('#cpNewClsName').fill('picker-'+mode)
            page.locator('#cpAddClsBtn').click()
            expect(page.locator('#cpList')).to_contain_text('picker-'+mode)
            page.locator('#cpCancel').click()
            expect(page.locator('#clsPopup')).to_be_hidden()
            assert page.evaluate('state.bboxes.length')==1
    record('annotation-class-picker-search-create-cancel-both-themes',class_picker_sweep,page)
    def picker_placement():
        page.wait_for_timeout(4500)
        for mode in ('light','dark'):
            page.evaluate('(m)=>ThemeEngine.setThemeMode(m)',mode)
            for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
                page.set_viewport_size(dict(width=width,height=height))
                page.wait_for_timeout(250)
                page.locator('#bboxModeBtn').click()
                page.locator('#fitBtn').click()
                rect=page.locator('#annoCanvas').bounding_box()
                geo=page.evaluate('({x:state.panX,y:state.panY,z:state.zoom})')
                x=rect['x']+geo['x']+350*geo['z']; y=rect['y']+geo['y']+310*geo['z']
                page.mouse.move(x,y); page.mouse.down()
                page.mouse.move(x+80*geo['z'],y+60*geo['z'],steps=8); page.mouse.up()
                expect(page.locator('#clsPopup')).to_be_visible()
                page.wait_for_timeout(180)
                popup=page.locator('#clsPopup').bounding_box()
                area=page.locator('#canvasArea').bounding_box()
                assert popup['x']>=area['x'] and popup['x']+popup['width']<=area['x']+area['width']+1,popup
                assert popup['y']>=area['y'] and popup['y']+popup['height']<=area['y']+area['height']+1,popup
                assert popup['width']<=221,popup
                overlap=max(0,min(popup['x']+popup['width'],x+80*geo['z'])-max(popup['x'],x))*max(0,min(popup['y']+popup['height'],y+60*geo['z'])-max(popup['y'],y))
                assert overlap<1,(popup,x,y)
                page.screenshot(path=str(OUT/f'assign-class-{mode}-{device}.png'),full_page=True)
                header=page.locator('#clsPopup .cp-header').bounding_box()
                dx=-25 if popup['x']>area['x']+40 else 25
                page.mouse.move(header['x']+30,header['y']+10);page.mouse.down()
                page.mouse.move(header['x']+30+dx,header['y']+25,steps=8);page.mouse.up()
                moved=page.locator('#clsPopup').bounding_box()
                assert abs(moved['x']-popup['x'])+abs(moved['y']-popup['y'])>5,(popup,moved)
                page.locator('#cpCancel').click()
                assert page.evaluate('state.bboxes.length')==1
        page.set_viewport_size(dict(width=1440,height=900))
        page.wait_for_timeout(350)
    record('class-picker-compact-nonoverlap-drag-six-theme-viewports',picker_placement,page)
    def annotation_control_sweep():
        page.context.grant_permissions(['clipboard-read','clipboard-write'])
        for mode in ('light','dark'):
            page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}',mode)
            page.wait_for_timeout(350)
            if page.locator('#sidebarRight').evaluate('e=>e.classList.contains("collapsed")'):
                page.locator('#rsbRestoreTab').click()
            page.locator('.rp-tab[data-rpt="labels"]').click()
            page.locator('#annoList .anno-item').first.click()
            page.locator('.rp-tab[data-rpt="props"]').click()
            expect(page.locator('#propsForm')).to_be_visible()
            for id,value in [('propX','9999'),('propY','9999'),('propW','9999'),('propH','9999')]:
                page.locator('#'+id).fill(value)
            page.locator('#applyPropsBtn').click()
            assert page.evaluate('state.bboxes[0].x+state.bboxes[0].w<=state.imgW && state.bboxes[0].y+state.bboxes[0].h<=state.imgH')
            page.locator('#undoBtn').click()
            page.locator('.rp-tab[data-rpt="labels"]').click()
            page.locator('#annoList .anno-item').first.click()
            page.locator('.rp-tab[data-rpt="props"]').click()
            page.locator('#propClass').select_option('1')
            assert page.evaluate('state.bboxes[0].cls')==1
            page.locator('#propClass').select_option('0')
            page.locator('#setCoverBtn').click()
            expect(page.locator('#toastStack')).to_contain_text('cover',ignore_case=True)
            page.locator('#delSelBtn').click()
            page.wait_for_function('state.bboxes.length===0')
            page.locator('#undoBtn').click()
            page.wait_for_function('state.bboxes.length===1')
            page.locator('.rp-tab[data-rpt="raw"]').click()
            expect(page.locator('#rawDataView')).not_to_contain_text('No annotations')
            page.locator('#copyRawBtn').click()
            copied=page.evaluate('navigator.clipboard.readText()')
            assert len(copied.split())==5,copied
            page.locator('.rp-tab[data-rpt="comments"]').click()
            page.locator('#commentInput').fill('<img src=x onerror="window.auditXss=true">')
            page.locator('#commentSendBtn').click()
            expect(page.locator('#commentsList .ci-text')).to_contain_text('<img')
            assert page.locator('#commentsList img').count()==0
            page.locator('#clearNotesBtn').click()
            expect(page.locator('#commentsList')).to_contain_text('No notes')
            page.locator('.rp-tab[data-rpt="labels"]').click()
            for button,modal in [('helpBtn','shortcutsModal'),('settingsBtn','settingsModal'),('statsBtn','statsModal'),('importBtn','importModal'),('splitBtn','splitModal')]:
                page.locator('#'+button).click()
                expect(page.locator('#'+modal)).to_be_visible()
                page.keyboard.press('Escape')
                expect(page.locator('#'+modal)).to_be_hidden()
                page.locator('#'+button).click()
                expect(page.locator('#'+modal)).to_be_visible()
                page.evaluate('location.hash="dataset"')
                expect(page.locator('#'+modal)).to_be_hidden()
                page.locator('#rnAnnotate').click()
                expect(page.locator('#'+modal)).to_be_hidden()
            page.route('**/annotations*',lambda route: route.fulfill(status=409,json={'error':'Audit lock conflict'}) if route.request.method=='POST' else route.continue_())
            page.locator('#bboxModeBtn').click()
            page.keyboard.press('Control+s')
            expect(page.locator('#hdrSaveStatus')).to_contain_text('Error')
            old_index=page.evaluate('state.currentIdx')
            page.locator('#completeBtn').click()
            expect(page.locator('#toastStack')).to_contain_text('Image was not marked complete')
            assert page.evaluate('state.currentIdx')==old_index
            page.unroute('**/annotations*')
            page.keyboard.press('Control+s')
            expect(page.locator('#hdrSaveStatus')).to_contain_text('Saved')
            page.locator('label.autosave-toggle').click()
            assert page.evaluate('state.autoSave') is False
            page.locator('label.autosave-toggle').click()
            assert page.evaluate('state.autoSave') is True
            page.locator('#splitBtn').click()
            page.locator('#trainNum').fill('1')
            page.locator('#valNum').fill('0')
            page.locator('#testNum').fill('0')
            with page.expect_response('**/split?*') as split_response:
                page.locator('#startSplitBtn').click()
            assert split_response.value.status==200,split_response.value.text()
            expect(page.locator('#resultTitle')).to_have_text('Split Complete')
            page.locator('#resultModal .modal-x').click()
            page.locator('#completeBtn').click()
            page.wait_for_function('state.currentIdx===1')
            page.locator('#prevImgBtn').click()
            page.wait_for_function('state.currentIdx===0 && state.bboxes.length===1')
    record('annotation-both-themes-properties-delete-raw-notes-dialog-leaving-save-errors',annotation_control_sweep,page)
    def next_null():
        page.locator('#nextImgBtn').click()
        page.wait_for_function('state.bboxes.length===0')
        page.locator('#nullMarkBtn').click()
        page.wait_for_function('state.isCurrentNull===true')
        page.wait_for_timeout(600)
        rel=page.evaluate('state.filteredMedia[state.currentIdx].path')
        assert page.request.get(BASE+'/api/workspaces/1/projects/audit-project/annotations',params={'path':rel}).json()['is_null']
        page.locator('#completeBtn').click()
        expect(page.locator('#toastStack')).to_contain_text('Image marked as complete')
        assert page.request.get(BASE+'/api/workspaces/1/projects/audit-project/annotations',params={'path':rel}).json()['is_null']
        page.locator('#prevImgBtn').click()
        page.wait_for_function('state.bboxes.length===1')
    record('annotation-next-null-mark-previous',next_null,page)
    def dialogs():
        for id,modal in [('helpBtn','shortcutsModal'),('statsBtn','statsModal'),('settingsBtn','settingsModal')]:
            page.locator('#'+id).click()
            expect(page.locator('#'+modal)).to_be_visible()
            if modal=='settingsModal':
                page.locator('#brightnessSlider').press('Home')
                page.locator('#brightnessSlider').press('ArrowRight')
                page.locator('#applySettingsBtn').click()
                assert page.evaluate('state.brightness')==21
            else:
                page.locator('#'+modal+' .modal-x').click()
            expect(page.locator('#'+modal)).to_be_hidden()
    record('annotation-shortcuts-statistics-adjustments-dialogs',dialogs,page)
    def dataset():
        page.locator('#rnUpload').click()
        expect(page.locator('.uhp-batch-card')).to_be_visible()
        page.locator('.uhp-batch-card .uhp-card-menu').click()
        page.locator('.kmenu-item').filter(has_text='Add to dataset').click()
        expect(page.locator('#uspModal')).to_be_visible()
        page.locator('#uspConfirmBtn').click()
        expect(page.locator('#uspModal')).to_be_hidden(timeout=20000)
        page.locator('#rnDataset').click()
        expect(page.locator('#page-dataset')).to_be_visible()
        items=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/datasets/images').json()['items']
        assert len(items)==2,items
        page.locator('#dsSearch').fill('notfound-xyz')
        page.locator('#dsSearch').fill('')
        page.locator('#dsClassFilter').select_option('0')
        page.locator('#dsClassFilter').select_option('')
    record('dataset-add-batch-search-class-filter',dataset,page)
    def gallery():
        page.locator('#dsResetFilters').click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        for split,count in [('train',1),('test',1),('val',0),('all',2)]:
            page.locator(f'#dsSplitPills [data-dsf="{split}"]').click()
            expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(count)
        page.locator('#dsClassFilter').select_option('0')
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(1)
        page.locator('#dsResetFilters').click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        page.locator('#dsPerPageSelect').select_option('20')
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        page.locator('#dsPerPageSelect').select_option('50')
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        page.locator('#dsSearch').fill('notfound-xyz')
        expect(page.locator('#dsEmptyTitle')).to_have_text('No images match your filters')
        page.locator('#dsEmptyAction').click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        page.locator('#dsClassFilter').select_option('__null__')
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(1)
        expect(page.locator('#dsGrid .ds-card-meta-row')).to_contain_text('Background')
        page.locator('#dsResetFilters').click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        for density in ('small','large','medium'):
            page.locator('#dsDensity').select_option(density)
            expect(page.locator('#dsGrid')).to_have_attribute('data-density',density)
        page.locator('#dsShowAnnotations').uncheck()
        expect(page.locator('#dsGrid')).to_have_class(__import__('re').compile('ds-hide-annotations'))
        page.locator('#dsShowAnnotations').check()
        page.locator('#dsSelectPage').click()
        expect(page.locator('#dsSelCount')).to_have_text('2 selected')
        page.locator('#dsSelClearBtn').click()
        expect(page.locator('#dsSelToolbar')).to_be_hidden()
        page.locator('#dsGrid .ds-card-checkbox').first.click()
        expect(page.locator('#dsSelCount')).to_have_text('1 selected')
        page.locator('#dsSelToggle').click()
        page.locator('#dsGrid .ds-card').first.focus()
        page.keyboard.press('Enter')
        expect(page.locator('#dsLightbox')).to_be_visible()
        page.locator('#dsLbNext').click()
        expect(page.locator('.ds-lb-counter')).to_have_text('2 / 2')
        page.locator('.ds-lb-close').click()
        expect(page.locator('#dsLightbox')).to_be_hidden()
        page.wait_for_timeout(4000)
        for width,height,name in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
            page.set_viewport_size(dict(width=width,height=height))
            page.locator('#page-dataset').evaluate('e=>e.scrollTop=0')
            page.screenshot(path=str(OUT/f'dataset-gallery-{name}-header.png'),full_page=True)
            page.locator('#dsGrid .ds-card').first.scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            box=page.locator('#dsGrid .ds-card').first.bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=width+1,box
            page.screenshot(path=str(OUT/f'dataset-gallery-{name}.png'),full_page=True)
        page.set_viewport_size(dict(width=1440,height=900))
        page.locator('#dsCreateVersionBtn').click()
        expect(page.locator('#vwOverlay')).to_be_visible()
        page.locator('#vwClose').click()
    record('dataset-gallery-filters-density-labels-selection-keyboard-preview-responsive',gallery,page)
    def gallery_error():
        page.locator('#rnDataset').click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
        page.route('**/datasets/images?*', lambda route: route.abort())
        page.locator('#dsResetFilters').click()
        expect(page.locator('#dsGrid')).to_contain_text('Could not load images')
        assert page.locator('#dsEmpty').count()==1
        page.unroute('**/datasets/images?*')
        page.get_by_role('button',name='Try again',exact=True).click()
        expect(page.locator('#dsGrid .ds-card:not(.ds-card-skeleton)')).to_have_count(2)
    record('dataset-gallery-network-error-retry',gallery_error,page)
    def dataset_themes():
        snapshots=[]
        for mode in ('light','dark'):
            page.evaluate('(mode)=>{localStorage.setItem("am_theme_mode",mode);ThemeEngine.setThemeMode(mode)}',mode)
            page.wait_for_timeout(350)
            for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
                page.set_viewport_size(dict(width=width,height=height))
                page.locator('#page-dataset').evaluate('e=>e.scrollTop=0')
                page.screenshot(path=str(OUT/f'dataset-{mode}-{device}.png'),full_page=True)
                styles=page.evaluate('''() => Object.fromEntries(['#page-dataset','.ds-header','.ds-filter-bar','.ds-card','.ds-gallery-toolbar','#dsDensity','#dsSearch','#dsClassFilter','#dsPerPageSelect','.right-nav','.anno-account-btn'].map(s=>{let e=document.querySelector(s),c=getComputedStyle(e);return [s,{background:c.backgroundColor,color:c.color}]}))''')
                snapshots.append(dict(mode=mode,device=device,styles=styles))
                bg=styles['#page-dataset']['background']
                channels=[int(x) for x in __import__('re').findall(r'\d+',bg)[:3]]
                assert (sum(channels)/3>200) if mode=='light' else (sum(channels)/3<80),(mode,styles)
                if mode=='light':
                    for selector in ('#dsClassFilter','#dsPerPageSelect','.right-nav','.anno-account-btn'):
                        rgb=[int(x) for x in __import__('re').findall(r'\d+',styles[selector]['background'])[:3]]
                        assert min(rgb)>200,(selector,styles[selector])
            page.set_viewport_size(dict(width=1440,height=900))
            page.locator('#dsGrid .ds-card').first.click()
            expect(page.locator('#dsLightbox')).to_be_visible()
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT/f'dataset-{mode}-viewer.png'),full_page=True)
            page.locator('.ds-lb-close').click()
            expect(page.locator('#dsLightbox')).to_be_hidden()
        return snapshots
    record('dataset-light-dark-surfaces-responsive-viewer',dataset_themes,page)
    def version():
        page.locator('#rnVersions').click()
        page.locator('#createVersionBtn').click()
        expect(page.locator('#vwOverlay')).to_be_visible()
        page.locator('#vwName').fill('Browser snapshot')
        page.locator('#vwNote').fill('Created through real browser UI')
        for _ in range(4):
            page.locator('#vwBtnNext').click()
        page.locator('#vwBtnCreate').click()
        expect(page.locator('#vwOverlay')).to_be_hidden(timeout=20000)
        page.screenshot(path=str(OUT/'version-created-desktop.png'),full_page=True)
        # Find the generated version via the same browser's authenticated API
        # before checking the actual download control in a later case.
        response=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/versions')
        assert any(v['name']=='Browser snapshot' and v['total_images']==2 for v in response.json()),response.json()
    record('versions-five-step-wizard-create',version,page)
    def downloads():
        with page.expect_download() as download:
            page.locator('#vsDetailPane button').filter(has_text='Download').click()
        archive=OUT/'browser-version.zip'
        download.value.save_as(archive)
        import zipfile
        with zipfile.ZipFile(archive) as z:
            assert sum('/images/' in p for p in z.namelist())==2
            assert sum('/labels/' in p for p in z.namelist())==2
            assert not any(p.endswith('.suggestions.json') for p in z.namelist())
        page.locator('#rnDataset').click()
        with page.expect_download() as download:
            page.locator('#dsExportBtn').click()
        download.value.save_as(OUT/'browser-dataset.zip')
        with zipfile.ZipFile(OUT/'browser-dataset.zip') as z:
            assert sum('/images/' in p for p in z.namelist())==2
    record('version-and-dataset-real-download-archive-inspection',downloads,page)
    def delete_version():
        page.locator('#rnVersions').click()
        page.locator('.vs-item').first.click()
        # Versions redesign: delete lives in the detail's ⋮ menu + themed confirm
        page.locator('#vsDetailPane [data-ver-act="more"]').click()
        page.locator('.kmenu .kmenu-item', has_text='Delete version').click()
        ui_confirm(page)
        expect(page.locator('.vs-item')).to_have_count(0)
    record('version-delete-confirmation-persistence',delete_version,page)
    def dataset_card_export():
        page.locator('#rnUpload').click()
        expect(page.locator('.upds-card')).to_have_count(1)
        page.locator('.upds-card-menu').click()
        with page.expect_download(timeout=5000) as download:
            page.locator('.kmenu-item').filter(has_text='Export').click()
        download.value.save_as(OUT/'browser-dataset-card.zip')
    record('dataset-card-export-menu-real-download',dataset_card_export,page)


def members(page):
    login(page)
    page.goto(BASE+'/workspace/1/members')
    def invite():
        expect(page.locator('#invite-card')).to_be_visible()
        button=page.locator('button[onclick="MembersFeature.invite()"]')
        button.click()
        expect(page.locator('#invite-error')).to_contain_text('email')
        page.locator('#invite-email').fill('audit-editor@example.test')
        page.locator('#invite-role').select_option('editor')
        button.click()
        expect(page.locator('.member-row').filter(has_text='audit-editor@example.test')).to_be_visible()
        page.locator('#invite-email').fill('audit-editor@example.test')
        button.click()
        expect(page.locator('#invite-error')).to_contain_text('already')
    record('members-invite-required-success-duplicate',invite,page)
    def roles_remove():
        row=page.locator('.member-row').filter(has_text='audit-editor@example.test')
        for role in ('viewer','editor','owner','viewer'):
            row.locator('select').select_option(role)
            page.wait_for_timeout(150)
            expect(row.locator('select')).to_have_value(role)
        row.get_by_role('button',name='Remove').click()
        ui_confirm(page)
        expect(row).to_have_count(0)
        page.reload()
        expect(page.locator('.member-row')).to_have_count(1)
    record('members-all-role-options-remove-reload',roles_remove,page)
    def navigation():
        page.get_by_role('link',name='Dashboard').click()
        page.wait_for_url(BASE+'/')
        page.goto(BASE+'/workspace/1/members')
        page.locator('#nav-brand-link').click()
        page.wait_for_url(BASE+'/')
    record('members-dashboard-brand-links',navigation,page)


def ai(page):
    from PIL import Image
    login(page)
    page.goto(BASE+'/pages/annotate?workspace_id=1&project=audit-project#upload')
    file=OUT/'ai-test.png'
    Image.new('RGB',(640,480),'gray').save(file)
    with page.expect_file_chooser() as chooser:
        page.locator('#uocImages').click()
    chooser.value.set_files(str(file))
    expect(page.locator('.uhp-batch-card')).to_have_count(1,timeout=20000)
    page.locator('.uhp-batch-card').click()
    page.wait_for_function('state.imgW===640',timeout=20000)
    def smart_detect():
        page.locator('#smartDetectBtn').click()
        expect(page.locator('#sdBar')).to_be_visible()
        page.locator('#sdModelSelect option').first.wait_for(state='attached',timeout=60000)
        options=page.locator('#sdModelSelect option').evaluate_all('es=>es.map(e=>({value:e.value,disabled:e.disabled}))')
        wanted=next((o['value'] for o in options if 'yolo11n' in o['value'] and not o['disabled']),None)
        if not wanted:
            raise BlockedTest('Bundled YOLO11n not available in model selector: '+str(options))
        page.locator('#sdModelSelect').select_option(wanted)
        for _ in range(60):
            settings=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/ai/settings').json()
            if settings.get('model')==wanted:
                break
            page.wait_for_timeout(250)
        assert settings.get('model')==wanted,settings
        expect(page.locator('#sdRunNowBtn')).to_be_enabled(timeout=90000)
        with page.expect_response(lambda r:'/ai/predict' in r.url and r.request.post_data_json.get('model')==wanted,timeout=120000) as response:
            page.locator('#sdRunNowBtn').click(timeout=30000)
        assert response.value.status==200,response.value.text()
        result=response.value.json()
        assert result.get('model')==wanted,result
        assert isinstance(result.get('predictions'),list),result
        page.locator('#sdBarCollapse').click()
        page.locator('#sdBarCollapse').click()
        page.locator('#sdBarClose').click()
        expect(page.locator('#sdBar')).to_be_hidden()
        return dict(model=result.get('model'),predictions=len(result['predictions']),scope='Real local inference on synthetic image; not accuracy evaluation')
    record('ai-smart-detect-real-yolo-inference-collapse-close',smart_detect,page)
    def bad_model():
        page.locator('#smartDetectBtn').click()
        bad=OUT/'audit-invalid.pt'
        bad.write_bytes(b'not a pytorch checkpoint')
        with page.expect_response('**/api/ai/upload_model',timeout=60000) as response:
            page.locator('#sdModelUpload').set_input_files(str(bad))
        assert response.value.status==422,response.value.text()
        expect(page.locator('#sdModelStatus')).not_to_have_text('')
        page.locator('#sdBarClose').click()
    record('ai-invalid-model-upload-readable-rejection',bad_model,page)
    def prompt_controls():
        page.locator('#promptAnnotateBtn').click()
        expect(page.locator('#paBar')).to_be_visible()
        page.locator('#paPhraseInput').fill('person')
        page.locator('#paPhraseAdd').click()
        expect(page.locator('#paChips')).to_contain_text('person')
        page.locator('#paChips button').first.click()
        expect(page.locator('#paChips .pa-chip')).to_have_count(0)
        page.locator('#paTabBox').click()
        expect(page.locator('#paPaneBox')).to_be_visible()
        page.locator('#paExNeg').click()
        page.locator('#paExPos').click()
        page.locator('#paTabText').click()
        page.locator('#paBarCollapse').click()
        page.locator('#paBarCollapse').click()
        page.locator('#paPhraseInput').fill('person')
        page.locator('#paPhraseAdd').click()
    record('ai-prompt-phrase-add-remove-text-box-tabs-collapse',prompt_controls,page)
    def sam3():
        spec=page.request.get(BASE+'/api/ai/prompt/engines',timeout=60000).json()
        if page.locator('#paRunBtn').is_disabled():
            raise BlockedTest('SAM3 run disabled; engine availability: '+str(spec))
        with page.expect_response(lambda r:'/ai/prompt' in r.url and r.request.method=='POST',timeout=180000) as response:
            page.locator('#paRunBtn').click()
        assert response.value.status==200,response.value.text()
        data=response.value.json()
        assert isinstance(data.get('predictions'),list),data
        expect(page.locator('#paRunBtn')).to_be_enabled(timeout=20000)
        page.locator('#paBarClose').click()
        return dict(engine='sam3',result_keys=list(data),device=data.get('device'),elapsed_ms=data.get('elapsed_ms'),scope='Real local text inference on synthetic image; not accuracy evaluation')
    record('ai-sam3-real-text-inference',sam3,page)


def media(page):
    from PIL import Image
    import zipfile
    login(page)
    page.goto(BASE+'/pages/annotate?workspace_id=1&project=audit-project#upload')
    def zip_import():
        image=OUT/'zip-image.png'
        Image.new('RGB',(80,60),'orange').save(image)
        archive=OUT/'browser-import.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.write(image,'train/images/imported.png')
            z.writestr('train/labels/imported.txt','0 0.5 0.5 0.2 0.2\n')
            z.writestr('data.yaml','names: [imported-object]\nnc: 1\n')
        with page.expect_file_chooser() as chooser:
            page.locator('#uocImport').click()
        chooser.value.set_files(str(archive))
        # The upload-page ZIP flow previews the archive in a confirmation drawer.
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT/'zip-preview-desktop.png'),full_page=True)
        RESULTS.append(dict(name='zip-preview-controls',status='OBSERVED',detail=page.locator('button:visible').evaluate_all('es=>es.map(e=>({id:e.id,text:e.innerText}))')))
        confirm=page.locator('#udrConfirmBtn')
        if confirm.count() and confirm.is_visible():
            confirm.click()
        else:
            choices=page.get_by_role('button').filter(has_text='Import')
            if choices.count():
                choices.last.click()
        expect(page.locator('.uhp-batch-card')).to_have_count(1,timeout=20000)
        page.locator('.uhp-batch-card').click()
        page.wait_for_function('state.imgW===80')
        page.wait_for_function('state.bboxes.length===1')
    record('media-yolo-zip-preview-import-annotation',zip_import,page)
    def video():
        ffmpeg=ROOT/'.audit-tools/bin/ffmpeg.exe'
        if not ffmpeg.exists():
            raise BlockedTest('No ffmpeg binary available')
        path=OUT/'browser-video.mp4'
        proc=subprocess.run([str(ffmpeg),'-y','-f','lavfi','-i','color=c=blue:s=320x240:r=5','-t','1','-c:v','libx264','-pix_fmt','yuv420p',str(path)],capture_output=True,timeout=30)
        assert proc.returncode==0,proc.stderr.decode(errors='replace')[-600:]
        page.locator('#rnUpload').click()
        with page.expect_file_chooser() as chooser:
            page.locator('#uocVideo').click()
        chooser.value.set_files(str(path))
        expect(page.locator('#uploadModal')).to_be_visible()
        page.locator('#fpsSelect').select_option('2')
        page.locator('#sizeSelect').select_option('custom')
        assert not any(e['type']=='pageerror' for e in EVENTS),EVENTS
        expect(page.locator('#customSizeRow')).to_be_visible()
        page.locator('#customW').fill('128')
        page.locator('#customH').fill('96')
        page.locator('#frameFormatSelect').select_option('png')
        expect(page.locator('#frameSplitSelect')).to_be_disabled()
        with page.expect_response(lambda r:'/extract_frames' in r.url,timeout=60000) as response:
            page.locator('#startExtractBtn').click()
        assert response.value.status==200,response.value.text()
        result=response.value.json()
        assert result.get('frames_extracted')==2,result
        page.wait_for_function('document.querySelector("#startExtractBtn").disabled===true')
        batch=page.request.get(BASE+f"/api/workspaces/1/projects/audit-project/uploads/{result['upload_id']}/media").json()
        assert len(batch['media'])==2,batch
        indexed=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/media?per_page=50').json()['media']
        assert all(any(m['name']==item['name'] for m in indexed) for item in batch['media']),indexed
        for item in batch['media']:
            assert item['name'].endswith('.png'),item
            image=page.request.get(BASE+'/api/workspaces/1/projects/audit-project/image',params={'path':item['path']})
            import io
            with Image.open(io.BytesIO(image.body())) as im:
                assert im.size==(128,96),im.size
        expect(page.locator('#uploadModal')).to_be_hidden(timeout=10000)
    record('media-real-video-extraction-size-format-frame-count',video,page)


def navigation_themes(page):
    import re
    login(page)
    page.goto(BASE+'/pages/annotate?workspace_id=1&project=audit-project#annotate')
    def rgb(value):
        return [float(v) for v in re.findall(r'[\d.]+',value)[:3]]
    def luminance(color):
        values=[v/255 for v in color]
        values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(a*b for a,b in zip(values,(.2126,.7152,.0722)))
    def contrast(a,b):
        x,y=sorted((luminance(a),luminance(b)))
        return (y+.05)/(x+.05)
    for mode in ('light','dark'):
        page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}',mode)
        for width,height,device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
            page.set_viewport_size(dict(width=width,height=height))
            for section in ('upload','annotate','dataset','versions','classes','projects'):
                def check(section=section,mode=mode,device=device):
                    page.locator(f'.rn-item[data-page="{section}"]').click()
                    page.wait_for_timeout(220)
                    styles=page.evaluate('''() => {const nav=getComputedStyle(document.querySelector('.right-nav'));return {background:nav.backgroundColor,items:[...document.querySelectorAll('.rn-item')].map(e=>({text:e.title,color:getComputedStyle(e).color})),badges:[...document.querySelectorAll('.rn-badge')].map(e=>({color:getComputedStyle(e).color,background:getComputedStyle(e).backgroundColor}))}}''')
                    bg=rgb(styles['background'])
                    assert (min(bg)>200) if mode=='light' else (max(bg)<80),styles
                    for badge in styles['badges']:
                        assert contrast(rgb(badge['color']),rgb(badge['background']))>=4.5,(mode,badge)
                    for item in styles['items']:
                        assert contrast(rgb(item['color']),bg)>=4.5,(mode,item,styles['background'])
                    if section=='dataset':
                        page.screenshot(path=str(OUT/f'shared-nav-{mode}-{device}.png'),full_page=True)
                    return styles
                record(f'shared-nav-{mode}-{device}-{section}-contrast',check,page)
    page.reload()
    expect(page.locator('html')).not_to_have_class(re.compile('light-mode'))
    expect(page.locator('#page-projects')).to_be_visible()
    record('shared-nav-theme-persists-after-reload',lambda: expect(page.locator('.right-nav')).to_be_visible(),page)


DS_PAGES = [('/login','login',False),('/register','register',False),('/forgot-password','forgot',False),
            ('/forgot-password?token=invalid','reset-invalid',False),('/help','help',False),
            ('/','dashboard',True),('/settings','settings',True),('/workspace/1/members','members',True)]
DS_PAGES += [(f'/pages/annotate?workspace_id=1&project=audit-project#{s}',s,True)
             for s in ('projects','upload','annotate','dataset','versions','classes')]
# Decorative motion (three.js scene, ambient animations) is frozen/hidden so a
# pixel diff measures styling only.
DS_FREEZE = '''*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}
#scene,canvas#scene,#vignette{visibility:hidden!important}'''


def _ds_open(page, route, mode):
    page.goto(BASE+route)
    page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m)}', mode)
    page.reload()
    page.wait_for_load_state('networkidle')
    page.add_style_tag(content=DS_FREEZE)
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(500)


def design_system_snapshots(page):
    """Before/after screenshots of every page, both themes, three sizes.
    DS_LABEL=before|after selects the output folder; scripts compare them."""
    label = os.environ.get('DS_LABEL', 'current')
    out = OUT/'ds'/label
    out.mkdir(parents=True, exist_ok=True)
    logged = False
    for route, name, auth_needed in DS_PAGES:
        if auth_needed and not logged:
            login(page); logged = True
        for mode in ('light', 'dark'):
            for width, height, device in ((1440,900,'desktop'),(768,1024,'tablet'),(390,844,'mobile')):
                def shot(route=route,name=name,mode=mode,width=width,height=height,device=device):
                    page.set_viewport_size(dict(width=width,height=height))
                    _ds_open(page, route, mode)
                    path = out/f'{name}-{mode}-{device}.png'
                    page.screenshot(path=str(path), full_page=False)
                    return {'file': str(path.relative_to(ROOT)),
                            'overflow': page.evaluate('document.documentElement.scrollWidth>innerWidth')}
                record(f'ds-snapshot-{name}-{mode}-{device}', shot, page)


def design_system_propagation(page):
    """Override the CENTRAL tokens only and assert every page's components follow.
    Proves a change in tokens.css reaches each page without page edits."""
    probe_js = '''() => {
      const pick = sel => [...document.querySelectorAll(sel)].filter(e=>e.getClientRects().length).slice(0,40);
      const fams = pick('body,h1,h2,h3,p,label,button,input,select,a,.btn,td,th,span')
        .map(e=>({sel:e.tagName+(e.id?'#'+e.id:'')+(e.className&&typeof e.className==='string'?'.'+e.className.split(' ')[0]:''),
                  fam:getComputedStyle(e).fontFamily, size:parseFloat(getComputedStyle(e).fontSize)}));
      const tok = getComputedStyle(document.documentElement);
      return {fams, accent:tok.getPropertyValue('--accent').trim(), body:getComputedStyle(document.body).fontFamily};
    }'''
    override = ''':root,:root.light-mode{--font-sans:"Courier New",monospace!important;--font-scale:1.25!important;
      --accent:rgb(255,0,255)!important}'''
    logged = False
    for route, name, auth_needed in DS_PAGES:
        if auth_needed and not logged:
            login(page); logged = True
        for mode in ('light', 'dark'):
            def check(route=route,name=name,mode=mode):
                page.set_viewport_size(dict(width=1440,height=900))
                _ds_open(page, route, mode)
                before = page.evaluate(probe_js)
                page.add_style_tag(content=override)
                page.wait_for_timeout(150)
                after = page.evaluate(probe_js)
                assert 'courier' in after['body'].lower(), ('body font did not follow --font-sans', after['body'])
                assert after['accent'].replace(' ','') == 'rgb(255,0,255)', after['accent']
                # Every sans-serif text element must follow the central family token.
                stuck = [a for a in after['fams'] if 'sora' in a['fam'].lower() or 'inter' in a['fam'].lower()]
                assert not stuck, ('elements bypass --font-sans', stuck[:8])
                grown = sum(1 for b,a in zip(before['fams'],after['fams']) if a['size'] > b['size']*1.1)
                return {'elements': len(after['fams']), 'scaled_by_font_scale': grown,
                        'body_before': before['body'], 'body_after': after['body']}
            record(f'ds-propagation-{name}-{mode}', check, page)


DS_GEOMETRY_JS = r'''() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const name = e => e.tagName.toLowerCase() + (e.id ? '#'+e.id : '') +
    (typeof e.className === 'string' && e.className.trim() ? '.'+e.className.trim().split(/\s+/)[0] : '');
  return [...document.querySelectorAll('body *')].filter(vis).slice(0, 1500).map(e => {
    const s = getComputedStyle(e);
    return {n: name(e), inline: !!(e.getAttribute('style')||'').match(/radius|padding|shadow|transition/),
      rad: parseFloat(s.borderTopLeftRadius) || 0, pad: parseFloat(s.paddingLeft) || 0,
      shadow: s.boxShadow, dur: parseFloat(s.transitionDuration) || 0};
  });
}'''


def design_system_geometry(page):
    """Override ONLY the global knobs and measure, per element, whether its
    radius / padding / shadow / transition followed. Non-followers are listed:
    they are literals the tokenizers could not reach (JS-built styles, UA
    defaults), so the result is a measured coverage figure, not a claim."""
    override = ''':root,:root.light-mode{--radius-scale:2!important;--space-scale:1.5!important;
      --shadow-strength:0!important;--motion-scale:2!important}'''
    logged = False
    for route, name, auth_needed in DS_PAGES:
        if auth_needed and not logged:
            login(page); logged = True
        for mode in ('light', 'dark'):
            def check(route=route, name=name, mode=mode):
                page.set_viewport_size(dict(width=1440, height=900))
                _ds_open(page, route, mode)
                # _ds_open freezes transitions for screenshots; measure the real ones here
                page.reload(); page.wait_for_load_state('networkidle'); page.wait_for_timeout(300)
                before = page.evaluate(DS_GEOMETRY_JS)
                page.add_style_tag(content=override)
                page.wait_for_timeout(150)
                motion_after = page.evaluate(DS_GEOMETRY_JS)
                # `transition: all` would animate the new radius/padding; read the
                # settled values, not a mid-transition frame.
                page.add_style_tag(content='*,*::before,*::after{transition:none!important}')
                page.wait_for_timeout(100)
                after = page.evaluate(DS_GEOMETRY_JS)
                for row, m in zip(after, motion_after):
                    row['dur'] = m['dur']
                pairs = [(b, a) for b, a in zip(before, after) if b['n'] == a['n']]
                def cover(key, ok, eligible):
                    rows = [(b, a) for b, a in pairs if eligible(b)]
                    miss = sorted({b['n'] + (' [inline]' if b['inline'] else '') for b, a in rows if not ok(b, a)})
                    return {'eligible': len(rows), 'followed': len(rows) - sum(1 for b, a in rows if not ok(b, a)), 'missed': miss[:12]}
                res = {
                    'radius': cover('rad', lambda b, a: abs(a['rad'] - 2 * b['rad']) < 1.01,
                                    lambda b: 0 < b['rad'] < 400),
                    'padding': cover('pad', lambda b, a: abs(a['pad'] - 1.5 * b['pad']) < 1.01,
                                     lambda b: b['pad'] >= 2),
                    'shadow': cover('shadow', lambda b, a: a['shadow'] == 'none' or '0)' in a['shadow'] or ', 0)' in a['shadow'] or a['shadow'] != b['shadow'],
                                    lambda b: b['shadow'] != 'none' and 'rgba(0, 0, 0' in b['shadow']),
                    'motion': cover('dur', lambda b, a: abs(a['dur'] - 2 * b['dur']) < 0.002,
                                    lambda b: b['dur'] > 0),
                }
                return res
            record(f'ds-geometry-{name}-{mode}', check, page)


def design_system_controls(page):
    """Interactive checks that popups and controls follow the shared tokens,
    both themes, desktop + mobile: themed tooltip (and title restored),
    switch off/on, annotator modal == shared confirm geometry, menu surfaces,
    native checkbox accent."""
    tok = '(n)=>getComputedStyle(document.documentElement).getPropertyValue(n).trim()'
    px = lambda v: round(float(str(v).replace('px', '').split()[0]), 1)
    login(page)
    project = BASE + '/pages/annotate?workspace_id=1&project=audit-project#annotate'
    for mode in ('light', 'dark'):
        for width, height, device in ((1440, 900, 'desktop'), (390, 844, 'mobile')):
            page.set_viewport_size(dict(width=width, height=height))

            def tooltip(mode=mode, device=device):
                page.goto(project); page.evaluate('(m)=>localStorage.setItem("am_theme_mode",m)', mode); page.reload()
                page.wait_for_timeout(500)
                el = page.locator('#helpBtn')
                el.hover(); page.wait_for_timeout(600)
                tip = page.locator('.ui-tooltip.show')
                expect(tip).to_have_text('Shortcuts (?)')
                bg = tip.evaluate('e=>getComputedStyle(e).backgroundColor')
                want = page.evaluate('''()=>{const d=document.createElement('div');d.style.color='var(--tooltip-bg)';
                    document.body.append(d);const c=getComputedStyle(d).color;d.remove();return c}''')
                assert bg == want, (bg, want)
                assert el.get_attribute('title') is None  # parked while shown, so no OS tooltip doubles it
                page.mouse.move(5, height - 5); page.wait_for_timeout(200)
                expect(tip).to_have_count(0)
                assert el.get_attribute('title') == 'Shortcuts (?)'
                return {'bg': bg}
            record(f'ds-controls-tooltip-{mode}-{device}', tooltip, page)

            def switch(mode=mode, device=device):
                track = page.locator('.autosave-toggle .aToggle')
                if not track.is_visible():
                    raise BlockedTest('autosave switch hidden at this size')
                on = track.evaluate('e=>getComputedStyle(e).backgroundColor')
                page.locator('.autosave-toggle').click(); page.wait_for_timeout(400)
                off = track.evaluate('e=>getComputedStyle(e).backgroundColor')
                assert page.evaluate('document.getElementById("autoSaveToggle").checked') is False
                page.locator('.autosave-toggle').click(); page.wait_for_timeout(400)
                assert on != off, ('switch looks the same off and on', on, off)
                return {'on': on, 'off': off}
            record(f'ds-controls-switch-{mode}-{device}', switch, page)

            def modals(mode=mode, device=device):
                page.locator('#helpBtn').click()
                m = page.locator('#shortcutsModal .modal')
                expect(m).to_be_visible(); page.wait_for_timeout(300)
                anno = m.evaluate('''e=>({r:getComputedStyle(e).borderTopLeftRadius,
                   pad:getComputedStyle(e.querySelector('.modal-head')).paddingLeft,
                   title:getComputedStyle(e.querySelector('.modal-head h3')).fontSize})''')
                page.keyboard.press('Escape'); expect(m).to_be_hidden()
                # don't return the promise: evaluate() would await the open dialog
                page.evaluate('() => { window.__c = UI.confirm({title:"T", message:"M"}); }')
                c = page.locator('[role="alertdialog"]')
                expect(c).to_be_visible(); page.wait_for_timeout(300)
                shared = c.evaluate('''e=>({r:getComputedStyle(e).borderTopLeftRadius,
                   pad:getComputedStyle(e.querySelector('.modal-header')).paddingLeft,
                   title:getComputedStyle(e.querySelector('.modal-header h3')).fontSize})''')
                page.keyboard.press('Escape'); expect(c).to_have_count(0)
                assert page.evaluate('window.__c') is not None
                assert anno['pad'] == shared['pad'] and anno['title'] == shared['title'], (anno, shared)
                if device == 'desktop':  # phones dock the shared modal (bottom corners square), top radius still equal
                    assert anno['r'] == shared['r'], (anno, shared)
                return {'annotator': anno, 'shared': shared}
            record(f'ds-controls-modal-geometry-{mode}-{device}', modals, page)

            def menus(mode=mode, device=device):
                page.goto(BASE + '/')
                page.locator('.pc-menu-btn').first.click()
                km = page.locator('.kmenu')
                expect(km).to_be_visible()
                k = km.evaluate('e=>[getComputedStyle(e).backgroundColor,getComputedStyle(e).borderTopLeftRadius]')
                page.keyboard.press('Escape')
                page.goto(project); page.wait_for_timeout(500)
                if not page.locator('#user-menu').is_visible():
                    raise BlockedTest('annotate account menu hidden at this size')
                page.locator('#user-menu').click()
                dd = page.locator('#user-menu .account-dropdown')
                expect(dd).to_be_visible(); page.wait_for_timeout(250)
                a = dd.evaluate('e=>[getComputedStyle(e).backgroundColor,getComputedStyle(e).borderTopLeftRadius]')
                page.locator('#user-menu').click()
                assert a == k, ('menus differ', a, k)
                return {'kmenu': k, 'account': a}
            record(f'ds-controls-menu-surfaces-{mode}-{device}', menus, page)

            def checkbox(mode=mode, device=device):
                page.goto(BASE + '/settings'); page.wait_for_timeout(400)
                page.locator('#nav-btn-notifications').click()
                cb = page.locator('#notif-email-digest')
                ac = cb.evaluate('e=>getComputedStyle(e).accentColor')
                want = page.evaluate('''()=>{const d=document.createElement('div');d.style.color='var(--accent)';
                    document.body.append(d);const c=getComputedStyle(d).color;d.remove();return c}''')
                assert ac == want, (ac, want)
                return {'accent-color': ac}
            record(f'ds-controls-native-checkbox-{mode}-{device}', checkbox, page)


SPLIT_METRICS_JS = '''e => { const cs = x => getComputedStyle(x), q = s => e.querySelector(s);
  const h = s => Math.round(q(s).getBoundingClientRect().height);
  const r = e.getBoundingClientRect();
  return {w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), right: Math.round(r.right), top: Math.round(r.top),
    bottom: Math.round(r.bottom), radius: cs(e).borderTopLeftRadius, bg: cs(e).backgroundColor,
    head: h('.ui-split-head'), foot: h('.ui-split-foot'), stats: h('.ui-split-stats'), rowH: h('.ui-split-row'),
    bar: h('.ui-split-bar'), title: cs(q('.ui-split-title')).fontSize, statN: cs(q('.ui-split-stat-n')).fontSize,
    label: cs(q('.ui-split-row-l')).fontSize, btnH: [...e.querySelectorAll('.ui-split-foot .btn')].map(b => Math.round(b.getBoundingClientRect().height)),
    btnR: cs(q('.ui-split-foot .btn')).borderTopLeftRadius, font: cs(e).fontFamily}; }'''


def design_system_split_card(page):
    """The Add-to-Dataset card must be ONE component: the Upload-page dialog
    (#uspModal) and the Annotate-page panel (#atdPanel) are measured and must
    match in width, section heights, type sizes, radius and button sizes, in
    light/dark at desktop/tablet/mobile; both fit the viewport; the ratio
    validation works in both. Screenshots: .audit-browser/split-card-*.png."""
    from PIL import Image
    login(page)
    url = BASE + '/pages/annotate?workspace_id=1&project=audit-project'
    page.goto(url + '#upload')
    files = []
    for name, color in (('split-one.png', 'green'), ('split-two.png', 'blue')):
        Image.new('RGB', (640, 480), color).save(OUT / name); files.append(str(OUT / name))
    with page.expect_file_chooser() as chooser:
        page.locator('#uocImages').click()
    chooser.value.set_files(files)
    expect(page.locator('.uhp-batch-card')).to_have_count(1, timeout=20000)
    page.locator('.uhp-batch-card .uhp-card-menu').click()
    page.locator('.kmenu-item').filter(has_text='Annotate raw images').click()
    page.wait_for_function('state.imgW===640')
    page.locator('#bboxModeBtn').click()
    box = page.locator('#annoCanvas').bounding_box()
    geo = page.evaluate('({x:state.panX,y:state.panY,z:state.zoom})')
    x = box['x'] + geo['x'] + 100 * geo['z']; y = box['y'] + geo['y'] + 110 * geo['z']
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 160 * geo['z'], y + 120 * geo['z'], steps=10); page.mouse.up()
    page.locator('#cpList .cp-item').first.click(); page.locator('#cpConfirm').click()
    page.wait_for_function('state.annotatedPaths.size>0')
    page.wait_for_timeout(900)

    def check_ratio(prefix, sliders, pcts, ok_btn):
        """Both cards share rebalanceSplit(): moving Train to 50 gives 25/25,
        the total stays 100, no error, Create stays enabled; back to 70 → 15/15."""
        page.locator('#' + sliders[0]).fill('50')
        got = [page.locator('#' + p).inner_text() for p in pcts]
        assert got == ['50%', '25%', '25%'], (prefix, got)
        expect(page.locator('#' + prefix + 'RatioErr')).to_be_hidden()
        assert page.locator('#' + ok_btn).is_enabled()
        page.locator('#' + sliders[0]).fill('70')
        got = [page.locator('#' + p).inner_text() for p in pcts]
        assert got == ['70%', '15%', '15%'], (prefix, got)
        return got

    for mode in ('light', 'dark'):
        for width, height, device in ((1440, 900, 'desktop'), (768, 1024, 'tablet'), (390, 844, 'mobile')):
            def compare(mode=mode, width=width, height=height, device=device):
                page.set_viewport_size(dict(width=width, height=height))
                page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}', mode)
                # Upload page dialog
                page.locator('#rnUpload').click()
                page.locator('.uhp-batch-card .uhp-card-menu').click()
                page.locator('.kmenu-item').filter(has_text='Add to dataset').click()
                card = page.locator('#uspModal .ui-split-card')
                expect(card).to_be_visible(); page.wait_for_timeout(400)
                expect(page.locator('#uspAnnotatedCount')).not_to_have_text('…', timeout=8000)
                up = card.evaluate(SPLIT_METRICS_JS)
                card.screenshot(path=str(OUT / f'split-card-upload-{mode}-{device}.png'))
                check_ratio('usp', ['batchTrainSlider'], ['batchTrainPct', 'batchValPct', 'batchTestPct'], 'uspConfirmBtn')
                page.locator('#uspCancelBtn').click(); expect(page.locator('#uspModal')).to_be_hidden()
                # Annotate page floating panel
                page.locator('#rnAnnotate').click()
                expect(page.locator('#atdPill')).to_be_visible(timeout=8000)
                page.locator('#atdPill').click()
                panel = page.locator('#atdPanel.atd-panel-visible')
                expect(panel).to_be_visible(); page.wait_for_timeout(450)
                an = panel.evaluate(SPLIT_METRICS_JS)
                panel.screenshot(path=str(OUT / f'split-card-annotate-{mode}-{device}.png'))
                check_ratio('atd', ['atdTrainSlider'], ['atdTrainPct', 'atdValPct', 'atdTestPct'], 'atdConfirmBtn')
                page.locator('#atdCancelBtn').click(); page.wait_for_timeout(300)
                expect(page.locator('#atdPanel')).to_be_hidden()
                same = ['w', 'h', 'radius', 'bg', 'head', 'foot', 'rowH', 'bar', 'title', 'statN', 'label', 'btnH', 'btnR', 'font']
                diff = {k: (up[k], an[k]) for k in same if up[k] != an[k]}
                assert not diff, ('Upload and Annotate cards differ', diff)
                for name, m in (('upload', up), ('annotate', an)):
                    assert m['x'] >= 0 and m['right'] <= width + 1 and m['top'] >= 0 and m['bottom'] <= height + 1, (name, m)
                assert up['btnH'][0] == up['btnH'][1], up['btnH']
                return {'upload': up, 'annotate': an}
            record(f'ds-split-card-same-{mode}-{device}', compare, page)


def classes_page(page):
    """Classes section: add / duplicate add / click-to-rename (Enter, Esc,
    blur, duplicate, empty) / colour / search / special characters / delete
    with themed confirm, each checked against the SERVER's class list; then
    screenshots + layout bounds in light/dark at three sizes."""
    import io
    from PIL import Image
    login(page)
    proj = BASE + '/api/workspaces/1/projects/audit-project'
    url = BASE + '/pages/annotate?workspace_id=1&project=audit-project#classes'
    page.goto(url); page.wait_for_timeout(600)
    # Seed REAL annotations (the old fixture had none, which hid the bug where
    # every class showed 0): class 'object' x3 + 'rare' x1 on one image, and a
    # second image left unannotated.
    auth = {'Authorization': 'Bearer ' + page.evaluate('localStorage.getItem("am_token")')}
    paths = []
    for name in ('cls-seed-1.png', 'cls-seed-2.png'):
        buf = io.BytesIO(); Image.new('RGB', (64, 48), 'gray').save(buf, format='PNG')
        r = page.request.post(proj + '/upload', headers=auth,
                              multipart={'file': {'name': name, 'mimeType': 'image/png', 'buffer': buf.getvalue()}})
        assert r.ok, r.text()
    media = page.request.get(proj + '/media', headers=auth).json()['media']
    seed = next(m['path'] for m in media if m['path'].endswith('cls-seed-1.png'))
    r = page.request.post(proj + '/classes', headers=auth, data={'name': 'rare', 'color': [200, 60, 60]})
    assert r.ok, r.text()
    rare_id = r.json()['new_id']
    box = lambda c, x: dict(class_id=c, x_center=x, y_center=.5, width=.1, height=.1)
    r = page.request.post(proj + '/annotations', headers=auth,
                          data={'path': seed, 'bboxes': [box(0, .2), box(0, .4), box(0, .6), box(rare_id, .8)]})
    assert r.ok, r.text()
    page.reload(); page.wait_for_timeout(900)
    body = page.locator('#clsPageTableBody')
    name_btn = lambda n: body.locator('.cls-name', has=page.locator('.cls-name-text', has_text=re.compile('^' + re.escape(n) + '$')))

    def names():
        return [t.strip() for t in body.locator('.cls-name-text').all_inner_texts()]
    # row lookup: `has=` must be RELATIVE to the row, not rooted at body
    row_of = lambda n: body.locator('tr', has=page.locator('.cls-name-text', has_text=re.compile('^' + re.escape(n) + '$')))

    def row_action(row, label):
        """Open a class row's ⋮ menu (shared KebabMenu) and choose an item."""
        row.locator('.cls-more').click()
        menu = page.locator('.kmenu')
        expect(menu).to_be_visible()
        menu.locator('.kmenu-item', has_text=label).click()
        expect(menu).to_have_count(0)


    def counts_and_insights_match_server():
        stats = page.request.get(proj + '/stats', headers=auth).json()
        by_id = {c['id']: c for c in stats['class_counts']}
        assert by_id[0]['count'] == 3 and by_id[rare_id]['count'] == 1, by_id
        cells = lambda cid: page.locator(f'#clsPageTableBody tr[data-id="{cid}"] .cls-num').all_inner_texts()
        assert cells(0) == ['3', '1'], cells(0)            # annotations, images
        assert cells(rare_id) == ['1', '1'], cells(rare_id)
        expect(page.locator('#clsKpiBoxes')).to_have_text(str(stats['total_boxes']))
        expect(page.locator('#clsKpiImages')).to_contain_text(f"{stats['labelled_images']} / {stats['total_images']}")
        assert stats['labelled_images'] == 1, stats
        expect(page.locator('#clsKpiClasses')).to_have_text(str(len(by_id)))
        dist = page.locator('#clsDistList li')
        expect(dist).to_have_count(len(by_id))
        assert dist.first.locator('.cls-dist-pct').inner_text() == '75%', dist.first.inner_text()
        expect(page.locator('#clsHealth')).to_contain_text('1 of 2 images have no labels yet')
        return {'stats': by_id, 'kpi_images': page.locator('#clsKpiImages').inner_text()}
    record('classes-counts-and-insights-match-server', counts_and_insights_match_server, page)

    def ux_sort_filter_menu_colour_insights():
        first_name = lambda: body.locator('.cls-name-text').first.inner_text().strip()
        # regressions caught in review: balance rows must show their names at full
        # width, and the add-class default colour must not repeat an existing one
        nm = page.locator('#clsDistList .cls-dist-name').first
        expect(nm).to_have_text('object')
        assert nm.bounding_box()['width'] > 100, nm.bounding_box()
        default = page.locator('#clsPageColor').input_value().lower()
        existing = {'#' + ''.join(f'{v:02x}' for v in c['color']) for c in page.evaluate('state.classes')}
        assert default not in existing, (default, existing)
        rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
        gap = min(sum((x - y) ** 2 for x, y in zip(rgb(default), rgb(e))) ** .5 for e in existing)
        assert gap >= 90, ('default colour too close to an existing class', default, existing, gap)
        head = lambda key: page.locator(f'#page-classes th[data-sort="{key}"]')
        # sort by annotations: desc first (biggest class on top), then asc
        head('count').locator('.cls-sort').click()
        expect(head('count')).to_have_attribute('aria-sort', 'descending')
        assert first_name() == 'object', names()
        head('count').locator('.cls-sort').click()
        expect(head('count')).to_have_attribute('aria-sort', 'ascending')
        assert first_name() == 'rare', names()                 # 1 annotation < 3
        head('name').locator('.cls-sort').click()
        expect(head('name')).to_have_attribute('aria-sort', 'ascending')
        assert names() == sorted(names(), key=str.lower), names()
        head('id').locator('.cls-sort').click()
        expect(head('id')).to_have_attribute('aria-sort', 'ascending')
        assert first_name() == 'object'
        chips = page.locator('#page-classes .cls-chip')
        # no unused classes yet: the Unused filter says so instead of a blank table
        expect(page.locator('#clsFilterUnused')).to_have_text('0')
        chips.filter(has_text='Unused').click()
        expect(body.locator('.cls-page-empty')).to_contain_text('Every class is in use')
        chips.filter(has_text='All').click()
        # ⋮ menu lists the four labelled actions
        row_of('object').locator('.cls-more').click()
        items = page.locator('.kmenu .kmenu-item')
        assert items.all_inner_texts() == ['Rename…', 'Change colour…', 'Change ID…', 'Delete class'], items.all_inner_texts()
        page.keyboard.press('Escape'); expect(page.locator('.kmenu')).to_have_count(0)
        # new classes get distinct palette colours (not all the same red)
        for nm in ('ux-colour-a', 'ux-colour-b'):
            page.locator('#clsPageName').fill(nm); page.locator('#clsPageAddBtn').click()
            expect(name_btn(nm)).to_be_visible()
        page.reload(); page.wait_for_timeout(900)            # class list comes back from the server
        colours = {c['name']: tuple(c['color']) for c in page.evaluate('state.classes')}
        assert colours['ux-colour-a'] != colours['ux-colour-b'], colours
        assert len(set(colours.values())) == len(colours), ('duplicate class colours', colours)
        # filter chips with counts (the two new classes have no annotations)
        expect(page.locator('#clsFilterUsed')).to_have_text('2')
        expect(page.locator('#clsFilterUnused')).to_have_text('2')
        chips.filter(has_text='Unused').click()
        expect(chips.filter(has_text='Unused')).to_have_attribute('aria-pressed', 'true')
        assert set(names()) == {'ux-colour-a', 'ux-colour-b'}, names()
        chips.filter(has_text='In use').click()
        assert set(names()) == {'object', 'rare'}, names()
        chips.filter(has_text='All').click()
        # insights: "Show unused" filters; a balance row jumps to and flashes its class
        page.locator('#clsHealth .cls-link[data-cls-filter="unused"]').click()
        expect(chips.filter(has_text='Unused')).to_have_attribute('aria-pressed', 'true')
        page.locator('#clsDistList [data-cls-jump]').filter(has_text='rare').click()
        expect(chips.filter(has_text='All')).to_have_attribute('aria-pressed', 'true')
        expect(row_of('rare')).to_have_class(re.compile('is-flash'))
        # "/" focuses search
        page.locator('.cls-title').click(); page.keyboard.press('/')
        expect(page.locator('#clsPageSearch')).to_be_focused()
        page.locator('#clsPageSearch').press('Escape')
        # loading placeholders while /stats is slow, never fake zeros
        held = []                                    # hold /stats, check the UI, then release
        page.route('**/stats*', lambda route: held.append(route))
        page.reload()
        expect(body.locator('.cls-skel').first).to_be_visible(timeout=5000)
        expect(page.locator('#clsPageSummary')).to_contain_text('counting')
        assert '0' not in [t.strip() for t in body.locator('.cls-num').all_inner_texts()]   # no fake zeros
        for route in held:                           # release BEFORE unroute (unroute auto-continues held ones)
            route.continue_()
        page.unroute('**/stats*')
        expect(body.locator('.cls-skel')).to_have_count(0, timeout=8000)
        assert row_of('object').locator('.cls-num').first.inner_text() == '3'
        # failure → error state with Retry, which recovers
        page.route('**/stats*', lambda route: route.abort())
        page.reload()
        expect(page.locator('#clsHealth')).to_contain_text("Couldn't load annotation counts", timeout=8000)
        assert row_of('object').locator('.cls-num').first.inner_text() == '—'
        page.unroute('**/stats*')
        page.locator('#clsHealth [data-cls-retry]').click()
        expect(row_of('object').locator('.cls-num').first).to_have_text('3', timeout=8000)
        # clean up the two classes so later checks see the seeded state
        for nm in ('ux-colour-a', 'ux-colour-b'):
            cid = int(row_of(nm).get_attribute('data-id'))
            r = page.request.fetch(proj + '/classes', method='DELETE', headers=auth, data={'id': cid})
            assert r.ok, r.text()
        page.reload(); page.wait_for_timeout(900)
        page.set_viewport_size(dict(width=1440, height=900))
        page.wait_for_timeout(200)
        page.screenshot(path=str(OUT / 'classes-ux-desktop.png'))
        return {'colours': colours}
    record('classes-ux-sort-filter-menu-colour-insights-loading', ux_sort_filter_menu_colour_insights, page)

    def change_class_id_swap_and_shift():
        rx = page.locator('#clsReindexModal')
        label_ids = lambda: sorted(b['class_id'] for b in page.request.get(
            proj + '/annotations', headers=auth, params={'path': seed}).json()['bboxes'])
        assert label_ids() == [0, 0, 0, rare_id], label_ids()
        # swap: rare takes 0, object takes rare's old ID
        row_action(page.locator(f'#clsPageTableBody tr[data-id="{rare_id}"]'), 'Change ID')
        expect(rx).to_be_visible()
        expect(page.locator('#clsReindexCurrent')).to_have_text(f'ID {rare_id}')
        assert page.locator('#clsReindexApply').is_disabled()            # nothing chosen yet
        page.locator('#clsReindexTarget').select_option('0')
        expect(page.locator('#clsReindexModes')).to_be_visible()
        expect(page.locator('#clsReindexSwapDesc')).to_contain_text(f'object → {rare_id}')
        expect(page.locator('#clsReindexPreview')).to_contain_text('4 label lines')   # 3 object + 1 rare
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / 'classes-change-id-popup.png'))
        page.locator('#clsReindexApply').click()
        expect(rx).to_be_hidden(timeout=10000)
        assert label_ids() == [0, rare_id, rare_id, rare_id], label_ids()   # rewritten on disk
        expect(page.locator('#clsPageTableBody tr[data-id="0"] .cls-name-text')).to_have_text('rare')
        # shift back: rare to ID 1 → object shifts down to 0
        row_action(page.locator('#clsPageTableBody tr[data-id="0"]'), 'Change ID')
        page.locator('#clsReindexTarget').select_option(str(rare_id))
        page.locator('input[name="clsReindexMode"][value="shift"]').check()
        expect(page.locator('#clsReindexShiftDesc')).to_contain_text('object → 0')
        expect(page.locator('#clsReindexPreview')).to_contain_text('label lines')
        page.locator('#clsReindexApply').click()
        expect(rx).to_be_hidden(timeout=10000)
        assert label_ids() == [0, 0, 0, rare_id], label_ids()
        expect(page.locator('#clsPageTableBody tr[data-id="0"] .cls-name-text')).to_have_text('object')
        # Escape closes without changing anything
        row_action(page.locator('#clsPageTableBody tr[data-id="0"]'), 'Change ID')
        page.locator('#clsReindexTarget').select_option(str(rare_id))
        page.keyboard.press('Escape'); expect(rx).to_be_hidden()
        assert label_ids() == [0, 0, 0, rare_id], label_ids()
        return {'labels': label_ids()}
    record('classes-change-id-swap-shift-rewrites-labels', change_class_id_swap_and_shift, page)

    def add_and_duplicate():
        page.locator('#clsPageName').fill('truck'); page.locator('#clsPageAddBtn').click()
        expect(name_btn('truck')).to_be_visible()
        page.locator('#clsPageName').fill('TRUCK'); page.locator('#clsPageName').press('Enter')
        expect(page.locator('#clsPageAddError')).to_contain_text('already exists')
        assert names().count('truck') == 1, names()
        page.locator('#clsPageName').fill('')
        return names()
    record('classes-add-and-duplicate-rejected', add_and_duplicate, page)

    modal = page.locator('#clsRenameModal')
    inp = page.locator('#clsRenameInput')
    save = page.locator('#clsRenameSave')

    def rename_popup_shows_class_and_saves():
        name_btn('object').click()
        expect(modal).to_be_visible()
        expect(page.locator('#clsRenameOld')).to_have_text('object')     # previous name
        expect(page.locator('#clsRenameId')).to_have_text('ID 0')
        expect(page.locator('#clsRenameBoxes')).to_have_text('3')        # annotations using it
        expect(page.locator('#clsRenameImages')).to_have_text('1')       # images using it
        expect(inp).to_be_focused(); expect(inp).to_have_value('object')
        assert save.is_disabled()                                         # unchanged → no save
        inp.fill('vehicle')
        expect(page.locator('#clsRenamePreview')).to_contain_text('object')
        expect(page.locator('#clsRenamePreview')).to_contain_text('vehicle')
        assert save.is_enabled()
        save.click()
        expect(modal).to_be_hidden()
        expect(name_btn('vehicle')).to_be_visible()
        page.reload(); page.wait_for_timeout(800)
        expect(name_btn('vehicle')).to_be_visible()                       # persisted
        # the ID and its annotations are unchanged by a rename
        row = row_of('vehicle')
        assert row.get_attribute('data-id') == '0'
        assert row.locator('.cls-num').first.inner_text() == '3'
        name_btn('vehicle').click(); inp.fill('object'); inp.press('Enter')   # restore
        expect(name_btn('object')).to_be_visible()
        return names()
    record('classes-rename-popup-shows-name-id-counts-and-keeps-id', rename_popup_shows_class_and_saves, page)

    def rename_cancel_paths():
        for close in ('escape', 'cancel', 'x', 'backdrop'):
            name_btn('truck').click(); expect(modal).to_be_visible()
            inp.fill('should-not-save')
            if close == 'escape': inp.press('Escape')
            elif close == 'cancel': page.locator('#clsRenameCancel').click()
            elif close == 'x': page.locator('#clsRenameClose').click()
            else: modal.click(position={'x': 5, 'y': 5})
            expect(modal).to_be_hidden()
            expect(name_btn('truck')).to_be_visible()
        assert 'should-not-save' not in names()
        return names()
    record('classes-rename-popup-cancel-escape-x-backdrop', rename_cancel_paths, page)

    def rename_enter_and_persist():
        name_btn('truck').click(); inp.fill('lorry 2'); inp.press('Enter')
        expect(modal).to_be_hidden()
        expect(name_btn('lorry 2')).to_be_visible()
        page.reload(); page.wait_for_timeout(800)
        expect(name_btn('lorry 2')).to_be_visible()          # persisted on the server
        return names()
    record('classes-rename-enter-saves-and-persists', rename_enter_and_persist, page)

    def rename_rejections():
        first = names()[0]
        name_btn('lorry 2').click()
        inp.fill(first.upper()); inp.press('Enter')
        expect(page.locator('#clsRenameError')).to_contain_text('already exists')
        expect(modal).to_be_visible()                        # stays open on refusal
        inp.fill('   ')
        assert save.is_disabled()                            # empty name can't be saved
        inp.press('Escape'); expect(modal).to_be_hidden()
        page.reload(); page.wait_for_timeout(800)
        expect(name_btn('lorry 2')).to_be_visible()          # server unchanged
        return names()
    record('classes-rename-duplicate-and-empty-rejected', rename_rejections, page)

    def special_characters():
        tricky = 'a "quoted" <b>bold</b> & co'
        page.locator('#clsPageName').fill(tricky); page.locator('#clsPageAddBtn').click()
        expect(name_btn(tricky)).to_be_visible()
        assert body.locator('b').count() == 0                # rendered as text, not markup
        return names()
    record('classes-special-characters-render-as-text', special_characters, page)

    def colour_and_search():
        row = row_of('lorry 2')
        row.locator('.cls-row-color input').evaluate("e=>{e.value='#3366cc';e.dispatchEvent(new Event('change',{bubbles:true}))}")
        page.wait_for_timeout(600)
        page.reload(); page.wait_for_timeout(800)
        assert 'rgb(51, 102, 204)' in row_of('lorry 2').locator('.cls-row-color').evaluate('e=>getComputedStyle(e).backgroundColor')
        page.locator('#clsPageSearch').fill('lorry')
        assert names() == ['lorry 2'], names()
        page.locator('#clsPageSearch').fill('zzz-none')
        expect(body.locator('.cls-page-empty')).to_contain_text('No classes match')
        page.locator('#clsPageSearch').fill('')
        return names()
    record('classes-colour-persists-and-search-filters', colour_and_search, page)

    def delete_with_confirm():
        before = names()
        row_action(row_of('lorry 2'), 'Delete class')
        dlg = page.locator('[role="alertdialog"]'); expect(dlg).to_be_visible()
        expect(dlg).to_contain_text('lorry 2')
        dlg.locator('.btn-secondary').click(); expect(dlg).to_have_count(0)
        assert names() == before                             # cancel keeps it
        row_action(row_of('lorry 2'), 'Delete class')
        ui_confirm(page)
        expect(name_btn('lorry 2')).to_have_count(0)
        page.reload(); page.wait_for_timeout(800)
        expect(name_btn('lorry 2')).to_have_count(0)
        return names()
    record('classes-delete-themed-confirm-cancel-and-confirm', delete_with_confirm, page)

    def export_and_sync():
        with page.expect_download() as pending:
            page.locator('#clsPageExportBtn').click()
        download = pending.value
        assert download.suggested_filename == 'classes.txt'
        assert Path(download.path()).read_text(encoding='utf-8').splitlines() == names()
        with page.expect_response(lambda r: '/classes/sync' in r.url and r.request.method == 'POST') as pending:
            page.locator('#clsPageSyncBtn').click()
        assert pending.value.ok
        return 'Downloaded names match visible classes; sync returned success'
    record('classes-export-content-and-sync', export_and_sync, page)

    def rename_network_failure():
        name_btn('object').click()
        page.route('**/classes/rename*', lambda route: route.abort())
        try:
            inp.fill('unsaved name'); inp.press('Enter')
            expect(page.locator('#clsRenameError')).to_contain_text('network error')
            expect(modal).to_be_visible()
            inp.press('Escape')
        finally:
            page.unroute('**/classes/rename*')
        page.reload(); page.wait_for_timeout(800)
        expect(name_btn('object')).to_be_visible()
        return 'Failed rename kept the editor open; original name persists after reload'
    record('classes-rename-network-error-preserves-name', rename_network_failure, page)

    for mode in ('light', 'dark'):
        for width, height, device in ((1440, 900, 'desktop'), (768, 1024, 'tablet'), (390, 844, 'mobile')):
            def look(mode=mode, width=width, height=height, device=device):
                page.set_viewport_size(dict(width=width, height=height))
                page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}', mode)
                page.wait_for_timeout(5500)  # let prior workflow success toasts expire for the layout evidence
                page.screenshot(path=str(OUT / f'classes-page-{mode}-{device}.png'))
                r = page.locator('.cls-page').bounding_box()
                main = page.locator('.cls-main').bounding_box(); side = page.locator('.cls-side').bounding_box()
                area = page.locator('#page-classes').bounding_box()
                if device == 'desktop':
                    # uses the working width, insights panel beside the table
                    assert r['width'] >= area['width'] - 2 * 24 - 2, ('page not using the width', r, area)
                    assert side['x'] >= main['x'] + main['width'], ('panel not beside table', main, side)
                else:
                    assert side['y'] >= main['y'] + main['height'] - 1, ('panel not below table', main, side)
                over = page.evaluate('document.querySelector("#page-classes").scrollWidth > document.querySelector("#page-classes").clientWidth + 1')
                assert not over, 'Classes page overflows horizontally'
                for sel in ('#clsPageAddBtn', '#clsPageSyncBtn', '#clsPageExportBtn', '#clsPageSearch'):
                    b = page.locator(sel).bounding_box()
                    assert b and b['x'] >= 0 and b['x'] + b['width'] <= width + 1, (sel, b)
                for sel in ('.cls-name', '.cls-more', '.cls-col-num', '.cls-col-count', '.cls-col-id'):
                    for item in body.locator(sel).all():
                        b = item.bounding_box()
                        assert b and b['x'] >= 0 and b['x'] + b['width'] <= width + 1, (sel, b)
                name_btn('object').click()
                expect(modal).to_be_visible(); expect(inp).to_be_focused()
                mb = page.locator('#clsRenameModal .modal').bounding_box()
                assert mb['x'] >= 0 and mb['x'] + mb['width'] <= width + 1 and mb['y'] >= 0, ('popup off-screen', mb)
                inp.fill('object edited')
                page.wait_for_timeout(450)   # let the open animation finish before capturing
                page.screenshot(path=str(OUT / f'classes-rename-popup-{mode}-{device}.png'))
                inp.press('Enter')
                expect(name_btn('object edited')).to_be_visible()
                name_btn('object edited').click()
                inp.fill('object'); inp.press('Enter')
                expect(name_btn('object')).to_be_visible()
                row_action(row_of('object'), 'Delete class')
                dlg = page.locator('[role="alertdialog"]'); expect(dlg).to_be_visible()
                dlg.locator('.btn-secondary').click(); expect(dlg).to_have_count(0)
                return {'page': r}
            record(f'classes-layout-{mode}-{device}', look, page)

    def classes_navigation():
        page.set_viewport_size(dict(width=1440, height=900))
        page.evaluate("location.hash='annotate'")
        expect(page.locator('#page-annotate')).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('.ah-center')).to_be_visible()
        page.evaluate("location.hash='classes'")
        expect(page.locator('#page-classes')).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('.ah-center')).not_to_be_visible()
        expect(name_btn('object')).to_be_visible()
        return 'Annotation header restored on Annotate, compact project header on Classes'
    record('classes-navigation-restores-annotation-header', classes_navigation, page)


def versions_page(page):
    """Versions section on seeded data: list/detail content vs the API, split
    colours from tokens, keyboard selection, copy path, ⋮ menu, download,
    delete (cancel + confirm + empty state), honest wizard notes, and the
    tablet/phone list↔detail flow in both themes."""
    import io
    from PIL import Image
    login(page)
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=BASE)
    proj = BASE + '/api/workspaces/1/projects/audit-project'
    url = BASE + '/pages/annotate?workspace_id=1&project=audit-project#versions'
    page.goto(url); page.wait_for_timeout(500)
    auth = {'Authorization': 'Bearer ' + page.evaluate('localStorage.getItem("am_token")')}
    for i, col in enumerate(('green', 'blue', 'red', 'gray', 'purple')):
        buf = io.BytesIO(); Image.new('RGB', (64, 48), col).save(buf, format='PNG')
        assert page.request.post(proj + '/upload', headers=auth, multipart={
            'file': {'name': f'ver{i}.png', 'mimeType': 'image/png', 'buffer': buf.getvalue()}}).ok
    box = dict(class_id=0, x_center=.5, y_center=.5, width=.2, height=.2)
    for m in page.request.get(proj + '/media', headers=auth).json()['media'][:4]:
        assert page.request.post(proj + '/annotations', headers=auth, data={'path': m['path'], 'bboxes': [box]}).ok
    for b in page.request.get(proj + '/uploads', headers=auth).json():
        assert page.request.post(proj + f"/uploads/{b['upload_id']}/add_to_dataset", headers=auth,
                                 data={'train': .6, 'val': .2, 'test': .2}).ok
    for name, note, pp in (('v1 baseline', '', {}),
                           ('v2 more data', 'Added night frames', {'resize_mode': 'stretch', 'resize_w': 640, 'resize_h': 640})):
        r = page.request.post(proj + '/versions', headers=auth, data={
            'name': name, 'note': note, 'split_ratio': {'train': .5, 'val': .25, 'test': .25, 'shuffle': False},
            'preprocessing': pp, 'augmentations': [{'type': 'flip_h'}] if pp else []})
        assert r.ok, r.text()
    api = lambda: page.request.get(proj + '/versions', headers=auth).json()
    page.reload(); page.wait_for_timeout(900)
    items = page.locator('#vsListScroll .ver-item')
    detail = page.locator('#vsDetailPane')
    colour = lambda var: page.evaluate('''(v)=>{const d=document.createElement('div');d.style.background=`var(${v})`;
        document.body.append(d);const c=getComputedStyle(d).backgroundColor;d.remove();return c}''', var)

    def list_and_detail():
        expect(items).to_have_count(2)
        expect(page.locator('#vsCount')).to_have_text('2')
        expect(items.first).to_contain_text('v2 more data'); expect(items.first.locator('.ver-latest')).to_be_visible()
        expect(items.nth(1).locator('.ver-latest')).to_have_count(0)
        expect(detail.locator('.ver-placeholder')).to_contain_text('Select a version')
        seg = items.first.locator('.ver-split .is-train')
        assert seg.evaluate('e=>getComputedStyle(e).backgroundColor') == colour('--split-train')
        assert items.first.locator('.ver-split .is-val').evaluate('e=>getComputedStyle(e).backgroundColor') == colour('--split-val')
        # keyboard: focus first, ArrowDown, Enter selects v1
        items.first.focus(); page.keyboard.press('ArrowDown'); page.keyboard.press('Enter')
        expect(items.nth(1)).to_have_attribute('aria-selected', 'true')
        expect(detail.locator('.ver-card-name')).to_have_text('v1 baseline')
        expect(detail.locator('.ver-section-title', has_text='Settings recorded')).to_have_count(0)   # nothing recorded
        items.first.click()
        v2 = next(v for v in api() if v['name'] == 'v2 more data')
        sc = v2['splits']
        kpis = detail.locator('.ver-kpi-n').all_inner_texts()
        assert kpis == [str(v2['total_images']), str(v2['num_classes']), str(sc.get('train', 0)),
                        str(sc.get('val', sc.get('valid', 0))), str(sc.get('test', 0))], (kpis, v2)
        expect(detail.locator('.ver-note')).to_contain_text('Added night frames')
        expect(detail.locator('.ver-path code')).to_have_text(re.compile(r'^Versions/'))
        expect(detail.locator('.ver-honest')).to_contain_text('README only')
        expect(detail.locator('.ver-folder-size')).to_contain_text('files', timeout=5000)
        detail.locator('[data-ver-act="copy"]').click()
        assert page.evaluate('navigator.clipboard.readText()') == v2['folder_path']
        return {'kpis': kpis}
    record('versions-list-detail-match-api-keyboard-copy', list_and_detail, page)

    def menu_download_delete():
        items.nth(1).locator('.ver-more').click()
        assert page.locator('.kmenu .kmenu-item').all_inner_texts() == ['Download ZIP', 'Copy folder path', 'Delete version']
        with page.expect_download() as dl:
            page.locator('.kmenu .kmenu-item', has_text='Download ZIP').click()
        assert dl.value.suggested_filename.endswith('.zip'), dl.value.suggested_filename
        items.nth(1).locator('.ver-more').click()
        page.locator('.kmenu .kmenu-item', has_text='Delete version').click()
        dlg = page.locator('[role="alertdialog"]'); expect(dlg).to_contain_text('v1 baseline')
        dlg.locator('.btn-secondary').click(); expect(dlg).to_have_count(0)
        assert len(api()) == 2                                   # cancel keeps it
        items.nth(1).locator('.ver-more').click()
        page.locator('.kmenu .kmenu-item', has_text='Delete version').click()
        ui_confirm(page)
        expect(items).to_have_count(1)
        assert [v['name'] for v in api()] == ['v2 more data']
        expect(items.first.locator('.ver-badge')).to_have_text('v2')    # number stays v2 after v1 is deleted
        return [v['name'] for v in api()]
    record('versions-menu-download-delete-cancel-confirm', menu_download_delete, page)

    def honest_wizard():
        page.locator('#createVersionBtn').click()
        expect(page.locator('#vwOverlay')).to_be_visible()
        for step in (3, 4):
            while not page.locator(f'#vwStep{step}').is_visible():
                page.locator('#vwBtnNext').click()
            expect(page.locator(f'#vwStep{step} .vw-honest')).to_contain_text('Recorded only, not applied yet')
        page.locator('#vwClose').click(); expect(page.locator('#vwOverlay')).to_be_hidden()
        return 'steps 3 and 4 say settings are recorded only'
    record('versions-wizard-says-transforms-are-recorded-only', honest_wizard, page)

    for mode in ('light', 'dark'):
        for width, height, device in ((1440, 900, 'desktop'), (768, 1024, 'tablet'), (390, 844, 'mobile')):
            def layout(mode=mode, width=width, height=height, device=device):
                page.set_viewport_size(dict(width=width, height=height))
                page.evaluate('(m)=>{localStorage.setItem("am_theme_mode",m);ThemeEngine.setThemeMode(m)}', mode)
                page.reload(); page.wait_for_timeout(900)
                expect(page.locator('.anno-header .ah-center')).to_be_hidden()      # compact header
                over = lambda: page.evaluate('(()=>{const e=document.querySelector("#page-versions");return e.scrollWidth>e.clientWidth+1})()')
                if device == 'desktop':
                    expect(items.first).to_be_visible(); items.first.click()
                    expect(detail.locator('.ver-card')).to_be_visible()
                    expect(detail.locator('.ver-back')).to_be_hidden()
                else:
                    expect(detail).to_be_hidden()                                  # list first
                    items.first.click()
                    expect(detail.locator('.ver-card')).to_be_visible()
                    expect(page.locator('#vsListScroll')).to_be_hidden()           # detail replaces list
                    page.wait_for_timeout(250)
                    page.screenshot(path=str(OUT / f'versions-detail-{mode}-{device}.png'))
                    assert not over(), 'detail overflows'
                    detail.locator('.ver-back').click()
                    expect(page.locator('#vsListScroll')).to_be_visible(); expect(detail).to_be_hidden()
                    items.first.click()
                page.wait_for_timeout(250)
                page.screenshot(path=str(OUT / f'versions-page-{mode}-{device}.png'))
                assert not over(), 'page overflows horizontally'
                return device
            record(f'versions-layout-{mode}-{device}', layout, page)

    def empty_state():
        page.set_viewport_size(dict(width=1440, height=900))
        for v in api():
            assert page.request.fetch(proj + '/versions', method='DELETE', headers=auth, data={'id': v['id']}).ok
        page.reload(); page.wait_for_timeout(900)
        expect(items).to_have_count(0)
        expect(page.locator('#vsEmptyList')).to_be_visible()
        expect(detail.locator('.ver-placeholder')).to_contain_text('No versions yet')
        detail.locator('#vsStartCreateBtn').click()
        expect(page.locator('#vwOverlay')).to_be_visible()
        page.locator('#vwClose').click()
        return 'empty list + create call to action'
    record('versions-empty-state-create-cta', empty_state, page)


CONTRAST_JS = r'''(scopeSel) => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, bot) => { const a = top[3]; return [0,1,2].map(i => top[i] * a + bot[i] * (1 - a)).concat(1); };
  const lum = c => { const v = c.slice(0, 3).map(x => { x /= 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; });
    return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => p - q); return (y + .05) / (x + .05); };
  // background actually behind an element: composite translucent layers up the tree
  const bgOf = el => { const layers = []; let unknown = false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none') unknown = true;   // images AND gradients: not decidable
      const c = parse(s.backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    const opaque = layers.length && layers[layers.length - 1][3] >= 1;
    if (!opaque) unknown = true;                 // nothing solid behind it: not decidable
    let base = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return {bg: base, unknown}; };
  const opacityOf = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const scope = scopeSel ? document.querySelector(scopeSel) : document.body;
  if (!scope) return {checked: 0, fails: []};
  const out = [], seen = new Set(); let checked = 0, skipped = 0;
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement; if (!el || seen.has(el) || !n.textContent.trim()) continue;
    seen.add(el);
    if (el.closest('script,style,noscript,option,[aria-hidden="true"],.visually-hidden,canvas,svg')) continue;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (!r.width || !r.height || s.visibility === 'hidden' || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    if (el.closest('[disabled],.disabled,:disabled')) continue;      // disabled text is exempt (WCAG 1.4.3)
    if (opacityOf(el) < 0.05) continue;                               // not actually visible
    const fill = s.webkitTextFillColor || '';
    if (/rgba\([^)]*,\s*0\)$/.test(fill) || /transparent/.test(fill)) { skipped++; continue; }   // gradient-filled text
    const {bg, unknown} = bgOf(el); if (unknown) { skipped++; continue; }   // photo/gradient behind: not decidable here
    const fg = parse(s.color); if (!fg) continue;
    const op = opacityOf(el); const shown = over([fg[0], fg[1], fg[2], fg[3] * op], bg);
    const size = parseFloat(s.fontSize), bold = +s.fontWeight >= 700;
    const need = (size >= 24 || (bold && size >= 18.66)) ? 3 : 4.5;
    const cr = ratio(shown, bg); checked++;
    if (cr + 0.005 < need) out.push({text: n.textContent.trim().slice(0, 40), sel: el.tagName.toLowerCase() +
      (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : ''),
      ratio: +cr.toFixed(2), need, color: s.color, opacity: +op.toFixed(2), bg: 'rgb(' + bg.slice(0, 3).map(Math.round).join(',') + ')'});
  }
  return {checked, skipped, fails: out};
}'''

CONTRAST_THEMES = (('light', None), ('dark', None), ('custom-dark', ('#1e1e24', '#e4e4e7')), ('custom-light', ('#f4efe6', '#2b2620')),
                   ('dark-midnight', 'style'), ('dark-navy', 'style'), ('dark-carbon', 'style'))


def set_theme_storage(page, name, custom):
    """Store a theme the way Settings does: light/dark, a custom (bg, text)
    pair, or a dark style ('dark-<style>', custom == 'style')."""
    page.evaluate('''([name, custom]) => {
        localStorage.removeItem('am_dark_style');
        if (custom === 'style') {
            localStorage.setItem('am_theme_mode', 'dark');
            localStorage.setItem('am_dark_style', name.slice(5));
            localStorage.removeItem('am_custom_bg'); localStorage.removeItem('am_custom_text');
        } else if (custom) {
            localStorage.setItem('am_theme_mode', 'custom');
            localStorage.setItem('am_custom_bg', custom[0]); localStorage.setItem('am_custom_text', custom[1]);
        } else {
            localStorage.setItem('am_theme_mode', name);
            localStorage.removeItem('am_custom_bg'); localStorage.removeItem('am_custom_text');
        }
        localStorage.removeItem('am_accent_color');
    }''', [name, custom])


def design_system_contrast(page):
    """Every visible text element on every page (and the Versions wizard,
    rename and kebab popups) in light, dark and two custom themes: text colour
    incl. opacity vs the real background behind it, against WCAG AA (4.5:1,
    3:1 large). Failures are listed by element so root causes can be fixed in
    tokens, not page by page. Result counts are the evidence."""
    def apply_theme(name, custom):
        set_theme_storage(page, name, custom)

    def scan(name, scope=None):
        page.wait_for_timeout(350)
        return page.evaluate(CONTRAST_JS, scope)

    logged = False
    for route, label, auth_needed in DS_PAGES:
        if auth_needed and not logged:
            login(page); logged = True
        for theme, custom in CONTRAST_THEMES:
            def check(route=route, label=label, theme=theme, custom=custom):
                page.set_viewport_size(dict(width=1440, height=900))
                page.goto(BASE + route); apply_theme(theme, custom); page.reload()
                page.wait_for_load_state('networkidle'); page.add_style_tag(content=DS_FREEZE)
                res = scan(label)
                extra = {}
                if label == 'versions':
                    page.locator('#createVersionBtn').click()
                    for step in range(1, 6):
                        r2 = scan(label, '#vwDrawer')
                        res['checked'] += r2['checked']; res['skipped'] += r2['skipped']
                        res['fails'] += [dict(f, where=f'wizard{step}') for f in r2['fails']]
                        if step < 5:
                            page.locator('#vwBtnNext').click()
                    page.locator('#vwClose').click()
                worst = sorted(res['fails'], key=lambda f: f['ratio'])[:12]
                assert not res['fails'], f"{len(res['fails'])} of {res['checked']} text elements below AA: {worst}"
                return {'checked': res['checked'], 'skipped_undecidable': res['skipped']}
            record(f'ds-contrast-{label}-{theme}', check, page)



def version_wizard(page):
    """Create Dataset Version wizard as a centred dialog: centred and inside the
    viewport at desktop/tablet/phone, steps rail beside the content on desktop,
    Back/Continue/step-click/Esc/backdrop/close behaviour, and screenshots of
    every step in light, dark, custom-dark and custom-light
    (.audit-browser/wizard/<theme>-<size>-step<n>.png)."""
    shots = OUT / 'wizard'; shots.mkdir(exist_ok=True)
    login(page)
    url = BASE + '/pages/annotate?workspace_id=1&project=audit-project#versions'
    sizes = (('desktop', 1440, 900), ('tablet', 768, 1024), ('phone', 390, 844))

    def set_theme(name, custom):
        set_theme_storage(page, name, custom)

    def geom():
        return page.evaluate("""()=>{const d=document.getElementById('vwDrawer').getBoundingClientRect();
          const s=document.getElementById('vwSteps').getBoundingClientRect(), b=document.getElementById('vwBody').getBoundingClientRect();
          return {l:d.left,t:d.top,r:innerWidth-d.right,btm:innerHeight-d.bottom,w:d.width,h:d.height,vw:innerWidth,vh:innerHeight,
                  rail:s.width, stepsBeside: s.right<=b.left+1, docScrollX: document.documentElement.scrollWidth>innerWidth}}""")

    for theme, custom in CONTRAST_THEMES:
        for size, w, h in sizes:
            def check(theme=theme, custom=custom, size=size, w=w, h=h):
                page.set_viewport_size(dict(width=w, height=h))
                page.goto(url); set_theme(theme, custom); page.reload(); page.wait_for_load_state('networkidle')
                page.locator('#createVersionBtn').click()
                expect(page.locator('#vwOverlay')).to_be_visible(); page.wait_for_timeout(400)
                g = geom()
                assert g['l'] >= -0.5 and g['r'] >= -0.5 and g['t'] >= -0.5 and g['btm'] >= -0.5, f'dialog leaves the viewport {g}'
                if size != 'phone':
                    assert abs(g['l'] - g['r']) <= 2, f'not horizontally centred {g}'
                    assert abs(g['t'] - g['btm']) <= 2, f'not vertically centred {g}'
                if size == 'desktop':
                    assert g['stepsBeside'], f'steps rail should sit beside the content on desktop {g}'
                for step in range(1, 6):
                    expect(page.locator(f'#vwStep{step}')).to_be_visible()
                    page.screenshot(path=str(shots / f'{theme}-{size}-step{step}.png'))
                    if step < 5:
                        page.locator('#vwBtnNext').click(); page.wait_for_timeout(250)
                expect(page.locator('#vwBtnCreate')).to_be_visible()
                page.locator('.vw-step[data-step="2"]').click(); expect(page.locator('#vwStep2')).to_be_visible()
                page.locator('#vwBtnBack').click(); expect(page.locator('#vwStep1')).to_be_visible()
                page.keyboard.press('Escape'); expect(page.locator('#vwOverlay')).to_be_hidden(timeout=2000)
                page.locator('#createVersionBtn').click(); expect(page.locator('#vwOverlay')).to_be_visible()
                page.locator('#vwClose').click(); expect(page.locator('#vwOverlay')).to_be_hidden(timeout=2000)
                return {k: round(v) if isinstance(v, float) else v for k, v in g.items()}
            record(f'wizard-{theme}-{size}', check, page)



DARK_STYLE_BG = {'classic': '#07070d', 'midnight': '#060818', 'navy': '#081221', 'carbon': '#0a0a0a'}
DARK_STYLE_ACCENT = {'classic': '#00e5b0', 'midnight': '#3a66f7', 'navy': '#1ec97e', 'carbon': '#146ef5'}


def dark_styles(page):
    """Theme Settings → Dark style: picker shown only in Dark Mode, choosing a
    style recolours the token layer (bg + accent) and drops an old accent, the
    choice reaches every page before first paint, a later accent still wins
    with readable --accent-text, light/custom ignore the style, Reset restores
    Classic. Screenshots .audit-browser/dark-styles/<style>-<page>.png."""
    shots = OUT / 'dark-styles'; shots.mkdir(exist_ok=True)
    login(page)
    page.set_viewport_size(dict(width=1440, height=900))
    tok = """(n)=>{const cs=getComputedStyle(document.documentElement);
        const hex=v=>{v=v.trim(); if(v[0]==='#') return v.toLowerCase();
          const m=v.match(/\d+/g); return m?'#'+m.slice(0,3).map(x=>(+x).toString(16).padStart(2,'0')).join(''):v};
        return Object.fromEntries(n.map(k=>[k,hex(cs.getPropertyValue(k))]))}"""
    ratio = """()=>{const cs=getComputedStyle(document.documentElement);
        const rgb=v=>{v=v.trim(); if(v[0]==='#') return [1,3,5].map(i=>parseInt(v.slice(i,i+2),16)); return v.match(/\d+(\.\d+)?/g).slice(0,3).map(Number)};
        const lin=c=>{c/=255;return c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4)}, L=c=>.2126*lin(c[0])+.7152*lin(c[1])+.0722*lin(c[2]);
        const a=L(rgb(cs.getPropertyValue('--accent-text'))), worst=Math.min(...['--bg','--surface','--panel','--card','--card2','--card3']
          .map(k=>{const b=L(rgb(cs.getPropertyValue(k)));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)}));
        return Math.round(worst*100)/100}"""

    def open_theme_tab():
        page.goto(BASE + '/settings'); page.wait_for_load_state('networkidle')
        page.locator('#nav-btn-theme').click()

    def picker_only_in_dark():
        set_theme_storage(page, 'dark', None); open_theme_tab()
        expect(page.locator('#dark-style-row')).to_be_visible()
        expect(page.locator('.dsty-opt')).to_have_count(4)
        expect(page.locator('.dsty-opt[data-style="classic"]')).to_have_class(re.compile('active'))
        page.locator('.dsty-opt[data-style="midnight"]').click(); page.wait_for_timeout(300)
        page.locator('#panel-theme').screenshot(path=str(shots / 'picker-midnight.png'))
        page.locator('.dsty-opt[data-style="classic"]').click()
        page.locator('#theme-mode-light').click()
        expect(page.locator('#dark-style-row')).to_be_hidden()
        page.locator('#theme-mode-custom').click()
        expect(page.locator('#dark-style-row')).to_be_hidden()
        page.locator('#theme-mode-dark').click()
        expect(page.locator('#dark-style-row')).to_be_visible()
        return 'shown for Dark only'
    record('dark-styles-picker-only-in-dark-mode', picker_only_in_dark, page)

    for style in ('midnight', 'navy', 'carbon', 'classic'):
        def choose(style=style):
            set_theme_storage(page, 'dark', None)
            page.evaluate("localStorage.setItem('am_accent_color','#ff4081')")   # an old accent pick
            open_theme_tab()
            page.locator(f'.dsty-opt[data-style="{style}"]').click()
            expect(page.locator(f'.dsty-opt[data-style="{style}"]')).to_have_attribute('aria-checked', 'true')
            attr = page.evaluate("document.documentElement.getAttribute('data-dark-style')")
            assert attr == (None if style == 'classic' else style), attr
            assert page.evaluate("localStorage.getItem('am_dark_style')") == style
            assert page.evaluate("localStorage.getItem('am_accent_color')") is None, 'old accent should be dropped'
            t = page.evaluate(tok, ['--bg', '--accent'])
            assert t == {'--bg': DARK_STYLE_BG[style], '--accent': DARK_STYLE_ACCENT[style]}, t
            # reaches every page, applied before first paint (checked at DOMContentLoaded)
            seen = {}
            for route, label, auth_needed in DS_PAGES:
                page.goto(BASE + route, wait_until='domcontentloaded')
                first = page.evaluate(tok, ['--bg'])['--bg']
                page.wait_for_load_state('networkidle')
                body = page.evaluate("getComputedStyle(document.body).backgroundColor")
                assert first == DARK_STYLE_BG[style], (label, first)
                seen[label] = body
                if label in ('dashboard', 'annotate', 'versions', 'settings', 'login'):
                    page.add_style_tag(content=DS_FREEZE)
                    page.screenshot(path=str(shots / f'{style}-{label}.png'))
            return {'pages': len(seen), 'accent_text_worst_ratio': page.evaluate(ratio)}
        record(f'dark-styles-choose-{style}-applies-everywhere', choose, page)

    def accent_after_style():
        set_theme_storage(page, 'dark-midnight', 'style'); open_theme_tab()
        page.locator('.color-circle[title="Amber Gold"]').click()
        t = page.evaluate(tok, ['--bg', '--accent'])
        assert t['--bg'] == DARK_STYLE_BG['midnight'] and t['--accent'] == '#ffb020', t
        r = page.evaluate(ratio)
        assert r >= 4.5, f'accent text {r}:1 on midnight surfaces'
        page.goto(BASE + '/'); page.wait_for_load_state('networkidle')
        assert page.evaluate(tok, ['--accent'])['--accent'] == '#ffb020'
        assert page.evaluate(ratio) >= 4.5
        return {'accent_text_ratio': r}
    record('dark-styles-later-accent-wins-and-stays-readable', accent_after_style, page)

    def light_and_custom_ignore_style():
        out = {}
        for name, custom, bg in (('light', None, '#f7f9fb'), ('custom', ('#1e1e24', '#e4e4e7'), '#1e1e24')):
            set_theme_storage(page, name, custom)
            page.evaluate("localStorage.setItem('am_dark_style','midnight')")
            page.goto(BASE + '/'); page.wait_for_load_state('networkidle')
            got = page.evaluate(tok, ['--bg'])['--bg']
            assert got == bg, (name, got)
            out[name] = got
        return out
    record('dark-styles-ignored-in-light-and-custom', light_and_custom_ignore_style, page)

    def reset_restores_classic():
        set_theme_storage(page, 'dark-carbon', 'style'); open_theme_tab()
        page.get_by_role('button', name='Reset Theme').click()
        ui_confirm(page)
        expect(page.locator('.dsty-opt[data-style="classic"]')).to_have_attribute('aria-checked', 'true')
        assert page.evaluate("localStorage.getItem('am_dark_style')") is None
        assert page.evaluate(tok, ['--bg'])['--bg'] == DARK_STYLE_BG['classic']
        return 'classic'
    record('dark-styles-reset-theme-restores-classic', reset_restores_classic, page)

DS_INVENTORY_JS = r'''() => {
  const root = getComputedStyle(document.documentElement);
  const fs = new Set(); for (const n of [8,9,10,11,12,13,14,15,16,17,18,20,22,24,26,28,30,32,36,40,48,56])
    fs.add(Math.round(parseFloat(root.getPropertyValue('--fs-'+n)) || n*1));
  const sans = root.getPropertyValue('--font-sans').split(',')[0].replace(/['"]/g,'').trim().toLowerCase();
  const mono = root.getPropertyValue('--font-mono').split(',')[0].replace(/['"]/g,'').trim().toLowerCase();
  const sel = 'button,a[href],input,select,textarea,[role="button"],[role="tab"],[role="switch"],[role="checkbox"],[data-tooltip],.btn,.modal,.badge,.card,table,.kmenu';
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0; };
  const rows = [...document.querySelectorAll(sel)].filter(vis).map(e => {
    const s = getComputedStyle(e);
    const fam = s.fontFamily.split(',')[0].replace(/['"]/g,'').trim().toLowerCase();
    const kind = e.matches('input[type=checkbox],[role=checkbox]') ? 'checkbox'
      : e.matches('input[type=radio]') ? 'radio' : e.matches('input[type=range]') ? 'range'
      : e.matches('input[type=color]') ? 'color' : e.matches('select') ? 'select'
      : e.matches('input,textarea') ? 'input' : e.matches('a') ? 'link'
      : e.matches('[role=tab]') ? 'tab' : e.matches('table') ? 'table'
      : e.matches('.modal') ? 'modal' : e.matches('.badge') ? 'badge' : e.matches('.card') ? 'card' : 'button';
    return {kind, id: e.id, cls: (typeof e.className === 'string' ? e.className : '').split(/\s+/).filter(Boolean).slice(0,3).join('.'),
      shared: e.matches('.btn,.form-input,.form-select,.form-textarea,.ui-tab,.badge,.card,.modal,.ui-table,.kmenu-btn,.kmenu-item'),
      fontOk: fam === sans || fam === mono || /awesome/.test(fam),
      sizeOk: fs.has(Math.round(parseFloat(s.fontSize))),
      sig: [kind, Math.round(e.getBoundingClientRect().height), s.borderRadius, s.fontSize, s.fontWeight].join('|')};
  });
  return rows;
}'''


def design_system_inventory(page):
    """Every visible interactive element on every page and theme: does it use a
    shared component class, the token font family and an on-scale size?
    Counts distinct button 'shapes' so consistency is measured, not asserted."""
    logged = False
    for route, name, auth_needed in DS_PAGES:
        if auth_needed and not logged:
            login(page); logged = True
        for mode in ('light', 'dark'):
            def inv(route=route, name=name, mode=mode):
                page.set_viewport_size(dict(width=1440, height=900))
                _ds_open(page, route, mode)
                rows = page.evaluate(DS_INVENTORY_JS)
                bad_font = [r for r in rows if not r['fontOk']]
                bad_size = [r for r in rows if not r['sizeOk']]
                buttons = [r for r in rows if r['kind'] == 'button']
                summary = dict(elements=len(rows), shared_class=sum(r['shared'] for r in rows),
                               buttons=len(buttons), button_shared=sum(r['shared'] for r in buttons),
                               distinct_button_shapes=len({r['sig'] for r in buttons}),
                               kinds={k: sum(1 for r in rows if r['kind'] == k) for k in sorted({r['kind'] for r in rows})},
                               shapes=sorted({r['sig']+' :: '+(r['cls'] or r['id']) for r in buttons}),
                               off_font=[(r['kind'], r['id'] or r['cls']) for r in bad_font][:10],
                               off_scale_size=[(r['kind'], r['id'] or r['cls']) for r in bad_size][:10])
                assert not bad_font, ('element font not from --font-sans/--font-mono', summary['off_font'])
                return summary
            record(f'ds-inventory-{name}-{mode}', inv, page)


def project_header_scope(page):
    login(page)
    url = BASE + '/pages/annotate?workspace_id=1&project=audit-project'
    page.goto(url + '#annotate')
    page.wait_for_timeout(600)
    for density in ('expanded', 'compact'):
        for theme in ('light', 'dark'):
            for width, height in ((1440, 900), (768, 1024), (390, 844)):
                def check(density=density, theme=theme, width=width, height=height):
                    page.set_viewport_size(dict(width=width, height=height))
                    page.evaluate('([d,t])=>{ThemeEngine.setLayoutMode(d);ThemeEngine.setThemeMode(t)}', [density, theme])
                    for section in ('upload', 'dataset', 'versions', 'classes', 'projects', 'annotate'):
                        page.evaluate('(s)=>location.hash=s', section)
                        expect(page.locator('#page-' + section)).to_have_class(re.compile(r'\bactive\b'))
                        for sel in ('.hdr-progress-wrap', '.ah-center', '#hdrSaveStatus', '.autosave-toggle', '#completeBtn', '#exportBtn'):
                            if section == 'annotate':
                                expect(page.locator(sel)).to_be_visible()
                            else:
                                expect(page.locator(sel)).to_be_hidden()
                        expect(page.locator('#projectSelect')).to_be_visible()
                        expect(page.locator('#user-menu')).to_be_visible()
                        if section == 'upload':
                            page.wait_for_timeout(250)
                            h = page.locator('#annoHeader').bounding_box()
                            assert h['height'] <= 53, h
                            page.screenshot(path=str(OUT / f'upload-header-{density}-{theme}-{width}.png'))
                    return 'Five project sections hide editor state; Annotate restores it; switcher/account retained'
                record(f'header-scope-{density}-{theme}-{width}', check, page)
    page.goto(url + '#upload')
    expect(page.locator('.ah-center')).to_be_hidden()
    page.reload()
    expect(page.locator('.ah-center')).to_be_hidden()


def compact_sidebar(page):
    login(page)
    page.goto(BASE + '/settings')
    page.locator('#nav-btn-layout').click()
    page.locator('#layout-mode-compact').click()
    assert page.evaluate("localStorage.getItem('am_layout_mode')") == 'compact'
    page.goto(BASE + '/pages/annotate?workspace_id=1&project=audit-project#annotate')
    page.wait_for_timeout(800)
    for density in ('compact', 'expanded'):
        for theme in ('light', 'dark'):
            for width, height in ((1440, 900), (768, 1024), (390, 844)):
                def check(density=density, theme=theme, width=width, height=height):
                    page.set_viewport_size(dict(width=width, height=height))
                    page.evaluate('([d,t])=>{ThemeEngine.setLayoutMode(d);ThemeEngine.setThemeMode(t)}', [density, theme])
                    page.wait_for_timeout(400)
                    # The panel can be automatically collapsed on narrow screens.
                    if 'collapsed' in (page.locator('#sidebarRight').get_attribute('class') or ''):
                        page.locator('#rsbRestoreTab').click()
                        page.wait_for_timeout(350)
                    page.screenshot(path=str(OUT / f'sidebar-{density}-{theme}-{width}.png'))
                    header = page.locator('.anno-header').bounding_box()
                    tabs = page.locator('#sidebarRight .rp-tabs').bounding_box()
                    assert tabs['y'] >= header['y'] + header['height'] - 1, {'header': header, 'tabs': tabs}
                    for tab in ('labels', 'props', 'raw', 'comments'):
                        button = page.locator(f'.rp-tab[data-rpt="{tab}"]')
                        button.click()
                        expect(page.locator('#rpt-' + tab)).to_have_class(re.compile(r'\bactive\b'))
                        assert button.evaluate('e=>e.scrollWidth<=e.clientWidth+1 && e.scrollHeight<=e.clientHeight+1')
                    page.locator('.rp-tab[data-rpt="labels"]').click()
                    page.locator('#rightSbToggle').click()
                    page.locator('#rsbRestoreTab').click()
                    expect(page.locator('#sidebarRight')).not_to_have_class(re.compile(r'\bcollapsed\b'))
                    return {'header': header, 'tabs': tabs}
                record(f'sidebar-{density}-{theme}-{width}', check, page)


def main():
    OUT.mkdir(exist_ok=True)
    phase = sys.argv[1] if len(sys.argv)>1 else 'probe'
    try:
        urllib.request.urlopen(BASE+'/health',timeout=1)
    except Exception:
        pass
    else:
        raise RuntimeError('Port 5055 already occupied; refusing to test an unknown server')
    log = (OUT / 'server.log').open('w',encoding='utf-8')
    environment = os.environ.copy()
    try:
        import imageio_ffmpeg
        source=Path(imageio_ffmpeg.get_ffmpeg_exe())
        binary=ROOT/'.audit-tools/bin/ffmpeg.exe'
        binary.parent.mkdir(exist_ok=True)
        if not binary.exists():
            shutil.copy2(source,binary)
        environment['PATH']=str(binary.parent)+os.pathsep+environment.get('PATH','')
    except ImportError:
        pass
    server = subprocess.Popen([sys.executable,str(ROOT/'scripts/audit_server.py'),'--fixtures',str(OUT/'fixtures.json')],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,env=environment)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE+'/health',timeout=1)
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError('Audit server exited; inspect server.log')
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context = browser.new_context(viewport=dict(width=1440,height=900),accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(7000)
            watch(page)
            if phase == 'probe':
                probe(page)
            elif phase == 'auth':
                auth(page)
            elif phase == 'dashboard':
                dashboard(page)
            elif phase == 'settings':
                settings(page)
            elif phase == 'compact-sidebar':
                compact_sidebar(page)
            elif phase == 'header-scope':
                project_header_scope(page)
            elif phase == 'project':
                project(page)
            elif phase == 'members':
                members(page)
            elif phase == 'ai':
                ai(page)
            elif phase == 'media':
                media(page)
            elif phase == 'nav-theme':
                navigation_themes(page)
            elif phase == 'ds-snapshots':
                design_system_snapshots(page)
            elif phase == 'ds-propagation':
                design_system_propagation(page)
            elif phase == 'ds-geometry':
                design_system_geometry(page)
            elif phase == 'ds-controls':
                design_system_controls(page)
            elif phase == 'ds-split-card':
                design_system_split_card(page)
            elif phase == 'classes':
                classes_page(page)
            elif phase == 'versions':
                versions_page(page)
            elif phase == 'ds-contrast':
                design_system_contrast(page)
            elif phase == 'wizard':
                version_wizard(page)
            elif phase == 'dark-styles':
                dark_styles(page)
            elif phase == 'ds-inventory':
                design_system_inventory(page)
            else:
                raise ValueError('Phase not implemented yet: '+phase)
            browser.close()
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=10)
        log.close()
        (OUT / f'{phase}-results.json').write_text(json.dumps(dict(results=RESULTS,events=EVENTS),indent=2),encoding='utf-8')
        print(json.dumps(dict(phase=phase,checks=len(RESULTS),failures=[r for r in RESULTS if r['status']=='FAIL'],events=len(EVENTS)),indent=2))
    if any(row['status']=='FAIL' for row in RESULTS):
        raise SystemExit(1)
    if any(row['status']=='BLOCKED' for row in RESULTS):
        raise SystemExit(2)


if __name__=='__main__':
    main()
