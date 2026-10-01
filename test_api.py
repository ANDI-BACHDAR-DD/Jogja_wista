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

    def _book_paid(self, token, days=10, qty=1):
        """Helper: buat booking PAID, return (code, old_visit, unit_price, total)."""
        dests = client.get('/api/destinations').get_json()
        d = dests[0]
        visit = self._future_date(days)
        r = client.post('/api/bookings', json={
            'destination_id': d['id'], 'visit_date': visit, 'qty': qty,
            'name': 'Chg Test', 'email': 'chg@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 201, r.get_json()
        data = r.get_json()
        return data['code'], visit, data['unit_price'], data['total']

    @patch('mailer.send_email_background')
    def test_07_change_date_success(self, mock_send):
        token = self._get_token('chg1@test.com', 'Chg One')
        code, old_visit, up, total = self._book_paid(token, days=10)
        new_visit = self._future_date(12)
        r = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit},
                       headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data['visit_date'], new_visit)
        # Harga terkunci
        self.assertEqual(data['unit_price'], up)
        self.assertEqual(data['total'], total)
        # Email perubahan terkirim
        self.assertTrue(mock_send.called)

    @patch('mailer.send_email_background')
    def test_08_change_date_with_qty_rejected(self, mock_send):
        token = self._get_token('chg2@test.com', 'Chg Two')
        code, *_ = self._book_paid(token, days=10)
        new_visit = self._future_date(12)
        r = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit, 'qty': 5},
                       headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Hanya tanggal', r.get_json()['error'])

    @patch('mailer.send_email_background')
    def test_09_change_date_with_name_phone_rejected(self, mock_send):
        token = self._get_token('chg3@test.com', 'Chg Three')
        code, *_ = self._book_paid(token, days=10)
        new_visit = self._future_date(12)
        for extra in [{'name': 'X'}, {'phone': '0812'}, {'tier': 'plus'}]:
            body = {'visit_date': new_visit}; body.update(extra)
            r = client.put(f'/api/bookings/{code}', json=body,
                           headers={'Authorization': f'Bearer {token}'})
            self.assertEqual(r.status_code, 400)

    @patch('mailer.send_email_background')
    def test_10_change_date_past_or_today_rejected(self, mock_send):
        token = self._get_token('chg4@test.com', 'Chg Four')
        code, *_ = self._book_paid(token, days=10)
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        for bad in [today, yesterday]:
            r = client.put(f'/api/bookings/{code}', json={'visit_date': bad},
                           headers={'Authorization': f'Bearer {token}'})
            self.assertEqual(r.status_code, 400)

    @patch('mailer.send_email_background')
    def test_11_change_date_old_visit_today_rejected(self, mock_send):
        # Booking visit_date = hari ini bisa dibuat, tapi TIDAK bisa diubah
        token = self._get_token('chg5@test.com', 'Chg Five')
        dests = client.get('/api/destinations').get_json()
        today = datetime.date.today().isoformat()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': today, 'qty': 1,
            'name': 'Chg Five', 'email': 'chg5@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        # Ubah tanggal: old_visit = hari ini < besok -> 400
        new_visit = self._future_date(3)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 400)

    @patch('mailer.send_email_background')
    def test_12_change_date_other_user_forbidden(self, mock_send):
        token = self._get_token('chg6@test.com', 'Chg Six')
        code, *_ = self._book_paid(token, days=10)
        token2 = self._get_token('chg7@test.com', 'Chg Seven')
        new_visit = self._future_date(12)
        r = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit},
                       headers={'Authorization': f'Bearer {token2}'})
        self.assertEqual(r.status_code, 403)

    @patch('mailer.send_email_background')
    def test_13_change_date_refunded_rejected(self, mock_send):
        token = self._get_token('chg8@test.com', 'Chg Eight')
        code, *_ = self._book_paid(token, days=10)
        r = client.post(f'/api/bookings/{code}/refund', json={'reason': 'test'},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 200)
        new_visit = self._future_date(12)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 409)

    @patch('mailer.send_email_background')
    def test_14_change_date_admin_ok(self, mock_send):
        token = self._get_token('chg9@test.com', 'Chg Nine')
        code, *_ = self._book_paid(token, days=10)
        new_visit = self._future_date(14)
        r = client.put(f'/api/bookings/{code}', json={'visit_date': new_visit},
                       headers=ADMIN_HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['visit_date'], new_visit)

    @patch('mailer.send_email_background')
    def test_15_change_date_same_day_tomorrow_boundary(self, mock_send):
        """Tanggal besok = valid untuk old & new."""
        token = self._get_token('chg10@test.com', 'Chg Ten')
        dests = client.get('/api/destinations').get_json()
        tomorrow = self._future_date(1)
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': tomorrow, 'qty': 1,
            'name': 'Chg Ten', 'email': 'chg10@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        day_after = self._future_date(2)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': day_after},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['visit_date'], day_after)


if __name__ == '__main__':
    unittest.main(verbosity=2)
