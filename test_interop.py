import os
import unittest
import uuid
from datetime import datetime
import app

app.app.config['TESTING'] = True
client = app.app.test_client()

class TestPhase1Interop(unittest.TestCase):
    def test_01_v1_and_legacy_paths_match(self):
        # Health check
        r_legacy = client.get('/api/health')
        r_v1 = client.get('/api/v1/health')
        self.assertEqual(r_legacy.status_code, 200)
        self.assertEqual(r_v1.status_code, 200)
        d_legacy = r_legacy.get_json()
        d_v1 = r_v1.get_json()
        self.assertEqual(d_legacy['status'], d_v1['status'])
        self.assertEqual(d_legacy['service'], d_v1['service'])
        self.assertEqual(d_legacy['version'], d_v1['version'])

        # Regions
        r_legacy_reg = client.get('/api/regions')
        r_v1_reg = client.get('/api/v1/regions')
        self.assertEqual(r_legacy_reg.status_code, 200)
        self.assertEqual(r_v1_reg.status_code, 200)
        self.assertEqual(r_legacy_reg.get_json(), r_v1_reg.get_json())

        # Destinations
        r_legacy_dest = client.get('/api/destinations')
        r_v1_dest = client.get('/api/v1/destinations')
        self.assertEqual(r_legacy_dest.status_code, 200)
        self.assertEqual(r_v1_dest.status_code, 200)
        self.assertEqual(r_legacy_dest.get_json(), r_v1_dest.get_json())

    def test_02_health_endpoint_contract(self):
        r = client.get('/api/v1/health')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('service'), 'wisata')
        self.assertEqual(data.get('version'), '1.0.0')
        self.assertIn('time', data)
        # Parse ISO time
        t_str = data['time']
        self.assertTrue(t_str.endswith('Z') or '+' in t_str)

    def test_03_error_format_404_json(self):
        r = client.get('/api/v1/non_existent_route')
        self.assertEqual(r.status_code, 404)
        data = r.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn('error', data)
        self.assertIsInstance(data['error'], str)
        self.assertEqual(data.get('code'), 'NOT_FOUND')

    def test_04_error_format_405_json(self):
        r = client.post('/api/v1/regions')
        self.assertEqual(r.status_code, 405)
        data = r.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn('error', data)
        self.assertIsInstance(data['error'], str)
        self.assertEqual(data.get('code'), 'VALIDATION_ERROR')

    def test_05_error_format_custom_codes(self):
        # 400 Bad Request
        r_bad = client.post('/api/v1/auth/register', json={'name': 'X', 'email': 'bad_email', 'password': '123'})
        self.assertEqual(r_bad.status_code, 400)
        d_bad = r_bad.get_json()
        self.assertEqual(d_bad.get('code'), 'VALIDATION_ERROR')
        self.assertIsInstance(d_bad.get('error'), str)

        # 401 Unauthorized
        r_unauth = client.get('/api/v1/auth/me')
        self.assertEqual(r_unauth.status_code, 401)
        d_unauth = r_unauth.get_json()
        self.assertEqual(d_unauth.get('code'), 'UNAUTHORIZED')

        # 403 Forbidden
        r_forbid = client.post('/api/v1/destinations', json={'name': 'Illegal', 'region': 'sleman'})
        self.assertEqual(r_forbid.status_code, 403)
        d_forbid = r_forbid.get_json()
        self.assertEqual(d_forbid.get('code'), 'FORBIDDEN')

    def test_06_cors_preflight_and_headers(self):
        # OPTIONS preflight for GET
        r = client.options('/api/v1/destinations', headers={
            'Origin': 'http://frontend.local',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'Authorization, Idempotency-Key'
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn('Access-Control-Allow-Origin', r.headers)
        self.assertIn('X-Request-Id', r.headers.get('Access-Control-Expose-Headers', ''))

    def test_07_request_id_in_response(self):
        r = client.get('/api/v1/destinations')
        self.assertIn('X-Request-Id', r.headers)
        req_id = r.headers['X-Request-Id']
        # Must be valid UUID
        parsed_uuid = uuid.UUID(req_id)
        self.assertEqual(str(parsed_uuid), req_id)

    def test_08_destinations_pagination_and_x_total_count(self):
        # Default behavior: all destinations returned, X-Total-Count present
        r_all = client.get('/api/v1/destinations')
        self.assertEqual(r_all.status_code, 200)
        self.assertIn('X-Total-Count', r_all.headers)
        total = int(r_all.headers['X-Total-Count'])
        self.assertGreaterEqual(total, 60)
        self.assertEqual(len(r_all.get_json()), total)

        # With limit
        r_lim = client.get('/api/v1/destinations?limit=5')
        self.assertEqual(r_lim.status_code, 200)
        self.assertEqual(len(r_lim.get_json()), 5)
        self.assertEqual(r_lim.headers['X-Total-Count'], str(total))

        # With offset
        r_off = client.get('/api/v1/destinations?limit=5&offset=5')
        self.assertEqual(r_off.status_code, 200)
        self.assertEqual(len(r_off.get_json()), 5)
        self.assertNotEqual(r_lim.get_json()[0]['id'], r_off.get_json()[0]['id'])

        # With ids filter
        r_ids = client.get('/api/v1/destinations?ids=1,2,3')
        self.assertEqual(r_ids.status_code, 200)
        self.assertEqual(r_ids.headers['X-Total-Count'], '3')
        self.assertEqual(len(r_ids.get_json()), 3)
        res_ids = {d['id'] for d in r_ids.get_json()}
        self.assertEqual(res_ids, {1, 2, 3})


class TestPhase2Partner(unittest.TestCase):
    HOTEL_KEY = "hotel-service-test-api-key-12345"
    TRANSPORT_KEY = "transport-service-test-key-99999"
    SHORT_KEY = "short-key"

    @classmethod
    def setUpClass(cls):
        os.environ['PARTNER_KEYS'] = f"hotel:{cls.HOTEL_KEY},transport:{cls.TRANSPORT_KEY},invalid:{cls.SHORT_KEY}"

    @classmethod
    def tearDownClass(cls):
        import sqlite3 as sq
        c = sq.connect('wisata.db')
        c.execute("DELETE FROM bookings WHERE source != 'web'")
        c.commit()
        c.close()

    def _future_date(self, days=60):
        from datetime import date, timedelta
        return (date.today() + timedelta(days=days)).isoformat()

    def test_01_partner_keys_auth(self):
        # Without key -> 401
        r_nokey = client.post('/api/v1/partner/bookings', json={})
        self.assertEqual(r_nokey.status_code, 401)
        self.assertEqual(r_nokey.get_json()['code'], 'UNAUTHORIZED')

        # Invalid key -> 401
        r_wrong = client.post('/api/v1/partner/bookings', json={},
                              headers={'Authorization': 'Bearer wrong-key-12345678901234567890'})
        self.assertEqual(r_wrong.status_code, 401)
        self.assertEqual(r_wrong.get_json()['code'], 'UNAUTHORIZED')

        # Short key rejected during parsing -> 401
        r_short = client.post('/api/v1/partner/bookings', json={},
                              headers={'Authorization': f'Bearer {self.SHORT_KEY}'})
        self.assertEqual(r_short.status_code, 401)

    def test_02_availability_endpoint(self):
        from datetime import date, timedelta
        # Public endpoint
        dests = client.get('/api/v1/destinations').get_json()
        d_id = dests[0]['id']

        # Find a weekday and a weekend date
        base = date.today() + timedelta(days=10)
        wd = base
        while wd.weekday() >= 5: wd += timedelta(days=1)
        we = base
        while we.weekday() < 5: we += timedelta(days=1)

        # Check weekday availability
        r_wd = client.get(f'/api/v1/destinations/{d_id}/availability?date={wd.isoformat()}&qty=2')
        self.assertEqual(r_wd.status_code, 200)
        data_wd = r_wd.get_json()
        self.assertEqual(data_wd['destination_id'], d_id)
        self.assertEqual(data_wd['date'], wd.isoformat())
        self.assertEqual(data_wd['qty'], 2)
        self.assertTrue(data_wd['available'])
        self.assertEqual(data_wd['currency'], 'IDR')
        self.assertFalse(data_wd['is_weekend'])

        # Check weekend availability
        r_we = client.get(f'/api/v1/destinations/{d_id}/availability?date={we.isoformat()}&qty=2')
        self.assertEqual(r_we.status_code, 200)
        data_we = r_we.get_json()
        self.assertTrue(data_we['is_weekend'])
        # If dest has price > 0, weekend price should reflect weekend surcharge/rate
        if dests[0]['price'] > 0 and not dests[0]['price_weekend']:
            self.assertEqual(data_we['unit_price'], dests[0]['price'] + app.WEEKEND_SURCHARGE)

        # Past date -> 400
        past = (date.today() - timedelta(days=1)).isoformat()
        r_past = client.get(f'/api/v1/destinations/{d_id}/availability?date={past}&qty=1')
        self.assertEqual(r_past.status_code, 400)
        self.assertEqual(r_past.get_json()['code'], 'VALIDATION_ERROR')

    def test_03_partner_create_booking_and_idempotency(self):
        from unittest.mock import patch
        dests = client.get('/api/v1/destinations').get_json()
        d_id = dests[0]['id']
        visit = self._future_date(7)
        ext_ref = f"HOTEL-BOOKING-{uuid.uuid4().hex[:8]}"
        idem_key = f"IDEM-{uuid.uuid4().hex}"

        payload = {
            "destination_id": d_id,
            "visit_date": visit,
            "qty": 2,
            "external_ref": ext_ref,
            "customer": {
                "name": "Jane Partner",
                "email": "jane@hotelguest.com",
                "phone": "08123456789"
            }
        }

        with patch('mailer.send_email_background') as mock_email:
            # 1. Create booking
            r = client.post('/api/v1/partner/bookings', json=payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}',
                'Idempotency-Key': idem_key
            })
            self.assertEqual(r.status_code, 201)
            b = r.get_json()
            self.assertIn('code', b)
            self.assertEqual(b['source'], 'hotel')
            self.assertEqual(b['status'], 'PAID')
            self.assertEqual(b['external_ref'], ext_ref)
            self.assertIn('destination_name', b)
            self.assertEqual(mock_email.call_count, 1)

            # 2. Resend with same Idempotency-Key -> 200 same booking
            r_idem = client.post('/api/v1/partner/bookings', json=payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}',
                'Idempotency-Key': idem_key
            })
            self.assertEqual(r_idem.status_code, 200)
            self.assertEqual(r_idem.get_json()['code'], b['code'])

            # 3. Duplicate external_ref with DIFFERENT idempotency key -> 409
            r_dup = client.post('/api/v1/partner/bookings', json=payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}'
            })
            self.assertEqual(r_dup.status_code, 409)
            self.assertEqual(r_dup.get_json()['code'], 'CONFLICT')

    def test_04_partner_isolation(self):
        # Hotel creates a booking
        dests = client.get('/api/v1/destinations').get_json()
        ext_ref = f"HOTEL-ISO-{uuid.uuid4().hex[:8]}"
        r = client.post('/api/v1/partner/bookings', json={
            "destination_id": dests[0]['id'],
            "visit_date": self._future_date(8),
            "qty": 1,
            "external_ref": ext_ref,
            "customer": {"name": "Test", "email": "iso@test.com", "phone": "081"}
        }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']

        # Hotel can view it
        r_hotel = client.get(f'/api/v1/partner/bookings/{code}',
                             headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
        self.assertEqual(r_hotel.status_code, 200)

        # Transport CANNOT view Hotel's booking -> 404
        r_trans = client.get(f'/api/v1/partner/bookings/{code}',
                             headers={'Authorization': f'Bearer {self.TRANSPORT_KEY}'})
        self.assertEqual(r_trans.status_code, 404)
        self.assertEqual(r_trans.get_json()['code'], 'NOT_FOUND')

    def test_05_partner_update_date_and_refund(self):
        from unittest.mock import patch
        dests = client.get('/api/v1/destinations').get_json()
        d_id = dests[0]['id']
        ext_ref = f"HOTEL-UPD-{uuid.uuid4().hex[:8]}"

        # Create booking for 10 days ahead
        r = client.post('/api/v1/partner/bookings', json={
            "destination_id": d_id,
            "visit_date": self._future_date(10),
            "qty": 1,
            "external_ref": ext_ref,
            "customer": {"name": "Bob", "email": "bob@hotel.com", "phone": "081"}
        }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']

        with patch('mailer.send_email_background') as mock_email:
            # Update date
            new_date = self._future_date(14)
            r_upd = client.put(f'/api/v1/partner/bookings/{code}', json={"visit_date": new_date},
                               headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r_upd.status_code, 200)
            self.assertEqual(r_upd.get_json()['visit_date'], new_date)
            self.assertTrue(mock_email.called)

            # Refund
            r_ref = client.post(f'/api/v1/partner/bookings/{code}/refund', json={"reason": "Customer cancelled"},
                                headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r_ref.status_code, 200)
            data_ref = r_ref.get_json()
            self.assertEqual(data_ref['status'], 'REFUNDED')
            self.assertEqual(data_ref['refund_amount'], data_ref['total']) # >= 3 days -> 100%

    def test_06_partner_rate_limiting(self):
        # 120 reqs/min
        p_name = 'ratelimit_partner'
        p_key = 'ratelimit-partner-test-key-12345'
        os.environ['PARTNER_KEYS'] += f",{p_name}:{p_key}"
        app.parse_partner_keys()

        # Clear any prior records
        app._partner_reqs[p_name] = []

        headers = {'Authorization': f'Bearer {p_key}'}
        # Simulate 120 calls
        for _ in range(120):
            r = client.get('/api/v1/partner/bookings', headers=headers)
            self.assertEqual(r.status_code, 200)

        # 121st call must return 429
        r_limited = client.get('/api/v1/partner/bookings', headers=headers)
        self.assertEqual(r_limited.status_code, 429)
        self.assertEqual(r_limited.get_json()['code'], 'RATE_LIMITED')
        self.assertIn('Retry-After', r_limited.headers)

    def test_07_quota_and_admin_view(self):
        dests = client.get('/api/v1/destinations').get_json()
        d_id = dests[0]['id']
        visit = self._future_date(18)

        # 1. Check availability before
        r_avail_before = client.get(f'/api/v1/destinations/{d_id}/availability?date={visit}&qty=1')
        rem_before = r_avail_before.get_json()['remaining']

        # 2. Partner booking for 5 tickets
        ext_ref = f"HOTEL-QUOTA-{uuid.uuid4().hex[:8]}"
        r_book = client.post('/api/v1/partner/bookings', json={
            "destination_id": d_id,
            "visit_date": visit,
            "qty": 5,
            "external_ref": ext_ref,
            "customer": {"name": "Quota Guy", "email": "quota@hotel.com", "phone": "081"}
        }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
        self.assertEqual(r_book.status_code, 201)
        code = r_book.get_json()['code']

        # 3. Check availability after -> remaining reduced by 5
        r_avail_after = client.get(f'/api/v1/destinations/{d_id}/availability?date={visit}&qty=1')
        rem_after = r_avail_after.get_json()['remaining']
        self.assertEqual(rem_after, rem_before - 5)

        # 4. Admin view
        r_admin = client.get(f'/api/v1/bookings?code={code}', headers={'X-Admin-Token': app.ADMIN_TOKEN})
        self.assertEqual(r_admin.status_code, 200)
        admin_bookings = r_admin.get_json()
        self.assertEqual(len(admin_bookings), 1)
        self.assertEqual(admin_bookings[0]['source'], 'hotel')
        self.assertEqual(admin_bookings[0]['status'], 'PAID')


if __name__ == '__main__':
    unittest.main(verbosity=2)
