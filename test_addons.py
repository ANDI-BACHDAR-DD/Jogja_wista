"""Wisata add-on checkout: one basket, one simulated payment. Run: python -m unittest test_addons -v"""
import os, sqlite3, tempfile, unittest, uuid
from datetime import date, timedelta

os.environ.setdefault('DB_PATH', os.path.join(tempfile.mkdtemp(), 'wisata_addons_import.db'))
os.environ.setdefault('SECRET_KEY', 'test-secret')
ADDON_ENV = {'ADDON_ENABLED': 'true', 'ADDON_HOTEL_URL': 'https://hotel.invalid', 'ADDON_HOTEL_TOKEN': 'h' * 30,
             'ADDON_TRANSPORT_URL': 'https://trans.invalid', 'ADDON_TRANSPORT_TOKEN': 't' * 30}
import app as wisata  # noqa: E402
import addons  # noqa: E402

wisata.app.config['TESTING'] = True
C = wisata.app.test_client()
VISIT = (date.today() + timedelta(days=14)).isoformat()


class Fake:
    """Two fake providers speaking Contract 0.2 (hold / confirm with simulated payment / release / GET)."""
    def __init__(self):
        self.calls, self.holds, self.keys = [], {}, {}
        self.hold_fail = {}      # provider -> (status, code) | 'timeout'
        self.confirm_fail = {}   # provider -> (status, code) | 'timeout' | 'unrecorded'
        self.price = {'hotel': 900000, 'transport': 300000}

    def http(self, method, url, headers, body, timeout):
        provider = 'hotel' if 'hotel.invalid' in url else 'transport'
        path = url.split('/api/v1/interop')[1]
        key = headers.get('Idempotency-Key')
        self.calls.append((provider, method, path.split('?')[0], key, body))
        assert headers['Authorization'].startswith('Bearer ')
        ent = 'lodging' if provider == 'hotel' else 'vehicle_rental'
        if path == '/capabilities':
            return 200, {'contract': '0.2.0', 'provider': provider, 'holds': True, 'durableStorage': True, 'holdTtlMinutes': 15,
                         'entityTypes': [ent], 'paymentMode': 'simulated'}
        if path.startswith('/offers'):
            return 200, {'provider': provider, 'generatedAt': '2026-01-01T00:00:00Z', 'offers': [
                {'offerId': 'off-' + provider, 'provider': provider, 'regionId': 'diy:kabupaten-sleman', 'available': True, 'remaining': 3,
                 'totalPrice': self.price[provider], 'name': 'X', 'description': '', 'imageUrl': None, 'period': {}}]}
        if path == '/holds' and method == 'POST':
            f = self.hold_fail.get(provider)
            if f == 'timeout': raise OSError('timeout')
            if f: return f[0], {'code': f[1]}
            if key in self.keys: return 201, self.keys[key]
            h = {'holdId': f'{provider[:1].upper()}H-{len(self.holds)+1}', 'offerId': body['offerId'], 'reservationState': 'awaiting_payment',
                 'paymentState': 'unpaid', 'totalPrice': self.price[provider], 'externalRef': body['externalRef'], 'provider': provider}
            self.holds[h['holdId']] = h
            self.keys[key] = h
            return 201, h
        hid = path.split('/')[2] if path.startswith('/holds/') else None
        h = self.holds.get(hid)
        if not h: return 404, {'code': 'NOT_FOUND'}
        if method == 'GET': return 200, h
        if path.endswith('/release'):
            if h['reservationState'] == 'reserved': return 409, {'code': 'ALREADY_CONFIRMED'}
            h['reservationState'] = 'cancelled'
            return 200, {'holdId': hid, 'reservationState': 'cancelled'}
        if path.endswith('/confirm'):
            f = self.confirm_fail.get(provider)
            if f == 'timeout': raise OSError('timeout')
            if isinstance(f, tuple): return f[0], {'code': f[1]}
            pay = (body or {}).get('payment')
            if pay and pay['amount'] != h['totalPrice']: return 400, {'code': 'INVALID_PAYMENT'}
            h['reservationState'] = 'reserved'
            h['voucher'] = {'code': 'V-' + hid, 'note': 'x'}
            if pay and f != 'unrecorded':
                h['paymentState'] = 'paid'; h['payment'] = {'method': 'simulated', 'reference': pay['reference']}
            return 200, {'holdId': hid, 'reservationState': 'reserved', 'paymentState': h['paymentState'], 'voucher': h['voucher'],
                         **({'payment': h['payment']} if h.get('payment') else {})}
        return 404, {'code': 'NOT_FOUND'}


class AddonCheckout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Own database and env so the suite also runs after the other suites in one process (unittest discover).
        cls._old_db = wisata.DB
        cls.db_path = os.path.join(tempfile.mkdtemp(), 'wisata_addons_test.db')
        wisata.DB = cls.db_path
        cls._old_env = {k: os.environ.get(k) for k in ADDON_ENV}
        os.environ.update(ADDON_ENV)
        wisata.init()
        r = C.post('/api/auth/register', json={'name': 'Add On', 'email': 'addon@example.test', 'password': 'password123'})
        cls.auth = {'Authorization': 'Bearer ' + (r.get_json() or {}).get('token', '')}
        con = sqlite3.connect(cls.db_path)
        cls.dest = con.execute("SELECT id FROM destinations WHERE region='kabupaten-sleman' LIMIT 1").fetchone()[0]
        con.close()

    @classmethod
    def tearDownClass(cls):
        wisata.DB = cls._old_db
        for k, v in cls._old_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def setUp(self):
        self.fake = Fake()
        self._orig = addons._http
        addons._http = self.fake.http

    def tearDown(self):
        addons._http = self._orig

    def booking(self):
        r = C.post('/api/v1/bookings', json={'destination_id': self.dest, 'visit_date': VISIT, 'qty': 1}, headers=self.auth)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()['code']

    def checkout(self, code, providers=('hotel', 'transport'), **over):
        body = {'payment': {'method': 'qris'}, 'consent': True, 'customer': {'phone': '081234567890'},
                'addons': [{'provider': p, 'offerId': 'off-' + p, 'expectedTotalPrice': self.fake.price[p]} for p in providers]}
        body.update(over)
        return C.post(f'/api/v1/bookings/{code}/checkout', json=body, headers=self.auth)

    def status(self, code):
        return C.get(f'/api/v1/bookings/{code}', headers=self.auth).get_json()['status']

    def test_01_one_basket_one_payment_paid_vouchers(self):
        code = self.booking()
        r = self.checkout(code)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        j = r.get_json()
        self.assertEqual(j['status'], 'CONFIRMED')
        self.assertEqual(self.status(code), 'PAID')
        refs = {c[4]['payment']['reference'] for c in self.fake.calls if c[2].endswith('/confirm')}
        self.assertEqual(len(refs), 1, 'one payment reference for the whole basket')
        self.assertTrue(all(a['state'] == 'CONFIRMED' and a['paymentState'] == 'paid' and a['voucher'] for a in j['addons']))
        # holds come before the payment: every hold call precedes every confirm call
        order = [c[2].split('/')[-1] if c[2] != '/holds' else 'hold' for c in self.fake.calls if c[1] == 'POST']
        self.assertEqual(order, ['hold', 'hold', 'confirm', 'confirm'])

    def test_02_replay_sends_nothing(self):
        code = self.booking()
        self.checkout(code)
        n = len(self.fake.calls)
        r = self.checkout(code)
        self.assertEqual(r.get_json()['status'], 'REPLAY')
        self.assertEqual(len(self.fake.calls), n)

    def test_03_definite_hold_refusal_continues_without_that_addon(self):
        self.fake.hold_fail['transport'] = (409, 'NOT_AVAILABLE')
        code = self.booking()
        j = self.checkout(code).get_json()
        self.assertEqual(self.status(code), 'PAID')
        states = {a['provider']: a['state'] for a in j['addons']}
        self.assertEqual(states, {'hotel': 'CONFIRMED', 'transport': 'HOLD_FAILED'})
        self.assertEqual(j['addons'][1]['errorCode'], 'NOT_AVAILABLE')

    def test_04_unknown_hold_pays_nothing_and_releases_the_rest(self):
        self.fake.hold_fail['transport'] = 'timeout'
        code = self.booking()
        r = self.checkout(code)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.status(code), 'PENDING')
        self.assertTrue(all(h['reservationState'] == 'cancelled' for h in self.fake.holds.values()))
        self.assertFalse([c for c in self.fake.calls if c[2].endswith('/confirm')])
        # same-key retry (provider replays) completes it
        self.fake.hold_fail.clear()
        r = self.checkout(code)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_05_wrong_price_releases_and_continues_without(self):
        code = self.booking()
        r = self.checkout(code, providers=('hotel',))
        self.assertEqual(r.get_json()['status'], 'CONFIRMED')
        code2 = self.booking()
        j = self.checkout(code2, providers=('transport',), addons=[{'provider': 'transport', 'offerId': 'off-transport', 'expectedTotalPrice': 1}]).get_json()
        self.assertEqual(j['addons'][0]['errorCode'], 'OFFER_CHANGED')
        self.assertEqual(self.status(code2), 'PAID')

    def test_06_payment_failure_releases_every_hold(self):
        from unittest import mock
        code = self.booking()
        # The ticket payment fails AFTER both add-ons are held (e.g. the booking window ran out in between).
        with mock.patch.object(wisata, 'settle_pending', return_value=(None, object())):
            r = self.checkout(code)
        self.assertEqual(r.status_code, 410)
        self.assertEqual(len(self.fake.holds), 2)
        self.assertTrue(all(h['reservationState'] == 'cancelled' for h in self.fake.holds.values()))
        self.assertFalse([c for c in self.fake.calls if c[2].endswith('/confirm')])
        self.assertEqual(self.status(code), 'PENDING')

    def test_06b_expired_ticket_makes_no_provider_call(self):
        code = self.booking()
        con = sqlite3.connect(self.db_path)
        con.execute("UPDATE bookings SET expires_at='2000-01-01T00:00:00' WHERE code=?", (code,)); con.commit(); con.close()
        r = self.checkout(code)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.fake.calls, [])

    def test_07_confirm_refused_after_payment_is_partial_never_cancelled(self):
        self.fake.confirm_fail['transport'] = (409, 'HOLD_EXPIRED')
        code = self.booking()
        j = self.checkout(code).get_json()
        self.assertEqual(j['status'], 'PARTIAL')
        self.assertEqual(self.status(code), 'PAID')
        self.assertFalse([c for c in self.fake.calls if c[2].endswith('/release') and c[0] == 'hotel'], 'confirmed hotel is not released')

    def test_08_unrecorded_payment_is_not_trusted(self):
        self.fake.confirm_fail['hotel'] = 'unrecorded'
        code = self.booking()
        j = self.checkout(code, providers=('hotel',)).get_json()
        self.assertIn(j['status'], ('PARTIAL', 'UNKNOWN'))
        self.assertEqual(len([c for c in self.fake.calls if c[2].endswith('/confirm')]), 1, 'no resend with a new key')

    def test_09_unknown_confirm_is_reconciled_by_get_and_resumable(self):
        self.fake.confirm_fail['hotel'] = 'timeout'
        code = self.booking()
        j = self.checkout(code, providers=('hotel',)).get_json()
        self.assertEqual(j['status'], 'UNKNOWN')
        self.assertTrue([c for c in self.fake.calls if c[1] == 'GET' and c[2].startswith('/holds/')])
        self.assertFalse([c for c in self.fake.calls if c[2].endswith('/release')])
        self.fake.confirm_fail.clear()
        j = self.checkout(code, providers=('hotel',)).get_json()
        self.assertEqual(j['status'], 'CONFIRMED')
        keys = {c[3] for c in self.fake.calls if c[2].endswith('/confirm')}
        self.assertEqual(len(keys), 1, 'same idempotency key on resume')

    def test_10_no_consent_no_addon_call(self):
        code = self.booking()
        r = self.checkout(code, consent=False)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.fake.calls, [])

    def test_11_recommendations_are_scoped_to_region_and_dates(self):
        code = self.booking()
        r = C.get(f'/api/v1/bookings/{code}/addon-offers?provider=hotel', headers=self.auth)
        j = r.get_json()
        self.assertEqual(j['regionId'], 'diy:kabupaten-sleman')
        q = [c for c in self.fake.calls if c[2] == '/offers']
        self.assertEqual(len(q), 1)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(o['regionId'] == 'diy:kabupaten-sleman' for o in j['offers']))

    def test_12_other_users_cannot_checkout(self):
        code = self.booking()
        r = C.post(f'/api/v1/bookings/{code}/checkout', json={'payment': {'method': 'qris'}, 'addons': []})
        self.assertIn(r.status_code, (401, 403))


if __name__ == '__main__':
    unittest.main()
