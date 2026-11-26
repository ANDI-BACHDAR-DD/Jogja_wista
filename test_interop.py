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
        for k in ['WEBHOOK_URLS', 'WEBHOOK_SECRET', 'WEBHOOK_SYNC', 'WEBHOOK_INCLUDE_PII']:
            os.environ.pop(k, None)

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
            # Penanda simulasi: PAID pada pesanan partner = dicatat lunas oleh kanal partner
            self.assertIn('simulasi', b['payment_note'])

            # Pesanan partner tidak kedaluwarsa (tidak punya jendela bayar 15 menit)
            r_get = client.get(f"/api/v1/partner/bookings/{b['code']}", headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r_get.status_code, 200)
            self.assertEqual(r_get.get_json()['status'], 'PAID')

            # 2. Resend with same Idempotency-Key -> 200 same booking
            r_idem = client.post('/api/v1/partner/bookings', json=payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}',
                'Idempotency-Key': idem_key
            })
            self.assertEqual(r_idem.status_code, 200)
            self.assertEqual(r_idem.get_json()['code'], b['code'])

            # Resend with same Idempotency-Key but different payload -> 409 IDEMPOTENCY_CONFLICT
            diff_payload = dict(payload, qty=3)
            r_diff = client.post('/api/v1/partner/bookings', json=diff_payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}',
                'Idempotency-Key': idem_key
            })
            self.assertEqual(r_diff.status_code, 409)

            # Non-numeric qty -> 400 (bukan 500)
            bad_qty_payload = dict(payload, qty='bukan_angka', external_ref=f"REF-{uuid.uuid4().hex[:6]}")
            r_bad_qty = client.post('/api/v1/partner/bookings', json=bad_qty_payload, headers={
                'Authorization': f'Bearer {self.HOTEL_KEY}'
            })
            self.assertEqual(r_bad_qty.status_code, 400)

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


class TestPhase3OpenAPI(unittest.TestCase):
    def test_01_openapi_json(self):
        r = client.get('/api/v1/openapi.json')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get('openapi'), '3.0.3')
        self.assertIn('paths', data)
        self.assertIn('components', data)
        self.assertIn('partnerKey', data['components']['securitySchemes'])
        self.assertIn('userToken', data['components']['securitySchemes'])

        # Verify required partner and availability endpoints
        self.assertIn('/api/v1/destinations/{id}/availability', data['paths'])
        self.assertIn('/api/v1/partner/bookings', data['paths'])
        self.assertIn('/api/v1/partner/bookings/{code}', data['paths'])
        self.assertIn('/api/v1/partner/bookings/{code}/refund', data['paths'])

    def test_02_spec_paths_exist_in_flask(self):
        import re
        spec = client.get('/api/v1/openapi.json').get_json()
        flask_rules = set()
        for r in app.app.url_map.iter_rules():
            if r.rule.startswith('/api/v1'):
                norm = re.sub(r'<([a-zA-Z0-9_]+:)?([a-zA-Z0-9_]+)>', r'{\2}', r.rule)
                flask_rules.add(norm)
        for path in spec['paths']:
            self.assertIn(path, flask_rules, f"OpenAPI path {path} not found in Flask routes")

    def test_03_swagger_docs_html(self):
        r = client.get('/api/docs')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r.headers.get('Content-Type', ''))
        html = r.get_data(as_text=True)
        self.assertIn('swagger-ui', html)
        self.assertIn('swagger-ui-bundle.js', html)
        self.assertIn('/api/v1/openapi.json', html)


class TestPhase4Webhooks(unittest.TestCase):
    WEBHOOK_SECRET = "webhook-test-secret-key-12345"
    HOTEL_KEY = "hotel-service-test-api-key-12345"

    class MockResp:
        def __init__(self, status=200):
            self.status = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    @classmethod
    def setUpClass(cls):
        os.environ['PARTNER_KEYS'] = f"hotel:{cls.HOTEL_KEY}"
        os.environ['WEBHOOK_URLS'] = "https://hotel.local/hook,https://itinerary.local/hook"
        os.environ['WEBHOOK_SECRET'] = cls.WEBHOOK_SECRET
        os.environ['WEBHOOK_SYNC'] = "1"
        os.environ['WEBHOOK_INCLUDE_PII'] = "0"
        app.parse_partner_keys()

    @classmethod
    def tearDownClass(cls):
        import sqlite3 as sq
        c = sq.connect('wisata.db')
        c.execute("DELETE FROM bookings WHERE source != 'web'")
        c.commit()
        c.close()
        for k in ['WEBHOOK_URLS', 'WEBHOOK_SECRET', 'WEBHOOK_SYNC', 'WEBHOOK_INCLUDE_PII']:
            os.environ.pop(k, None)

    def _future_date(self, days=80):
        from datetime import date, timedelta
        return (date.today() + timedelta(days=days)).isoformat()

    def test_01_webhook_created_and_hmac_signature(self):
        from unittest.mock import patch
        import json, hmac, hashlib
        os.environ['WEBHOOK_INCLUDE_PII'] = "0"

        captured = []
        def fake_urlopen(req, timeout=5):
            captured.append((req, req.data, dict(req.headers)))
            return self.MockResp(200)

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), patch('mailer.send_email_background'):
            r = client.post('/api/v1/partner/bookings', json={
                "destination_id": 1,
                "visit_date": self._future_date(81),
                "qty": 2,
                "external_ref": f"WH-CR-{uuid.uuid4().hex[:8]}",
                "customer": {"name": "Webhook Tester", "email": "wh@test.com", "phone": "081234"}
            }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r.status_code, 201)

        # 2 webhook URLs configured -> 2 calls
        self.assertEqual(len(captured), 2)
        req, raw_body, headers = captured[0]

        event_header = req.get_header('X-wisata-event') or headers.get('X-Wisata-Event')
        self.assertEqual(event_header, 'booking.created')

        sig_header = req.get_header('X-wisata-signature') or headers.get('X-Wisata-Signature')
        self.assertTrue(sig_header.startswith('sha256='))

        # Re-compute HMAC and verify
        expected_sig = "sha256=" + hmac.new(self.WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        self.assertEqual(sig_header, expected_sig)

        # Verify body
        payload = json.loads(raw_body.decode('utf-8'))
        self.assertTrue(payload['id'].startswith('evt_'))
        self.assertEqual(payload['type'], 'booking.created')
        self.assertIn('created_at', payload)
        self.assertIn('data', payload)
        # PII should NOT be present
        self.assertNotIn('name', payload['data'])
        self.assertNotIn('email', payload['data'])
        self.assertNotIn('phone', payload['data'])

    def test_02_webhook_with_pii(self):
        from unittest.mock import patch
        import json
        os.environ['WEBHOOK_INCLUDE_PII'] = "1"

        captured = []
        def fake_urlopen(req, timeout=5):
            captured.append(req.data)
            return self.MockResp(200)

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), patch('mailer.send_email_background'):
            r = client.post('/api/v1/partner/bookings', json={
                "destination_id": 1,
                "visit_date": self._future_date(82),
                "qty": 1,
                "external_ref": f"WH-PII-{uuid.uuid4().hex[:8]}",
                "customer": {"name": "Alice PII", "email": "alice@pii.com", "phone": "089999"}
            }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r.status_code, 201)

        payload = json.loads(captured[0].decode('utf-8'))
        self.assertEqual(payload['data']['name'], 'Alice PII')
        self.assertEqual(payload['data']['email'], 'alice@pii.com')
        self.assertEqual(payload['data']['phone'], '089999')

    def test_03_webhook_rescheduled_and_refunded(self):
        from unittest.mock import patch
        os.environ['WEBHOOK_INCLUDE_PII'] = "0"

        captured = []
        def fake_urlopen(req, timeout=5):
            captured.append(req.get_header('X-wisata-event') or req.headers.get('X-Wisata-Event'))
            return self.MockResp(200)

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), patch('mailer.send_email_background'):
            # 1. Create
            r = client.post('/api/v1/partner/bookings', json={
                "destination_id": 1,
                "visit_date": self._future_date(83),
                "qty": 1,
                "external_ref": f"WH-FLOW-{uuid.uuid4().hex[:8]}",
                "customer": {"name": "Flow", "email": "flow@test.com", "phone": "081"}
            }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            code = r.get_json()['code']
            captured.clear()

            # 2. Reschedule
            r_upd = client.put(f'/api/v1/partner/bookings/{code}', json={"visit_date": self._future_date(85)},
                               headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r_upd.status_code, 200)
            self.assertIn('booking.rescheduled', captured)
            captured.clear()

            # 3. Refund
            r_ref = client.post(f'/api/v1/partner/bookings/{code}/refund', json={"reason": "Customer cancelled"},
                                headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            self.assertEqual(r_ref.status_code, 200)
            self.assertIn('booking.refunded', captured)

    def test_04_webhook_network_failure_does_not_fail_booking(self):
        from unittest.mock import patch
        import urllib.error

        def failing_urlopen(req, timeout=5):
            raise urllib.error.URLError("Connection refused")

        with patch('urllib.request.urlopen', side_effect=failing_urlopen), patch('mailer.send_email_background'):
            r = client.post('/api/v1/partner/bookings', json={
                "destination_id": 1,
                "visit_date": self._future_date(86),
                "qty": 1,
                "external_ref": f"WH-FAIL-{uuid.uuid4().hex[:8]}",
                "customer": {"name": "Fail Test", "email": "fail@test.com", "phone": "081"}
            }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
            # Booking must still succeed
            self.assertEqual(r.status_code, 201)

    def test_05_webhook_without_secret_does_not_send(self):
        from unittest.mock import patch
        saved_secret = os.environ.get('WEBHOOK_SECRET', '')
        os.environ['WEBHOOK_SECRET'] = ''

        try:
            with patch('urllib.request.urlopen') as mock_urlopen, patch('mailer.send_email_background'):
                r = client.post('/api/v1/partner/bookings', json={
                    "destination_id": 1,
                    "visit_date": self._future_date(87),
                    "qty": 1,
                    "external_ref": f"WH-NOSEC-{uuid.uuid4().hex[:8]}",
                    "customer": {"name": "No Sec", "email": "nosec@test.com", "phone": "081"}
                }, headers={'Authorization': f'Bearer {self.HOTEL_KEY}'})
                self.assertEqual(r.status_code, 201)
                mock_urlopen.assert_not_called()
        finally:
            os.environ['WEBHOOK_SECRET'] = saved_secret


class TestPhase5Integrations(unittest.TestCase):
    class MockResp:
        def __init__(self, data, status=200):
            import json
            self.data = json.dumps(data).encode('utf-8') if isinstance(data, (dict, list)) else data
            self.status = status
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def setUp(self):
        import integrations
        integrations._cache.clear()

    def test_01_unconfigured_returns_503(self):
        os.environ.pop('HOTEL_API_URL', None)
        os.environ.pop('TRANSPORT_API_URL', None)

        r_hotel = client.get('/api/v1/integrations/hotels')
        self.assertEqual(r_hotel.status_code, 503)
        self.assertEqual(r_hotel.get_json()['code'], 'INTEGRATION_NOT_CONFIGURED')

        r_trans = client.get('/api/v1/integrations/transport')
        self.assertEqual(r_trans.status_code, 503)
        self.assertEqual(r_trans.get_json()['code'], 'INTEGRATION_NOT_CONFIGURED')

    def test_02_successful_call_wraps_response(self):
        from unittest.mock import patch
        os.environ['HOTEL_API_URL'] = "https://mock-hotel.local"
        os.environ['HOTEL_API_KEY'] = "mock-hotel-key-12345"

        mock_data = {"hotels": [{"id": 1, "name": "Hotel Jogja Asri"}]}
        captured = []

        def fake_urlopen(req, timeout=5):
            captured.append(req)
            return self.MockResp(mock_data, 200)

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            r = client.get('/api/v1/integrations/hotels?region=kota-yogyakarta&check_in=2026-11-20&check_out=2026-11-22')
            self.assertEqual(r.status_code, 200)
            res = r.get_json()
            self.assertEqual(res['source'], 'hotel')
            self.assertEqual(res['data'], mock_data)

            self.assertEqual(len(captured), 1)
            req = captured[0]
            self.assertIn("mock-hotel.local/api/v1/hotels", req.full_url)
            self.assertIn("check_in=2026-11-20", req.full_url)
            self.assertIn("region=kota-yogyakarta", req.full_url)
            auth_header = req.get_header('Authorization')
            self.assertEqual(auth_header, "Bearer mock-hotel-key-12345")

    def test_03_upstream_failure_returns_502_no_leak(self):
        from unittest.mock import patch
        import urllib.error

        secret_url = "https://internal-dns-secret.corp:8443"
        secret_key = "secret-super-key-XYZ"
        os.environ['TRANSPORT_API_URL'] = secret_url
        os.environ['TRANSPORT_API_KEY'] = secret_key

        def failing_urlopen(req, timeout=5):
            raise urllib.error.URLError("Upstream timeout")

        with patch('urllib.request.urlopen', side_effect=failing_urlopen):
            r = client.get('/api/v1/integrations/transport?startDate=2099-01-10&endDate=2099-01-12')
            self.assertEqual(r.status_code, 502)
            data = r.get_json()
            self.assertEqual(data['code'], 'UPSTREAM_ERROR')

            # Ensure secret URL and key are never leaked in response
            raw_text = r.get_data(as_text=True)
            self.assertNotIn(secret_url, raw_text)
            self.assertNotIn(secret_key, raw_text)
            self.assertNotIn("internal-dns-secret", raw_text)

    def test_04_cache_60s_active(self):
        from unittest.mock import patch
        import integrations
        integrations._cache.clear()

        os.environ['HOTEL_API_URL'] = "https://mock-hotel.local"
        call_count = [0]

        def counting_urlopen(req, timeout=5):
            call_count[0] += 1
            return self.MockResp({"hotels": [{"id": 1}]}, 200)

        with patch('urllib.request.urlopen', side_effect=counting_urlopen):
            # First request -> hits upstream
            r1 = client.get('/api/v1/integrations/hotels?region=sleman')
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(call_count[0], 1)

            # Second identical request -> served from cache
            r2 = client.get('/api/v1/integrations/hotels?region=sleman')
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(call_count[0], 1)
            self.assertEqual(r1.get_json(), r2.get_json())

    def test_05_status_endpoint(self):
        from unittest.mock import patch
        os.environ['HOTEL_API_URL'] = "https://hotel.local"
        os.environ['TRANSPORT_API_URL'] = ""

        def ping_urlopen(req, timeout=3):
            return self.MockResp({"status": "ok"}, 200)

        with patch('urllib.request.urlopen', side_effect=ping_urlopen):
            r = client.get('/api/v1/integrations/status')
            self.assertEqual(r.status_code, 200)
            st = r.get_json()
            self.assertTrue(st['hotel']['configured'])
            self.assertTrue(st['hotel']['reachable'])
            self.assertFalse(st['transport']['configured'])
            self.assertFalse(st['transport']['reachable'])

            raw_text = r.get_data(as_text=True)
            self.assertNotIn("hotel.local", raw_text)


class TestPhaseHotel1Backend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['HOTEL_API_URL'] = "https://mock-jogjastay.local"
        os.environ['HOTEL_SEARCH_PATH'] = "/api/v1/hotels"
        os.environ['HOTEL_TIMEOUT'] = "5"

    def setUp(self):
        import integrations
        integrations._cache.clear()

    def test_01_normalize_hotel(self):
        import integrations
        # 1. Normalizing handles missing fields (null)
        raw_sparse = {"hotelId": "H99"}
        norm_sparse = integrations.normalize_hotel(raw_sparse, base_url="https://mock.com")
        self.assertEqual(norm_sparse["id"], "H99")
        self.assertIsNone(norm_sparse["name"])
        self.assertIsNone(norm_sparse["region"])
        self.assertIsNone(norm_sparse["region_label"])
        self.assertIsNone(norm_sparse["image"])
        self.assertIsNone(norm_sparse["price_from"])
        self.assertIsNone(norm_sparse["currency"])
        self.assertIsNone(norm_sparse["address"])
        self.assertIsNone(norm_sparse["rating"])

        # 2. Relative image URL -> prepended with base_url
        raw_rel = {"hotelId": "H01", "image": "/photos/hotel1.jpg"}
        norm_rel = integrations.normalize_hotel(raw_rel, base_url="https://mock.com")
        self.assertEqual(norm_rel["image"], "https://mock.com/photos/hotel1.jpg")

        # 3. String price conversion (e.g. "Rp 450.000")
        raw_price_str = {"hotelId": "H01", "price_from": "Rp 450.000"}
        norm_price = integrations.normalize_hotel(raw_price_str)
        self.assertEqual(norm_price["price_from"], 450000)
        self.assertEqual(norm_price["currency"], "IDR")

        # 4. Price from rooms list
        raw_rooms = {
            "hotelId": "H01",
            "rooms": [
                {"roomType": "Deluxe", "pricePerNight": 500000},
                {"roomType": "Standard", "pricePerNight": 250000}
            ]
        }
        norm_rooms = integrations.normalize_hotel(raw_rooms)
        self.assertEqual(norm_rooms["price_from"], 250000)

    def test_02_recommendations_for_5_regions(self):
        from unittest.mock import patch
        import integrations, sqlite3
        
        conn = sqlite3.connect("wisata.db")
        c = conn.cursor()
        region_dest_map = {}
        for reg in ["kota-yogyakarta", "kabupaten-sleman", "kabupaten-bantul", "kabupaten-gunungkidul", "kabupaten-kulon-progo"]:
            c.execute("SELECT id, region FROM destinations WHERE region=? LIMIT 1", (reg,))
            row = c.fetchone()
            if row:
                region_dest_map[reg] = row[0]
        conn.close()

        for reg, dest_id in region_dest_map.items():
            captured_calls = []
            def fake_http_get(base_url, path, params=None, api_key=None, timeout=5, use_cache=True):
                captured_calls.append((path, params))
                return [
                    {
                        "hotelId": f"H_{reg}",
                        "name": f"Hotel {reg}",
                        "city": reg,
                        "imageUrl": "https://img.com/h.jpg",
                        "price_from": 350000
                    }
                ]

            with patch('integrations.http_get', side_effect=fake_http_get):
                r = client.get(f'/api/v1/destinations/{dest_id}/hotels')
                self.assertEqual(r.status_code, 200)
                data = r.get_json()
                self.assertEqual(data["destination_id"], dest_id)
                self.assertEqual(data["region"], reg)
                self.assertEqual(data["hotel_region"], reg)
                self.assertEqual(data["source"], "jogjastay")
                self.assertEqual(data["match"], "region")
                self.assertEqual(data["count"], 1)
                self.assertEqual(len(data["hotels"]), 1)
                self.assertEqual(data["hotels"][0]["id"], f"H_{reg}")

                self.assertEqual(len(captured_calls), 1)
                p_path, p_params = captured_calls[0]
                self.assertEqual(p_params.get("city"), reg)

    def test_03_destination_not_found(self):
        r = client.get('/api/v1/destinations/999999/hotels')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["code"], "NOT_FOUND")

    def test_04_unknown_region_422(self):
        import sqlite3
        conn = sqlite3.connect("wisata.db")
        c = conn.cursor()
        c.execute("INSERT INTO destinations(name, region, daily_quota, price) VALUES ('Alien Land', 'planet-mars', 100, 10000)")
        fake_id = c.lastrowid
        conn.commit()
        conn.close()

        try:
            r = client.get(f'/api/v1/destinations/{fake_id}/hotels')
            self.assertEqual(r.status_code, 422)
            self.assertEqual(r.get_json()["code"], "UNPROCESSABLE")
        finally:
            conn = sqlite3.connect("wisata.db")
            conn.execute("DELETE FROM destinations WHERE id=?", (fake_id,))
            conn.commit()
            conn.close()

    def test_05_upstream_error_502_no_leak(self):
        from unittest.mock import patch
        import integrations

        secret_url = "https://super-secret-hotel.internal"
        os.environ['HOTEL_API_URL'] = secret_url

        def failing_http_get(*args, **kwargs):
            raise integrations.UpstreamError("Connection failed")

        with patch('integrations.http_get', side_effect=failing_http_get):
            r = client.get('/api/v1/destinations/1/hotels')
            self.assertEqual(r.status_code, 502)
            self.assertEqual(r.get_json()["code"], "UPSTREAM_ERROR")
            raw_text = r.get_data(as_text=True)
            self.assertNotIn("super-secret-hotel", raw_text)

        os.environ['HOTEL_API_URL'] = "https://mock-jogjastay.local"

    def test_06_empty_list_200_count_0(self):
        from unittest.mock import patch
        with patch('integrations.http_get', return_value=[]):
            r = client.get('/api/v1/destinations/1/hotels')
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertEqual(data["count"], 0)
            self.assertEqual(data["hotels"], [])

    def test_07_cache_active_on_destinations_hotels(self):
        from unittest.mock import patch
        import integrations, json
        integrations._cache.clear()

        class MockResp:
            def __init__(self, data):
                self.data = json.dumps(data).encode('utf-8')
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch('urllib.request.urlopen', return_value=MockResp([{"hotelId": "H01", "name": "Hotel Cached", "city": "Kota Yogyakarta"}])):
            r1 = client.get('/api/v1/destinations/1/hotels')
            self.assertEqual(r1.status_code, 200)

            with patch('urllib.request.urlopen', side_effect=Exception("Should not be called!")):
                r2 = client.get('/api/v1/destinations/1/hotels')
                self.assertEqual(r2.status_code, 200)
                self.assertEqual(r1.get_json(), r2.get_json())

    def test_08_hotel_detail_success_and_404(self):
        from unittest.mock import patch
        import integrations

        sample_detail = {
            "hotelId": "H01",
            "name": "Hotel Malioboro Inn",
            "address": "Jl. Malioboro 52",
            "city": "Kota Yogyakarta",
            "rating": 4,
            "area": "Malioboro",
            "description": "Hotel bagus",
            "imageUrl": "https://img.com/h01.jpg",
            "rooms": [
                {"roomType": "Standard", "pricePerNight": 300000}
            ]
        }

        with patch('integrations.get_hotel_detail', return_value=sample_detail):
            r = client.get('/api/v1/integrations/hotels/H01')
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertEqual(data["id"], "H01")
            self.assertEqual(data["name"], "Hotel Malioboro Inn")
            self.assertEqual(data["region"], "kota-yogyakarta")
            self.assertEqual(data["price_from"], 300000)
            self.assertEqual(data["description"], "Hotel bagus")
            self.assertIn("rooms", data)

        with patch('integrations.get_hotel_detail', side_effect=integrations.UpstreamNotFoundError()):
            r_404 = client.get('/api/v1/integrations/hotels/H999')
            self.assertEqual(r_404.status_code, 404)
            self.assertEqual(r_404.get_json()["code"], "NOT_FOUND")


class TestPhaseHotel2Frontend(unittest.TestCase):
    def test_09_frontend_has_hotel_recommendation_and_jogjastay_no_terdekat(self):
        index_path = os.path.join(os.path.dirname(__file__), 'public', 'index.html')
        self.assertTrue(os.path.exists(index_path), "public/index.html must exist")

        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check required texts
        self.assertIn("Rekomendasi Penginapan", content)
        self.assertIn("JogjaStay", content)
        self.assertIn("Hotel di wilayah yang sama, dari JogjaStay", content)
        self.assertIn("loadHotelRecommendations", content)
        self.assertIn("openHotelDetailModal", content)
        self.assertIn("hotelRecommendations", content)

        # Ensure "terdekat" NEVER appears anywhere in public/index.html
        self.assertNotIn("terdekat", content.lower(), "Frontend must never claim hotels are 'terdekat'")

    def test_10_frontend_served_via_static_routes(self):
        # Verify app serves public/index.html with the new sections
        r = client.get('/')
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        r.close()
        self.assertIn("Rekomendasi Penginapan", text)
        self.assertIn("JogjaStay", text)
        self.assertNotIn("terdekat", text.lower())

    def test_11_verify_hotel_script_exists_and_executable(self):
        script_path = os.path.join(os.path.dirname(__file__), 'verify_hotel.sh')
        self.assertTrue(os.path.exists(script_path), "verify_hotel.sh must exist")
        self.assertTrue(os.access(script_path, os.X_OK), "verify_hotel.sh must be executable")
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
        self.assertIn("destinations/${DEST_ID}/hotels", script_content)
        self.assertIn("integrations/hotels/${FIRST_HOTEL_ID}", script_content)
        self.assertIn("999999/hotels", script_content)


class TestUserAgentAndHeaders(unittest.TestCase):
    def test_01_hotel_recommendations_headers(self):
        from unittest.mock import patch
        import integrations, json

        captured_requests = []

        class MockResp:
            def __init__(self, data):
                self.data = json.dumps(data).encode('utf-8')
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=5):
            captured_requests.append(req)
            return MockResp([{"hotelId": "H01", "name": "Hotel Test", "city": "Kota Yogyakarta"}])

        integrations._cache.clear()
        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            r = client.get('/api/v1/destinations/1/hotels')
            self.assertEqual(r.status_code, 200)

        self.assertEqual(len(captured_requests), 1)
        req = captured_requests[0]
        ua = req.get_header('User-agent')
        accept = req.get_header('Accept')

        self.assertNotIn('Python-urllib', ua or '')
        self.assertEqual(ua, 'WisataJogja/1.0 (interoperabilitas; layanan Wisata)')
        self.assertEqual(accept, 'application/json')

    def test_02_hotel_detail_headers(self):
        from unittest.mock import patch
        import integrations, json

        captured_requests = []

        class MockResp:
            def __init__(self, data):
                self.data = json.dumps(data).encode('utf-8')
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=5):
            captured_requests.append(req)
            return MockResp({"hotelId": "H01", "name": "Hotel Detail Test", "city": "Kota Yogyakarta", "rooms": []})

        integrations._cache.clear()
        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            r = client.get('/api/v1/integrations/hotels/H01')
            self.assertEqual(r.status_code, 200)

        self.assertEqual(len(captured_requests), 1)
        req = captured_requests[0]
        ua = req.get_header('User-agent')
        accept = req.get_header('Accept')

        self.assertNotIn('Python-urllib', ua or '')
        self.assertEqual(ua, 'WisataJogja/1.0 (interoperabilitas; layanan Wisata)')
        self.assertEqual(accept, 'application/json')

    def test_03_webhook_headers(self):
        from unittest.mock import patch
        import webhooks

        captured_requests = []

        class MockResp:
            def __init__(self):
                self.status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=5):
            captured_requests.append(req)
            return MockResp()

        os.environ['WEBHOOK_URLS'] = "http://test-webhook.local/hook"
        os.environ['WEBHOOK_SECRET'] = "super-secret-webhook-key-12345"

        try:
            with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                webhooks.emit_event('booking.created', {"code": "WJ-TEST"}, sync=True)
        finally:
            os.environ.pop('WEBHOOK_URLS', None)
            os.environ.pop('WEBHOOK_SECRET', None)

        self.assertEqual(len(captured_requests), 1)
        req = captured_requests[0]
        ua = req.get_header('User-agent')
        content_type = req.get_header('Content-type')

        self.assertNotIn('Python-urllib', ua or '')
        self.assertEqual(ua, 'WisataJogja-Webhook/1.0')
        self.assertEqual(content_type, 'application/json')
        self.assertTrue(req.get_header('X-wisata-signature'))

    def test_04_upstream_403_logs_snippet_and_returns_502(self):
        from unittest.mock import patch
        import urllib.error, io, integrations

        long_body = "Access Denied: Cloudflare 403 Forbidden Error Page with very long explanation text " * 10
        class FakeHTTPError(urllib.error.HTTPError):
            def __init__(self, code, body):
                super().__init__('https://jogjastay-hotel-service.jogjawisata.workers.dev/api/v1/hotels', code, 'Forbidden', {}, io.BytesIO(body.encode('utf-8')))

        integrations._cache.clear()
        error_logs = []

        with patch('integrations.logger.error', side_effect=lambda msg: error_logs.append(msg)), \
             patch('urllib.request.urlopen', side_effect=FakeHTTPError(403, long_body)):
            r = client.get('/api/v1/destinations/1/hotels')
            self.assertEqual(r.status_code, 502)
            self.assertEqual(r.get_json()['code'], 'UPSTREAM_ERROR')

        self.assertTrue(len(error_logs) > 0)
        log_msg = error_logs[0]
        self.assertIn('403', log_msg)
        self.assertIn('Access Denied', log_msg)
        # Verify snippet is at most 200 chars (not the entire long_body)
        self.assertLess(len(log_msg), len(long_body))
        # Ensure no full url or secret keys are logged
        self.assertNotIn('jogjastay-hotel-service', log_msg)


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestTransportRentalAndSemantic(unittest.TestCase):
    """W4 (transport) dan W7 (/semantic). Tanpa jaringan: urlopen ditiru."""
    class MockResp:
        def __init__(self, data):
            import json
            self.data = json.dumps(data).encode('utf-8')
            self.status = 200
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def setUp(self):
        import integrations
        integrations._cache.clear()
        self._saved = {k: os.environ.get(k) for k in ('TRANSPORT_API_URL', 'TRANSPORT_API_KEY', 'TRANSPORT_SEARCH_PATH')}
        os.environ['TRANSPORT_API_URL'] = 'https://mock-trans.local'
        os.environ.pop('TRANSPORT_API_KEY', None)
        os.environ.pop('TRANSPORT_SEARCH_PATH', None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_01_default_path_is_rental_catalog_and_whitelists_params(self):
        from unittest.mock import patch
        captured = []
        def fake(req, timeout=5):
            captured.append(req.full_url)
            return self.MockResp({'vehicles': [{'id': 'M01'}], 'startDate': '2099-01-10', 'endDate': '2099-01-12'})
        with patch('urllib.request.urlopen', side_effect=fake):
            r = client.get('/api/v1/integrations/transport?startDate=2099-01-10&endDate=2099-01-12'
                           '&type=mobil&withDriver=false&token=SECRET&bookingId=RT-1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['source'], 'transport')
        self.assertEqual(len(captured), 1)
        url = captured[0]
        self.assertIn('mock-trans.local/api/v1/rentals/vehicles?', url)
        for part in ('startDate=2099-01-10', 'endDate=2099-01-12', 'type=mobil', 'withDriver=false'):
            self.assertIn(part, url)
        self.assertNotIn('SECRET', url)
        self.assertNotIn('bookingId', url)

    def test_02_invalid_params_rejected_before_upstream(self):
        from unittest.mock import patch
        bad = [
            '',                                                    # tanggal hilang
            '?startDate=2099-01-10',                               # endDate hilang
            '?startDate=2099-02-30&endDate=2099-03-01',            # tanggal kalender palsu
            '?startDate=2099-01-12&endDate=2099-01-10',            # terbalik
            '?startDate=2099-01-01&endDate=2099-02-01',            # 32 hari
            '?startDate=2099-01-10&endDate=2099-01-12&type=bus',   # type tidak dikenal
            '?startDate=2099-01-10&endDate=2099-01-12&withDriver=yes',
            '?startDate=2099-01-10&endDate=2099-01-12&category=a b',
        ]
        with patch('urllib.request.urlopen', side_effect=AssertionError('upstream tidak boleh dipanggil')):
            for q in bad:
                r = client.get('/api/v1/integrations/transport' + q)
                self.assertEqual(r.status_code, 400, q)
                self.assertEqual(r.get_json()['code'], 'INVALID_PARAMS', q)

    def test_03_thirty_days_allowed(self):
        from unittest.mock import patch
        with patch('urllib.request.urlopen', return_value=self.MockResp({'vehicles': []})):
            r = client.get('/api/v1/integrations/transport?startDate=2099-01-01&endDate=2099-01-30')
        self.assertEqual(r.status_code, 200)

    def test_04_explicit_search_path_keeps_legacy_passthrough(self):
        from unittest.mock import patch
        os.environ['TRANSPORT_SEARCH_PATH'] = '/api/v1/routes'
        captured = []
        def fake(req, timeout=5):
            captured.append(req.full_url)
            return self.MockResp({'routes': []})
        with patch('urllib.request.urlopen', side_effect=fake):
            r = client.get('/api/v1/integrations/transport?origin=jogja&destination=solo')
        self.assertEqual(r.status_code, 200)
        self.assertIn('mock-trans.local/api/v1/routes', captured[0])
        self.assertIn('origin=jogja', captured[0])

    def test_05_default_url_used_when_env_absent_outside_tests(self):
        import integrations
        os.environ.pop('TRANSPORT_API_URL', None)
        with app.app.app_context():
            self.assertTrue(integrations._is_testing())  # di bawah tes, bawaan sengaja kosong agar tidak memanggil jaringan
            url, _, path = integrations.get_transport_config()
        self.assertEqual(url, '')
        self.assertEqual(path, '/api/v1/rentals/vehicles')
        app.app.config['TESTING'] = False
        try:
            with app.app.app_context():
                url, _, _ = integrations.get_transport_config()
            self.assertEqual(url, integrations.DEFAULT_TRANSPORT_API_URL)
        finally:
            app.app.config['TESTING'] = True
        self.assertEqual(integrations.DEFAULT_TRANSPORT_API_URL, 'https://jogjatrans-service.jogjawisata.workers.dev')

    def test_06_semantic_endpoint_serves_pinned_crs(self):
        import hashlib, json
        for prefix in ('/api', '/api/v1'):
            r = client.get(prefix + '/semantic')
            self.assertEqual(r.status_code, 200, prefix)
            self.assertEqual(r.mimetype, 'application/json')
            body = r.get_data()
            data = json.loads(body)
            self.assertEqual(data['version'], '0.1.1')
            # Git blob SHA-1 dari crs-vocabulary.json di JogjaTrans main (d40b68b): byte-identik
            blob = hashlib.sha1(b'blob %d\x00' % len(body) + body).hexdigest()
            self.assertEqual(blob, '14eee633a6641d373b53e48b8dc7586cd6f24f5d')

    def test_07_semantic_has_five_diy_regions(self):
        data = client.get('/api/v1/semantic').get_json()
        ids = {r['conceptId'] for r in data['regions']}
        self.assertEqual(ids, {'diy:kota-yogyakarta', 'diy:kabupaten-sleman', 'diy:kabupaten-bantul',
                               'diy:kabupaten-gunungkidul', 'diy:kabupaten-kulon-progo'})
