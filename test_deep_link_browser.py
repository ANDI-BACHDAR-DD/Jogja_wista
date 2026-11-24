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


# ───────── Tautan keluar ke JogjaStay dan JogjaTrans (W6) ─────────

HOTEL_BASE = 'https://jogjastay-hotel-service.jogjawisata.workers.dev'
TRANS_BASE = 'https://jogjatrans-service.jogjawisata.workers.dev'


def _mock_hotels(page, hotels):
    """Tiru API hotel Wisata sehingga tes tidak memanggil JogjaStay produksi."""
    def hotels_route(route):
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'hotels': hotels}))

    def detail_route(route):
        hid = route.request.url.rsplit('/', 1)[-1].split('?')[0]
        route.fulfill(status=200, content_type='application/json', body=json.dumps(
            {'id': hid, 'name': 'Hotel Uji ' + hid, 'region': 'kabupaten-sleman', 'rooms': []}))
    page.route('**/api/v1/destinations/*/hotels', hotels_route)
    page.route('**/api/v1/integrations/hotels/*', detail_route)


def _hrefs(page, selector):
    return page.eval_on_selector_all(selector, 'els => els.map(e => e.hidden ? null : e.getAttribute("href"))')


def test_w6_links_without_date_hotel_only_trans_hidden(server, page):
    _mock_hotels(page, [{'id': 'H01', 'name': 'Hotel Satu', 'region': 'kabupaten-sleman'}])
    _open(page, server, '?destinationId=1')
    page.wait_for_selector('a[data-handoff-hotel]', state='attached')
    hotel = _hrefs(page, 'a[data-handoff-hotel]')
    # Wilayah mengikuti destinasi yang dibuka (destinasi 1 = Kota Yogyakarta); tidak ada tanggal, jadi tanpa checkIn/checkOut
    assert hotel == [f'{HOTEL_BASE}/?hotelId=H01&region=Kota+Yogyakarta']
    assert _hrefs(page, '#transHandoffLink') == [None]  # tanpa tanggal, tombol Trans tidak aktif
    assert page.is_visible('#transHandoffHint')


def test_w6_links_follow_selected_date(server, page):
    d = _day(3)
    nxt = (datetime.date.today() + datetime.timedelta(days=4)).isoformat()
    _mock_hotels(page, [{'id': 'H01', 'name': 'Hotel Satu', 'region': 'kabupaten-sleman'}])
    _open(page, server, f'?destinationId=1&visitDate={d}')
    page.wait_for_selector('a[data-handoff-hotel]', state='attached')
    hotel = _hrefs(page, 'a[data-handoff-hotel]')[0]
    assert hotel.startswith(f'{HOTEL_BASE}/?hotelId=H01&checkIn={d}&checkOut={nxt}')
    assert _hrefs(page, '#transHandoffLink') == [f'{TRANS_BASE}/mobil?startDate={d}&endDate={d}']
    link = page.locator('#transHandoffLink')
    assert link.get_attribute('target') == '_blank'
    assert 'noopener' in link.get_attribute('rel') and 'noreferrer' in link.get_attribute('rel')
    assert not page.is_visible('#transHandoffHint')
    assert not page.errors


def test_w6_hotel_link_updates_when_date_changes_and_has_no_private_data(server, page):
    _mock_hotels(page, [{'id': 'H01', 'name': 'Hotel Satu', 'region': 'kabupaten-sleman'}])
    _open(page, server, '?destinationId=1')
    page.wait_for_selector('a[data-handoff-hotel]', state='attached')
    d = _day(5)
    page.evaluate(f"selectDate('{d}', 10000, 0, false, '')")
    hotel = _hrefs(page, 'a[data-handoff-hotel]')[0]
    trans = _hrefs(page, '#transHandoffLink')[0]
    assert f'checkIn={d}' in hotel and f'startDate={d}' in trans
    for url in (hotel, trans):
        for bad in ('token', 'booking', 'email', 'phone', 'name=', 'price', 'total'):
            assert bad not in url.lower(), (bad, url)


def test_w6_invalid_hotel_id_gets_no_link(server, page):
    _mock_hotels(page, [{'id': 'H 01<x>', 'name': 'Salah', 'region': 'kabupaten-sleman'},
                        {'id': 'H02', 'name': 'Benar', 'region': 'kabupaten-bantul'}])
    _open(page, server, '?destinationId=1')
    page.wait_for_selector('a[data-handoff-hotel]', state='attached')
    links = _hrefs(page, 'a[data-handoff-hotel]')
    assert links[0] is None
    assert links[1].startswith(f'{HOTEL_BASE}/?hotelId=H02')


def test_w6_hotel_modal_has_link(server, page):
    d = _day(3)
    _mock_hotels(page, [{'id': 'H01', 'name': 'Hotel Satu', 'region': 'kabupaten-sleman'}])
    _open(page, server, f'?destinationId=1&visitDate={d}')
    page.wait_for_selector('.hotel-btn-detail')
    page.click('.hotel-btn-detail')
    page.wait_for_selector('#modalBody a[data-handoff-hotel]', state='attached')
    href = page.get_attribute('#modalBody a[data-handoff-hotel]', 'href')
    assert href.startswith(f'{HOTEL_BASE}/?hotelId=H01&checkIn={d}')


# ───────── Tautan keluar ke Itinerary (W6b) ─────────

ITINERARY_BASE = 'https://jogjatrip-itinerary.azzahraghania110.workers.dev'


def test_w6_itinerary_link_carries_destination_without_date(server, page):
    _mock_hotels(page, [])
    _open(page, server, '?destinationId=1')
    page.wait_for_selector('#itineraryHandoffLink', state='attached')
    href = _hrefs(page, '#itineraryHandoffLink')[0]
    assert href == f'{ITINERARY_BASE}/?from=wisata&destinationId=1'
    link = page.locator('#itineraryHandoffLink')
    assert link.get_attribute('target') == '_blank'
    assert 'noopener' in link.get_attribute('rel')


def test_w6_itinerary_link_carries_visit_date_and_follows_calendar(server, page):
    d = _day(3)
    _mock_hotels(page, [])
    _open(page, server, f'?destinationId=1&visitDate={d}')
    page.wait_for_selector('#itineraryHandoffLink', state='attached')
    assert _hrefs(page, '#itineraryHandoffLink') == [f'{ITINERARY_BASE}/?from=wisata&destinationId=1&visitDate={d}']
    d2 = _day(6)
    page.evaluate(f"selectDate('{d2}', 10000, 0, false, '')")
    href = _hrefs(page, '#itineraryHandoffLink')[0]
    assert href.endswith(f'visitDate={d2}')
    for bad in ('token', 'booking', 'email', 'phone', 'price', 'total', 'name='):
        assert bad not in href.lower(), (bad, href)
    assert not page.errors


# ───────── Pemilihan Hotel dan Rental Kendaraan Sebelum Pembayaran ─────────

def _mock_transports(page, vehicles):
    """Tiru API rental transportasi JogjaTrans untuk pengujian peramban."""
    def transport_route(route):
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'source': 'jogjatrans',
            'data': {
                'startDate': '2026-12-01',
                'endDate': '2026-12-01',
                'currency': 'IDR',
                'days': 1,
                'vehicles': vehicles
            }
        }))
    page.route('**/api/v1/integrations/transport*', transport_route)


def test_interop_trip_addons_selection_in_step3(server, page):
    d = _day(3)
    email = f'trip{int(time.time())}@test.com'
    _api(server, '/auth/register', {'name': 'Uji Addon', 'email': email, 'password': 'Passw0rd!123'})
    
    _mock_hotels(page, [{'id': 'H10', 'name': 'Hotel Malioboro Nyaman', 'region': 'kota-yogyakarta', 'price_from': 350000, 'rating': 4.5}])
    _mock_transports(page, [{'id': 'V10', 'name': 'Toyota Avanza Nyaman', 'type': 'mobil', 'seats': 7, 'transmission': 'Otomatis', 'dailyPrice': 350000, 'available': True}])
    
    _open(page, server, f'?destinationId=1&visitDate={d}')
    page.click('#btnLanjut1')
    page.wait_for_function("location.hash === '#/masuk'")
    page.fill('#lEmail', email)
    page.fill('#lPass', 'Passw0rd!123')
    page.click('#btnLogin')
    page.wait_for_function("location.hash === '#/wisata/1'")
    page.wait_for_timeout(1000)
    
    # Lanjut ke Step 2
    page.click('#btnLanjut1')
    page.wait_for_selector('#bName')
    # Lanjut ke Step 3 (Konfirmasi Pesanan)
    page.click('button:has-text("Lanjut →")')
    page.wait_for_selector('.trip-addons-section')
    
    # Buka picker hotel
    page.click('#step3HotelBox button:has-text("Pilih Penginapan")')
    page.wait_for_selector('#modal.open')
    page.wait_for_selector('#modalBody .vehicle-item-card')
    page.click('#modalBody .vehicle-item-card button:has-text("Pilih")')
    page.wait_for_selector('#step3HotelBox.selected')
    assert page.evaluate('_tripAddons.hotel && _tripAddons.hotel.id') == 'H10'
    
    # Buka picker rental kendaraan
    page.click('#step3VehicleBox button:has-text("Pilih Kendaraan")')
    page.wait_for_selector('#modal.open')
    page.wait_for_selector('#modalBody .vehicle-item-card')
    page.click('#modalBody .vehicle-item-card button:has-text("Pilih")')
    page.wait_for_selector('#step3VehicleBox.selected')
    assert page.evaluate('_tripAddons.vehicle && _tripAddons.vehicle.id') == 'V10'
    assert not page.errors


def test_interop_trip_addons_displayed_on_payment_and_success(server, page):
    d = _day(4)
    email = f'pay{int(time.time())}@test.com'
    _api(server, '/auth/register', {'name': 'Uji Bayar Addon', 'email': email, 'password': 'Passw0rd!123'})
    
    _mock_hotels(page, [{'id': 'H20', 'name': 'Grand Hotel Jogja', 'region': 'kota-yogyakarta', 'price_from': 500000, 'rating': 4.8}])
    _mock_transports(page, [{'id': 'V20', 'name': 'Honda BeAT Gesit', 'type': 'motor', 'seats': 2, 'transmission': 'Otomatis', 'dailyPrice': 70000, 'available': True}])
    
    _open(page, server, f'?destinationId=1&visitDate={d}')
    page.click('#btnLanjut1')
    page.wait_for_function("location.hash === '#/masuk'")
    page.fill('#lEmail', email)
    page.fill('#lPass', 'Passw0rd!123')
    page.click('#btnLogin')
    page.wait_for_function("location.hash === '#/wisata/1'")
    page.wait_for_timeout(1000)
    
    # Lanjut ke Step 2 & 3
    page.click('#btnLanjut1')
    page.wait_for_selector('#bName')
    page.click('button:has-text("Lanjut →")')
    page.wait_for_selector('.trip-addons-section')
    
    # Pilih hotel & kendaraan di Step 3
    page.click('#step3HotelBox button:has-text("Pilih Penginapan")')
    page.wait_for_selector('#modal.open')
    page.wait_for_selector('#modalBody .vehicle-item-card')
    page.click('#modalBody .vehicle-item-card button:has-text("Pilih")')
    
    page.click('#step3VehicleBox button:has-text("Pilih Kendaraan")')
    page.wait_for_selector('#modal.open')
    page.wait_for_selector('#modalBody .vehicle-item-card')
    page.click('#modalBody .vehicle-item-card button:has-text("Pilih")')
    
    # Klik Pesan Sekarang untuk lanjut ke halaman bayar
    page.click('#btnBook')
    page.wait_for_function("location.hash.startsWith('#/bayar/')")
    page.wait_for_selector('#payRoot .trip-addons-section')
    
    # Pastikan hotel & kendaraan terpilih muncul di halaman pembayaran sebelum tombol bayar ditekan
    assert 'Grand Hotel Jogja' in page.inner_text('#payHotelSection')
    assert 'Honda BeAT Gesit' in page.inner_text('#payVehicleSection')
    
    # Pilih metode pembayaran
    page.click('.pay-method[data-id="qris"]')
    assert page.is_enabled('#btnPayNow')
    
    # Klik Saya Sudah Bayar
    page.click('#btnPayNow')
    page.wait_for_selector('.eticket')
    
    # Pastikan di layar sukses pesanan berhasil memuat rencana perjalanan lengkap
    text = page.inner_text('body')
    assert 'Pesanan Berhasil!' in text
    assert 'Grand Hotel Jogja' in text
    assert 'Honda BeAT Gesit' in text
    assert not page.errors
