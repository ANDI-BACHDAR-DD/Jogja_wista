"""Uji peramban untuk penerima tautan masuk (kontrak partner-native JogjaTrans/JogjaStay).

Menjalankan Flask sungguhan dengan basis data sementara, lalu membuka tautan di Chromium.
Dilewati otomatis bila Playwright atau Chrome tidak tersedia.
Jalankan: python3 -m pytest test_deep_link_browser.py -q
"""
import datetime
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import json

import pytest

sync_api = pytest.importorskip('playwright.sync_api')

HERE = os.path.dirname(os.path.abspath(__file__))


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _chrome():
    for name in ('google-chrome', 'chromium', 'chromium-browser'):
        path = shutil.which(name)
        if path:
            return path
    return None


@pytest.fixture(scope='module')
def server():
    tmp = tempfile.mkdtemp()
    port = _free_port()
    env = dict(os.environ, DB_PATH=os.path.join(tmp, 'w.db'), PORT=str(port), SECRET_KEY='test-secret',
               WEBHOOK_SECRET='')
    env.pop('VERCEL', None)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'app.py')], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    for _ in range(50):
        try:
            urllib.request.urlopen(base + '/api/v1/destinations', timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip('server tidak naik')
    yield base
    proc.terminate()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope='module')
def browser():
    chrome = _chrome()
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f'Chromium tidak tersedia: {exc}')
        yield b
        b.close()


def _api(base, path, payload=None):
    req = urllib.request.Request(base + '/api/v1' + path,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))


def _day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.errors = []
    pg.on('pageerror', lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def _open(page, base, query, hash_=''):
    page.goto(f'{base}/{query}{hash_}')
    page.wait_for_timeout(1500)


def _selected(page):
    return page.evaluate('_detail.selectedDate && _detail.selectedDate.date')


def test_1_valid_id_and_date_fill_detail(server, page):
    d = _day(3)
    _open(page, server, f'?destinationId=1&visitDate={d}&region=Sleman')
    assert page.evaluate('location.hash') == '#/wisata/1'
    assert page.evaluate('location.search') == ''  # query dibersihkan
    assert page.evaluate('_detail.dest.id') == 1
    assert _selected(page) == d
    assert page.locator('#btnLanjut1').is_enabled()
    assert not page.errors


def test_1b_hash_form_also_works(server, page):
    d = _day(3)
    _open(page, server, f'?visitDate={d}', '#/wisata/1')
    assert page.evaluate('_detail.dest.id') == 1
    assert _selected(page) == d


@pytest.mark.parametrize('bad', ['2026-02-30', '2026-13-01', 'besok', '20261210', ''])
def test_2_invalid_date_ignored(server, page, bad):
    _open(page, server, f'?destinationId=1&visitDate={bad}')
    assert page.evaluate('_detail.dest.id') == 1
    assert _selected(page) is None
    assert not page.errors


def test_3_past_date_ignored(server, page):
    _open(page, server, f'?destinationId=1&visitDate={_day(-2)}')
    assert page.evaluate('_detail.dest.id') == 1
    assert _selected(page) is None


def test_4_unknown_destination_shows_message_and_home(server, page):
    _open(page, server, '?destinationId=999999')
    assert page.evaluate('location.hash') in ('#/', '')
    assert 'Destinasi tidak ditemukan' in page.inner_text('body')
    assert not page.errors


@pytest.mark.parametrize('bad', ['abc', '0101', '0', '-1', '1.5', '1' * 16])
def test_5_malformed_id_ignored(server, page, bad):
    _open(page, server, f'?destinationId={bad}')
    assert page.evaluate('location.hash') in ('#/', '')
    assert page.evaluate('location.search') == ''
    assert not page.errors


def test_6_extra_params_ignored_and_not_kept(server, page):
    _open(page, server, f'?destinationId=1&visitDate={_day(3)}&token=abc&bookingId=RT-123&guests=9')
    assert page.evaluate('location.search') == ''
    assert 'token' not in page.url and 'RT-123' not in page.url
    assert page.evaluate('_detail.dest.id') == 1


def test_7_login_keeps_destination_and_date(server, page):
    d = _day(4)
    email = f'dl{int(time.time())}@test.com'
    _api(server, '/auth/register', {'name': 'Uji Tautan', 'email': email, 'password': 'Passw0rd!123'})
    _open(page, server, f'?destinationId=1&visitDate={d}')
    assert _selected(page) == d
    page.click('#btnLanjut1')
    page.wait_for_function("location.hash === '#/masuk'")
    page.fill('#lEmail', email)
    page.fill('#lPass', 'Passw0rd!123')
    page.click('#btnLogin')
    page.wait_for_function("location.hash === '#/wisata/1'")
    page.wait_for_timeout(1200)
    assert _selected(page) == d


def test_8_no_params_behaves_as_before(server, page):
    _open(page, server, '')
    assert page.evaluate('location.hash') in ('#/', '')
    assert page.evaluate('_inbound') is None
    assert not page.errors


def test_9_opening_link_creates_no_booking(server, page):
    before = _api(server, '/destinations')
    _open(page, server, f'?destinationId=1&visitDate={_day(3)}')
    assert page.evaluate("getToken() || ''") == ''  # tidak login → tidak mungkin membuat pesanan
    assert page.evaluate('_detail.step') == 1
    assert _api(server, '/destinations') == before


def test_10_inbound_not_carried_to_other_destination(server, page):
    _open(page, server, f'?destinationId=1&visitDate={_day(3)}')
    page.evaluate("location.hash = '#/wisata/2'")
    page.wait_for_timeout(1200)
    assert page.evaluate('_detail.dest.id') == 2
    assert _selected(page) is None
