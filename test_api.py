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

    def _create_booking(self, token, days=5, qty=1, dest_id=None, name='Book Test', email='booktest@example.com'):
        if dest_id is None:
            dests = client.get('/api/destinations').get_json()
            dest_id = dests[0]['id']
        r = client.post('/api/bookings', json={
            'destination_id': dest_id, 'visit_date': self._future_date(days),
            'qty': qty, 'name': name, 'email': email
        }, headers={'Authorization': f'Bearer {token}'})
        return r

    def _pay(self, code, token, method='qris'):
        return client.post(f'/api/bookings/{code}/pay', json={'method': method},
                           headers={'Authorization': f'Bearer {token}'})

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
        self.assertEqual(data['status'], 'PENDING')
        self.assertTrue(data.get('expires_at'))
        # Email konfirmasi TIDAK dikirim saat create
        self.assertEqual(mock_send.call_count, 0)
        # Bayar dulu
        r2 = self._pay(data['code'], token)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['status'], 'PAID')
        self.assertTrue(r2.get_json().get('email_sent'))
        self.assertEqual(mock_send.call_count, 1)
        return data['code']

    @patch('mailer.send_email_background')
    def test_03_other_user_cannot_refund(self, mock_send):
        token = self._get_token()
        r = self._create_booking(token, days=10)
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        self._pay(code, token)
        token2 = self._get_token2()
        r2 = client.post(f'/api/bookings/{code}/refund', json={},
            headers={'Authorization': f'Bearer {token2}'})
        self.assertEqual(r2.status_code, 403)

    @patch('mailer.send_email_background')
    def test_04_owner_can_refund(self, mock_send):
        token = self._get_token()
        r = self._create_booking(token, days=10)
        code = r.get_json()['code']
        self._pay(code, token)
        r2 = client.post(f'/api/bookings/{code}/refund', json={'reason': 'test'},
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['status'], 'REFUNDED')

    @patch('mailer.send_email_background')
    def test_05_email_error_doesnt_break_booking(self, mock_send):
        mock_send.side_effect = Exception('SMTP error')
        token = self._get_token()
        r = self._create_booking(token, days=15)
        code = r.get_json()['code']
        r2 = self._pay(code, token)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.get_json().get('email_sent'))

    @patch('mailer.send_email_background')
    def test_06_admin_crud_still_works(self, _):
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
        """Helper: buat booking PENDING lalu bayar, return (code, old_visit, unit_price, total)."""
        r = self._create_booking(token, days=days, qty=qty, name='Chg Test', email='chg@test.com')
        assert r.status_code == 201, r.get_json()
        data = r.get_json()
        code = data['code']
        r2 = self._pay(code, token)
        assert r2.status_code == 200, r2.get_json()
        paid = r2.get_json()
        return code, paid['visit_date'], paid['unit_price'], paid['total']

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
        self.assertEqual(data['unit_price'], up)
        self.assertEqual(data['total'], total)
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
        token = self._get_token('chg5@test.com', 'Chg Five')
        dests = client.get('/api/destinations').get_json()
        today = datetime.date.today().isoformat()
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': today, 'qty': 1,
            'name': 'Chg Five', 'email': 'chg5@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        # Bayar dulu (status PENDING -> PAID)
        self._pay(code, token)
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
        token = self._get_token('chg10@test.com', 'Chg Ten')
        dests = client.get('/api/destinations').get_json()
        tomorrow = self._future_date(1)
        r = client.post('/api/bookings', json={
            'destination_id': dests[0]['id'], 'visit_date': tomorrow, 'qty': 1,
            'name': 'Chg Ten', 'email': 'chg10@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        self._pay(code, token)
        # Ubah ke hari kerja berikutnya (bukan weekend) agar harga tidak naik
        day_after = self._future_date(2)
        d_obj = datetime.date.fromisoformat(day_after)
        while d_obj.weekday() >= 5:
            day_after = (d_obj + datetime.timedelta(days=1)).isoformat()
            d_obj = datetime.date.fromisoformat(day_after)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': day_after},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['visit_date'], day_after)

    # ── FASE 2: Payment flow ──────────────────────────────────────

    @patch('mailer.send_email_background')
    def test_20_booking_is_pending(self, mock_send):
        token = self._get_token('pay1@test.com', 'Pay One')
        r = self._create_booking(token, days=5, name='Pay One', email='pay1@test.com')
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertEqual(data['status'], 'PENDING')
        self.assertTrue(data['expires_at'])
        self.assertIsNone(data.get('paid_at'))

    @patch('mailer.send_email_background')
    def test_21_pay_success(self, mock_send):
        token = self._get_token('pay2@test.com', 'Pay Two')
        r = self._create_booking(token, days=5, name='Pay Two', email='pay2@test.com')
        code = r.get_json()['code']
        r2 = self._pay(code, token, method='gopay')
        self.assertEqual(r2.status_code, 200)
        data = r2.get_json()
        self.assertEqual(data['status'], 'PAID')
        self.assertEqual(data['payment_method'], 'gopay')
        self.assertTrue(data.get('paid_at'))
        self.assertTrue(data.get('email_sent'))
        self.assertEqual(mock_send.call_count, 1)

    @patch('mailer.send_email_background')
    def test_22_pay_invalid_method(self, mock_send):
        token = self._get_token('pay3@test.com', 'Pay Three')
        r = self._create_booking(token, days=5, name='Pay Three', email='pay3@test.com')
        code = r.get_json()['code']
        r2 = self._pay(code, token, method='bitcoin')
        self.assertEqual(r2.status_code, 400)

    @patch('mailer.send_email_background')
    def test_23_pay_expired_returns_410(self, mock_send):
        token = self._get_token('pay4@test.com', 'Pay Four')
        r = self._create_booking(token, days=5, name='Pay Four', email='pay4@test.com')
        code = r.get_json()['code']
        # Set expires_at ke masa lalu langsung di DB
        import sqlite3 as sq
        c = sq.connect('wisata.db')
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec='seconds')
        c.execute("UPDATE bookings SET expires_at=? WHERE code=?", (past, code))
        c.commit(); c.close()
        r2 = self._pay(code, token)
        self.assertEqual(r2.status_code, 410)
        self.assertEqual(r2.get_json()['error'], 'Waktu pembayaran habis')
        # Status otomatis EXPIRED
        r3 = client.get(f'/api/bookings/{code}', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r3.get_json()['status'], 'EXPIRED')

    @patch('mailer.send_email_background')
    def test_24_expired_not_counted_in_quota(self, mock_send):
        token = self._get_token('pay5@test.com', 'Pay Five')
        dests = client.get('/api/destinations').get_json()
        d = dests[0]
        visit = self._future_date(8)
        r = client.post('/api/bookings', json={
            'destination_id': d['id'], 'visit_date': visit, 'qty': 3,
            'name': 'Pay Five', 'email': 'pay5@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        code = r.get_json()['code']
        # Set expired
        import sqlite3 as sq
        c = sq.connect('wisata.db')
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec='seconds')
        c.execute("UPDATE bookings SET status='EXPIRED', expires_at=? WHERE code=?", (past, code))
        c.commit(); c.close()
        # Kuota penuh kembali (EXPIRED tidak dihitung)
        cal = client.get(f'/api/destinations/{d["id"]}/calendar').get_json()
        day = next(x for x in cal if x['date'] == visit)
        self.assertEqual(day['remaining'], d['daily_quota'])

    @patch('mailer.send_email_background')
    def test_25_refund_on_pending_409(self, mock_send):
        token = self._get_token('pay6@test.com', 'Pay Six')
        r = self._create_booking(token, days=5, name='Pay Six', email='pay6@test.com')
        code = r.get_json()['code']
        r2 = client.post(f'/api/bookings/{code}/refund', json={},
                         headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 409)

    @patch('mailer.send_email_background')
    def test_26_other_user_cannot_pay(self, mock_send):
        token = self._get_token('pay7@test.com', 'Pay Seven')
        r = self._create_booking(token, days=5, name='Pay Seven', email='pay7@test.com')
        code = r.get_json()['code']
        token2 = self._get_token('pay8@test.com', 'Pay Eight')
        r2 = self._pay(code, token2)
        self.assertEqual(r2.status_code, 403)

    @patch('mailer.send_email_background')
    def test_27_cancel_pending(self, mock_send):
        token = self._get_token('pay9@test.com', 'Pay Nine')
        r = self._create_booking(token, days=5, name='Pay Nine', email='pay9@test.com')
        code = r.get_json()['code']
        r2 = client.post(f'/api/bookings/{code}/cancel', json={},
                         headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()['status'], 'EXPIRED')

    @patch('mailer.send_email_background')
    def test_28_cancel_paid_409(self, mock_send):
        token = self._get_token('pay10@test.com', 'Pay Ten')
        r = self._create_booking(token, days=5, name='Pay Ten', email='pay10@test.com')
        code = r.get_json()['code']
        self._pay(code, token)
        r2 = client.post(f'/api/bookings/{code}/cancel', json={},
                         headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 409)

    @patch('mailer.send_email_background')
    def test_29_pay_all_methods(self, mock_send):
        token = self._get_token('pay11@test.com', 'Pay Eleven')
        for m in ['qris', 'va_bca', 'va_bni', 'va_mandiri', 'gopay', 'ovo', 'dana']:
            r = self._create_booking(token, days=6, name='Pay Eleven', email='pay11@test.com')
            code = r.get_json()['code']
            r2 = self._pay(code, token, method=m)
            self.assertEqual(r2.status_code, 200, f'method {m} failed')
            self.assertEqual(r2.get_json()['payment_method'], m)

    # ── FASE 3: Weekend pricing + selisih ubah tanggal ────────────

    def _find_weekday_and_weekend(self, days_ahead=14):
        """Cari tanggal weekday dan weekend di masa depan."""
        base = datetime.date.today() + datetime.timedelta(days=days_ahead)
        # Cari Senin (weekday) terdekat
        wd = base
        while wd.weekday() >= 5:
            wd += datetime.timedelta(days=1)
        # Cari Sabtu (weekend) terdekat
        we = base
        while we.weekday() < 5:
            we += datetime.timedelta(days=1)
        return wd.isoformat(), we.isoformat()

    @patch('mailer.send_email_background')
    def test_30_weekend_surcharge_for_destination_without_price_weekend(self, mock_send):
        """Destinasi tanpa price_weekend: harga akhir pekan = dasar + WEEKEND_SURCHARGE."""
        dests = client.get('/api/destinations').get_json()
        # Cari destinasi dengan price=0? tidak, cari yang price>0 dan price_weekend=0
        d = next(x for x in dests if x['price'] > 0 and not x['price_weekend'])
        wd, we = self._find_weekday_and_weekend()
        cal = client.get(f'/api/destinations/{d["id"]}/calendar').get_json()
        wd_day = next(x for x in cal if x['date'] == wd)
        we_day = next(x for x in cal if x['date'] == we)
        self.assertEqual(wd_day['price'], d['price'])
        self.assertEqual(we_day['price'], d['price'] + app.WEEKEND_SURCHARGE)
        self.assertTrue(we_day['is_weekend'])
        self.assertFalse(wd_day['is_weekend'])

    @patch('mailer.send_email_background')
    def test_31_gembira_loka_weekend_price(self, mock_send):
        """Gembira Loka (id 5): 60.000 hari kerja, 75.000 akhir pekan (dari spreadsheet)."""
        cal = client.get('/api/destinations/5/calendar').get_json()
        wd, we = self._find_weekday_and_weekend()
        wd_day = next(x for x in cal if x['date'] == wd)
        we_day = next(x for x in cal if x['date'] == we)
        self.assertEqual(wd_day['price'], 60000)
        self.assertEqual(we_day['price'], 75000)

    @patch('mailer.send_email_background')
    def test_32_free_destination_no_surcharge(self, mock_send):
        """Destinasi gratis (harga 0) tidak dikenai tambahan akhir pekan."""
        dests = client.get('/api/destinations').get_json()
        d = next(x for x in dests if x['price'] == 0 and not x['price_weekend'])
        wd, we = self._find_weekday_and_weekend()
        cal = client.get(f'/api/destinations/{d["id"]}/calendar').get_json()
        wd_day = next(x for x in cal if x['date'] == wd)
        we_day = next(x for x in cal if x['date'] == we)
        self.assertEqual(wd_day['price'], 0)
        self.assertEqual(we_day['price'], 0)

    @patch('mailer.send_email_background')
    def test_33_change_date_cheaper_total_stays(self, mock_send):
        """Ubah ke tanggal lebih murah: total TETAP (tidak ada pengembalian selisih)."""
        token = self._get_token('we1@test.com', 'We One')
        # Booking pada hari kerja (harga dasar)
        wd, we = self._find_weekday_and_weekend(20)
        dests = client.get('/api/destinations').get_json()
        d = next(x for x in dests if x['price'] > 0 and not x['price_weekend'])
        r = client.post('/api/bookings', json={
            'destination_id': d['id'], 'visit_date': we, 'qty': 1,
            'name': 'We One', 'email': 'we1@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        self._pay(code, token)
        # Booking sekarang ada di weekend (harga lebih mahal)
        b = client.get(f'/api/bookings/{code}', headers={'Authorization': f'Bearer {token}'}).get_json()
        self.assertEqual(b['visit_date'], we)
        self.assertEqual(b['unit_price'], d['price'] + app.WEEKEND_SURCHARGE)
        old_total = b['total']
        # Ubah ke hari kerja (lebih murah)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': wd},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        b2 = r2.get_json()
        self.assertEqual(b2['visit_date'], wd)
        # Total TETAP
        self.assertEqual(b2['total'], old_total)
        self.assertEqual(b2['unit_price'], b['unit_price'])
        self.assertFalse(b2.get('requires_payment'))

    @patch('mailer.send_email_background')
    def test_34_change_date_more_expensive_requires_payment(self, mock_send):
        """Ubah ke tanggal lebih mahal: requires_payment, tanggal belum berubah."""
        token = self._get_token('we2@test.com', 'We Two')
        wd, we = self._find_weekday_and_weekend(20)
        dests = client.get('/api/destinations').get_json()
        d = next(x for x in dests if x['price'] > 0 and not x['price_weekend'])
        # Booking di hari kerja (harga dasar)
        r = client.post('/api/bookings', json={
            'destination_id': d['id'], 'visit_date': wd, 'qty': 1,
            'name': 'We Two', 'email': 'we2@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r.status_code, 201)
        code = r.get_json()['code']
        self._pay(code, token)
        old_total = d['price']
        # Ubah ke weekend (lebih mahal)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': we},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(r2.status_code, 200)
        b2 = r2.get_json()
        self.assertTrue(b2.get('requires_payment'))
        self.assertEqual(b2['due_amount'], app.WEEKEND_SURCHARGE)
        # Tanggal BELUM berubah
        self.assertEqual(b2['visit_date'], wd)
        # Bayar selisih
        r3 = self._pay(code, token)
        self.assertEqual(r3.status_code, 200)
        b3 = r3.get_json()
        self.assertEqual(b3['visit_date'], we)
        self.assertEqual(b3['unit_price'], d['price'] + app.WEEKEND_SURCHARGE)
        self.assertEqual(b3['total'], d['price'] + app.WEEKEND_SURCHARGE)
        self.assertIsNone(b3.get('pending_visit_date'))

    @patch('mailer.send_email_background')
    def test_35_pending_price_change_expires_old_date_kept(self, mock_send):
        """Pending ubah tanggal kedaluwarsa: tanggal lama tetap berlaku."""
        token = self._get_token('we3@test.com', 'We Three')
        wd, we = self._find_weekday_and_weekend(20)
        dests = client.get('/api/destinations').get_json()
        d = next(x for x in dests if x['price'] > 0 and not x['price_weekend'])
        r = client.post('/api/bookings', json={
            'destination_id': d['id'], 'visit_date': wd, 'qty': 1,
            'name': 'We Three', 'email': 'we3@test.com'
        }, headers={'Authorization': f'Bearer {token}'})
        code = r.get_json()['code']
        self._pay(code, token)
        # Minta ubah ke weekend (lebih mahal)
        r2 = client.put(f'/api/bookings/{code}', json={'visit_date': we},
                        headers={'Authorization': f'Bearer {token}'})
        self.assertTrue(r2.get_json().get('requires_payment'))
        # Set expires_at ke masa lalu
        import sqlite3 as sq
        c = sq.connect('wisata.db')
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec='seconds')
        c.execute("UPDATE bookings SET expires_at=? WHERE code=?", (past, code))
        c.commit(); c.close()
        # Akses booking -> expire_stale akan membuang pending
        b = client.get(f'/api/bookings/{code}', headers={'Authorization': f'Bearer {token}'}).get_json()
        self.assertEqual(b['visit_date'], wd)
        self.assertIsNone(b.get('pending_visit_date'))
        self.assertEqual(b['total'], d['price'])

    @patch('mailer.send_email_background')
    def test_36_calendar_has_is_weekend_and_weekend_note(self, mock_send):
        dests = client.get('/api/destinations').get_json()
        d = next(x for x in dests if x['price'] > 0 and not x['price_weekend'])
        wd, we = self._find_weekday_and_weekend()
        cal = client.get(f'/api/destinations/{d["id"]}/calendar').get_json()
        wd_day = next(x for x in cal if x['date'] == wd)
        we_day = next(x for x in cal if x['date'] == we)
        self.assertIn('is_weekend', wd_day)
        self.assertIn('is_weekend', we_day)
        self.assertFalse(wd_day['is_weekend'])
        self.assertTrue(we_day['is_weekend'])
        # weekend_note untuk destinasi tanpa price_weekend
        self.assertIsNone(wd_day.get('weekend_note'))
        self.assertIn('Akhir pekan', we_day.get('weekend_note', ''))
        # Untuk Gembira Loka (ada price_weekend): note = 'Tarif akhir pekan'
        cal5 = client.get('/api/destinations/5/calendar').get_json()
        we5 = next(x for x in cal5 if x['date'] == we)
        self.assertEqual(we5.get('weekend_note'), 'Tarif akhir pekan')


if __name__ == '__main__':
    unittest.main(verbosity=2)
