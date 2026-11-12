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


if __name__ == '__main__':
    unittest.main(verbosity=2)
