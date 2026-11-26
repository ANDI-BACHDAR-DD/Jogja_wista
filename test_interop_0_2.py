"""Contract 0.2 provider tests for Wisata Jogja. Run: python -m unittest test_interop_0_2 -v"""
import os, tempfile, unittest, uuid, sqlite3
from datetime import date, timedelta

_tmp = tempfile.mkdtemp()
os.environ['DB_PATH'] = os.path.join(_tmp, 'wisata_interop_test.db')
os.environ['PARTNER_KEYS'] = 'hotel:hotel-test-key-0123456789abcdef,transport:transport-test-key-0123456789'
os.environ['INTEROP_OFFER_SIGNING_KEY'] = 'x' * 40
os.environ['SECRET_KEY'] = 'test-secret'
import app as wisata  # noqa: E402

wisata.app.config['TESTING'] = True
C = wisata.app.test_client()
H = {'Authorization': 'Bearer hotel-test-key-0123456789abcdef'}
T = {'Authorization': 'Bearer transport-test-key-0123456789'}
P = '/api/v1/interop'
DAY = (date.today() + timedelta(days=10)).isoformat()


def key(): return uuid.uuid4().hex


def offers(h=H, **q):
    q.setdefault('startDate', DAY)
    return C.get(P + '/offers', query_string=q, headers=h)


def hold(offer, ref=None, k=None, h=H, **over):
    body = {'offerId': offer['offerId'], 'externalRef': ref or 'JT-' + uuid.uuid4().hex[:10], 'consent': True,
            'customer': {'name': 'Dummy QA', 'email': 'qa@example.test', 'phone': '081234567890'}}
    body.update(over)
    return C.post(P + '/holds', json=body, headers={**h, 'Idempotency-Key': k or key()})


def act(hid, verb, h=H, k=None):
    return C.post(f'{P}/holds/{hid}/{verb}', headers={**h, 'Idempotency-Key': k or key()})


class Wisata02(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls._tmp, 'wisata_interop_test.db')
        os.environ['DB_PATH'] = cls.db_path
        os.environ['PARTNER_KEYS'] = 'hotel:hotel-test-key-0123456789abcdef,transport:transport-test-key-0123456789'
        os.environ['INTEROP_OFFER_SIGNING_KEY'] = 'x' * 40
        os.environ['SECRET_KEY'] = 'test-secret'
        wisata.DB = cls.db_path
        wisata.init()
        wisata.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('DB_PATH', None)
        os.environ.pop('INTEROP_OFFER_SIGNING_KEY', None)
        os.environ.pop('INTEROP_DURABLE_STORAGE', None)
        wisata.DB = 'wisata.db'
        wisata.init()
        try:
            import shutil
            shutil.rmtree(cls._tmp, ignore_errors=True)
        except Exception:
            pass

    def first(self, **q):
        r = offers(**q)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.json['offers'])
        return r.json['offers'][0]

    def rows(self, hid):
        c = sqlite3.connect(os.environ['DB_PATH']); c.row_factory = sqlite3.Row
        try: return c.execute('SELECT * FROM bookings WHERE code=?', (hid,)).fetchone()
        finally: c.close()

    def test_01_auth_and_capabilities(self):
        self.assertEqual(C.get(P + '/capabilities').status_code, 401)
        self.assertEqual(C.get(P + '/capabilities', headers={'Authorization': 'Bearer nope'}).status_code, 401)
        r = C.get(P + '/capabilities', headers=H)
        self.assertEqual(r.status_code, 200)
        j = r.json
        self.assertEqual((j['contract'], j['provider'], j['holds'], j['holdTtlMinutes']), ('0.2.0', 'wisata', True, 15))
        self.assertEqual(j['entityTypes'], ['tourist_attraction'])
        self.assertIn('email', j['requiredCustomerFields'])
        self.assertIs(j['durableStorage'], False)  # the test DB lives in /tmp: capabilities must not overclaim
        # Negative test: flag set to true but storage is ephemeral in /tmp -> must stay False (fail-closed)
        os.environ['INTEROP_DURABLE_STORAGE'] = 'true'
        try:
            self.assertIs(C.get(P + '/capabilities', headers=H).json['durableStorage'], False)
        finally:
            del os.environ['INTEROP_DURABLE_STORAGE']

        # Probe test: Turso configured and probe succeeds -> durableStorage is True
        from unittest.mock import patch
        with patch('db_turso.is_turso_configured', return_value=True), \
             patch('db_turso.is_durable', return_value=True):
            self.assertIs(C.get(P + '/capabilities', headers=H).json['durableStorage'], True)

        # Fail-closed test: Turso configured but probe fails -> durableStorage is False
        with patch('db_turso.is_turso_configured', return_value=True), \
             patch('db_turso.is_durable', return_value=False):
            self.assertIs(C.get(P + '/capabilities', headers=H).json['durableStorage'], False)

    def test_02_offers_shape_filters_and_region_form(self):
        o = self.first(regionId='diy:kabupaten-sleman', quantity=2, limit=3)
        self.assertEqual((o['provider'], o['entityType'], o['priceUnit'], o['regionId']), ('wisata', 'tourist_attraction', 'ticket', 'diy:kabupaten-sleman'))
        self.assertEqual(o['totalPrice'], o['price'] * 2)
        self.assertEqual(o['period']['startDate'], DAY)
        self.assertIsNone(o['location']['lat'])
        self.assertLessEqual(len(offers(regionId='kabupaten-sleman', limit=3).json['offers']), 3)
        self.assertEqual(offers(regionId='diy:mars').status_code, 400)
        self.assertEqual(offers(startDate='2001-01-01').status_code, 400)
        self.assertEqual(offers(quantity=0).status_code, 400)

    def test_03_hold_is_idempotent_and_conflicts(self):
        o, k, ref = self.first(), key(), 'JT-' + uuid.uuid4().hex[:8]
        a = hold(o, ref=ref, k=k)
        self.assertEqual(a.status_code, 201, a.get_data(as_text=True))
        self.assertEqual((a.json['reservationState'], a.json['paymentState']), ('awaiting_payment', 'unpaid'))
        self.assertTrue(a.json['expiresAt'].endswith('Z'))
        b = hold(o, ref=ref, k=k)
        self.assertEqual((b.status_code, b.json['holdId']), (200, a.json['holdId']))
        self.assertEqual(hold(o, ref=ref, k=k, customer={'name': 'Other', 'email': 'o@example.test'}).json['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(hold(o, ref=ref, k=key()).status_code, 409)  # same externalRef, new key
        act(a.json['holdId'], 'release')

    def test_04_validation_codes(self):
        o = self.first()
        self.assertEqual(hold(o, consent=False).json['code'], 'CONSENT_REQUIRED')
        self.assertEqual(hold(o, ref='x' * 65).json['code'], 'INVALID_HOLD')
        self.assertEqual(hold(o, extra=1).json['code'], 'BAD_JSON')
        self.assertEqual(hold(o, customer={'name': 'A', 'email': 'bad'}).json['code'], 'INVALID_CUSTOMER')
        self.assertEqual(hold(o, customer={'name': 'Ok Name', 'phone': '0812345678901'}).json['code'], 'INVALID_CUSTOMER')  # email required
        r = hold({'offerId': o['offerId'][:-1] + ('0' if o['offerId'][-1] != '0' else '1')})
        self.assertEqual((r.status_code, r.json['code']), (422, 'INVALID_OFFER'))
        self.assertEqual(hold(o, h=T).json['code'], 'INVALID_OFFER')  # offer is bound to the partner that asked for it
        self.assertEqual(C.post(P + '/holds', json={}, headers=H).json['code'], 'IDEMPOTENCY_REQUIRED')
        self.assertEqual(hold(o, quantity=5).json['code'], 'INVALID_OFFER')

    def test_05_hold_counts_against_quota_and_release_returns_it(self):
        conn = sqlite3.connect(os.environ['DB_PATH'])
        orig_quota = conn.execute('SELECT daily_quota FROM destinations WHERE id=(SELECT MIN(id) FROM destinations)').fetchone()[0]
        conn.execute('UPDATE destinations SET daily_quota=1 WHERE id=(SELECT MIN(id) FROM destinations)'); conn.commit(); conn.close()
        try:
            first_id = str(sqlite3.connect(os.environ['DB_PATH']).execute('SELECT MIN(id) FROM destinations').fetchone()[0])
            o = next(x for x in offers(limit=100).json['offers'] if x['resourceId'] == first_id)
            a = hold(o)
            self.assertEqual(a.status_code, 201)
            self.assertNotIn(first_id, [x['resourceId'] for x in offers(limit=100).json['offers']])  # held ticket is out of stock
            self.assertEqual(hold(o, h=H).json['code'], 'NOT_AVAILABLE')
            self.assertEqual(act(a.json['holdId'], 'release').json['reservationState'], 'cancelled')
            self.assertIn(first_id, [x['resourceId'] for x in offers(limit=100).json['offers']])  # stock is back
            row = self.rows(a.json['holdId'])
            self.assertEqual((row['name'], row['email'], row['phone']), ('', '', ''))  # no PII kept for a released hold
            self.assertEqual(act(a.json['holdId'], 'release').status_code, 200)  # release is idempotent
        finally:
            conn = sqlite3.connect(os.environ['DB_PATH'])
            conn.execute('UPDATE destinations SET daily_quota=? WHERE id=(SELECT MIN(id) FROM destinations)', (orig_quota,))
            conn.commit(); conn.close()

    def test_06_confirm_release_after_confirm_and_ownership(self):
        o = self.first(); hid = hold(o).json['holdId']
        self.assertEqual(C.get(f'{P}/holds/{hid}', headers=T).status_code, 404)  # another partner cannot read it
        self.assertEqual(act(hid, 'confirm', h=T).status_code, 404)
        c = act(hid, 'confirm')
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True))
        self.assertEqual((c.json['reservationState'], c.json['paymentState']), ('reserved', 'paid'))
        self.assertTrue(c.json['simulation']); self.assertEqual(c.json['voucher']['code'], hid)
        self.assertEqual(act(hid, 'confirm').json['voucher']['code'], hid)  # confirm twice = same answer
        r = act(hid, 'release')
        self.assertEqual((r.status_code, r.json['code']), (409, 'ALREADY_CONFIRMED'))
        self.assertEqual(C.get(f'{P}/holds/{hid}', headers=H).json['reservationState'], 'reserved')
        self.assertEqual(self.rows(hid)['email'], 'qa@example.test')  # the owner keeps the ticket record

    def test_07_expiry_is_computed_on_read(self):
        o = self.first(); hid = hold(o).json['holdId']
        conn = sqlite3.connect(os.environ['DB_PATH'])
        conn.execute("UPDATE bookings SET expires_at='2000-01-01T00:00:00' WHERE code=?", (hid,)); conn.commit(); conn.close()
        self.assertEqual(C.get(f'{P}/holds/{hid}', headers=H).json['reservationState'], 'expired')
        c = act(hid, 'confirm'); self.assertEqual((c.status_code, c.json['code']), (409, 'HOLD_EXPIRED'))
        self.assertEqual(self.rows(hid)['email'], '')
        o2 = self.first(); h2 = hold(o2).json['holdId']; act(h2, 'release')
        c2 = act(h2, 'confirm'); self.assertEqual((c2.status_code, c2.json['code']), (409, 'HOLD_RELEASED'))

    def test_08_legacy_routes_are_untouched(self):
        self.assertEqual(C.get('/api/v1/health').status_code, 200)
        self.assertEqual(C.get('/api/v1/destinations').status_code, 200)

    def test_09_partner_booking_qty_validation(self):
        # Non-numeric or boolean qty must return 400 (not 500)
        body = {
            'destination_id': 1, 'visit_date': DAY, 'qty': 'non-integer',
            'external_ref': 'LEGACY-' + uuid.uuid4().hex[:8],
            'customer': {'name': 'Budi', 'email': 'budi@example.test', 'phone': '08123456789'}
        }
        r = C.post('/api/v1/partner/bookings', json=body, headers=H)
        self.assertEqual(r.status_code, 400)
        body['qty'] = True
        r = C.post('/api/v1/partner/bookings', json=body, headers=H)
        self.assertEqual(r.status_code, 400)
        body['qty'] = -1
        r = C.post('/api/v1/partner/bookings', json=body, headers=H)
        self.assertEqual(r.status_code, 400)

    def test_10_partner_booking_request_fingerprint_idempotency(self):
        ref = 'LEGACY-' + uuid.uuid4().hex[:8]
        idem = 'IDEM-' + uuid.uuid4().hex[:8]
        body = {
            'destination_id': 1, 'visit_date': DAY, 'qty': 1,
            'external_ref': ref,
            'customer': {'name': 'Budi', 'email': 'budi@example.test', 'phone': '08123456789'}
        }
        r1 = C.post('/api/v1/partner/bookings', json=body, headers={**H, 'Idempotency-Key': idem})
        self.assertEqual(r1.status_code, 201)
        # Replay same payload and key -> 200 OK same booking
        r2 = C.post('/api/v1/partner/bookings', json=body, headers={**H, 'Idempotency-Key': idem})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json['code'], r1.json['code'])
        # Replay same key but different payload -> 409 Conflict
        body_diff = {**body, 'qty': 2}
        r3 = C.post('/api/v1/partner/bookings', json=body_diff, headers={**H, 'Idempotency-Key': idem})
        self.assertEqual(r3.status_code, 409)

    def test_11_admin_default_credentials_hardened_in_prod(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'VERCEL': '1'}):
            import app as w
            prev_is_vercel = w.IS_VERCEL
            w.IS_VERCEL = True
            try:
                # In production, default admin token 'admin123' must be rejected
                r = C.post('/api/v1/destinations', headers={'X-Admin-Token': 'admin123'}, json={'name': 'test'})
                self.assertEqual(r.status_code, 403)
            finally:
                w.IS_VERCEL = prev_is_vercel

    @classmethod
    def tearDownClass(cls):
        if 'DB_PATH' in os.environ:
            del os.environ['DB_PATH']
        wisata.DB = 'wisata.db'
        wisata.init()


if __name__ == '__main__':
    unittest.main()
