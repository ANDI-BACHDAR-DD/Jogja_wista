import datetime
import os
import unittest
from unittest.mock import patch
import app

app.app.config['TESTING'] = True
client = app.app.test_client()
ADMIN_TOKEN = app.ADMIN_TOKEN
ADMIN_HEADERS = {'X-Admin-Token': ADMIN_TOKEN}

class TestAuth(unittest.TestCase):
    def test_01_register_success(self):
        r = client.post('/api/auth/register', json={
            'name': 'Test User', 'email': 'testuser@example.com', 'password': 'password123'
        })
        # 201 or 409 if already exists
        self.assertIn(r.status_code, [201, 409])
        if r.status_code == 201:
            data = r.get_json()
            self.assertIn('token', data)
            self.assertIn('user', data)
            self.assertNotIn('password_hash', data['user'])

    def test_02_register_duplicate_email(self):
        # Register first time
        client.post('/api/auth/register', json={
            'name': 'Dup User', 'email': 'dup@example.com', 'password': 'password123'
        })
        # Second time should 409
        r = client.post('/api/auth/register', json={
            'name': 'Dup User', 'email': 'dup@example.com', 'password': 'password123'
        })
        self.assertEqual(r.status_code, 409)

    def test_03_register_short_password(self):
        r = client.post('/api/auth/register', json={
            'name': 'Test', 'email': 'short@example.com', 'password': '123'
        })
        self.assertEqual(r.status_code, 400)

    def test_04_login_success(self):
        client.post('/api/auth/register', json={
            'name': 'Login Test', 'email': 'logintest@example.com', 'password': 'password123'
        })
        r = client.post('/api/auth/login', json={
            'email': 'logintest@example.com', 'password': 'password123'
        })
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn('token', data)
        self.assertNotIn('password_hash', data['user'])

    def test_05_login_wrong_password(self):
        r = client.post('/api/auth/login', json={
            'email': 'logintest@example.com', 'password': 'wrongpass'
        })
        self.assertEqual(r.status_code, 401)

    def test_06_me_with_token(self):
        r = client.post('/api/auth/login', json={
            'email': 'logintest@example.com', 'password': 'password123'
        })
        token = r.get_json()['token']
        me = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()['email'], 'logintest@example.com')

    def test_07_me_without_token(self):
        r = client.get('/api/auth/me')
        self.assertEqual(r.status_code, 401)


class TestDestinations(unittest.TestCase):
    def test_01_regions(self):
        r = client.get('/api/regions')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 5)

    def test_02_destinations(self):
        r = client.get('/api/destinations')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 62)

    def test_03_filter_region(self):
        dests = client.get('/api/destinations').get_json()
        sleman = [d for d in dests if 'sleman' in d['region']]
        if sleman:
            r = client.get(f'/api/destinations?region={sleman[0]["region"]}')
            self.assertEqual(len(r.get_json()), len(sleman))

    def test_04_crud_admin(self):
        # No token → 403
        r = client.post('/api/destinations', json={'name': 'Test', 'region': 'kota-yogyakarta'})
        self.assertEqual(r.status_code, 403)
        # With admin token
        r = client.post('/api/destinations', json={'name': 'Test CRUD', 'region': 'kota-yogyakarta', 'price': 0, 'price_max': 0, 'price_weekend': 0, 'daily_quota': 100, 'description': '', 'price_label': ''}, headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 201)
        cid = r.get_json()['id']
        # Update
        r = client.put(f'/api/destinations/{cid}', json={'price': 20000}, headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['price'], 20000)
        # Delete
        r = client.delete(f'/api/destinations/{cid}', headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 204)


class TestBookings(unittest.TestCase):
    def _get_token(self, email='booktest@example.com', name='Book Test'):
        client.post('/api/auth/register', json={'name': name, 'email': email, 'password': 'password123'})
        r = client.post('/api/auth/login', json={'email': email, 'password': 'password123'})
        return r.get_json().get('token')

    def _get_token2(self):
        return self._get_token('other@example.com', 'Other User')

    def _future_date(self, days=5):
        return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

    @patch('mailer.send_email_background')
    def test_01_booking_without_token(self, _):
        dests = client.get('/api/destinations').get_json()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': self._future_date(),
            'qty': 1, 'name': 'X', 'email': 'x@x.com', 'phone': ''
        })
        self.assertEqual(r.status_code, 401)

    @patch('mailer.send_email_background')
    def test_02_booking_with_token(self, mock_send):
        token = self._get_token()
        dests = client.get('/api/destinations').get_json()
        gembira = next(d for d in dests if 'Gembira' in d['name'])
        r = client.post('/api/bookings', json={
            'destination_id': gembira['id'], 'visit_date': self._future_date(7),
            'qty': 2, 'name': 'Book Test', 'email': 'booktest@example.com', 'phone': '0812'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertIn('code', data)
        self.assertTrue(data.get('email_sent'))
        self.assertEqual(mock_send.call_count, 1)
        return data['code']

    @patch('mailer.send_email_background')
    def test_03_other_user_cannot_refund(self, mock_send):
        # Owner books
        token = self._get_token()
        dests = client.get('/api/destinations').get_json()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': self._future_date(10),
            'qty': 1
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        # Other user tries to refund
        token2 = self._get_token2()
        r2 = client.post(f'/api/bookings/{code}/refund', json={},
            headers={'Authorization': f'Bearer {token2}'})
        self.assertEqual(r2.status_code, 403)

    @patch('mailer.send_email_background')
    def test_04_owner_can_refund(self, mock_send):
        token = self._get_token()
        dests = client.get('/api/destinations').get_json()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': self._future_date(10),
            'qty': 1
        }, headers={'Authorization': f'Bearer {token}'})
        code = r.get_json()['code']
        r2 = client.post(f'/api/bookings/{code}/refund', json={'reason': 'test'},
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['status'], 'REFUNDED')

    @patch('mailer.send_email_background')
    def test_05_email_error_doesnt_break_booking(self, mock_send):
        mock_send.side_effect = Exception('SMTP error')
        token = self._get_token()
        dests = client.get('/api/destinations').get_json()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': self._future_date(15),
            'qty': 1
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.get_json().get('email_sent'))

    @patch('mailer.send_email_background')
    def test_06_admin_crud_still_works(self, _):
        # Admin CRUD via X-Admin-Token
        r = client.post('/api/destinations', json={
            'name': 'Admin Test', 'region': 'kota-yogyakarta',
            'price': 5000, 'price_max': 0, 'price_weekend': 0, 'daily_quota': 50,
            'description': '', 'price_label': ''
        }, headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 201)
        cid = r.get_json()['id']
        r = client.delete(f'/api/destinations/{cid}', headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 204)


if __name__ == '__main__':
    unittest.main(verbosity=2)
