"""Wisata Jogja - Backend REST API (Flask + SQLite). Jalankan: python app.py"""
import json, os, random, sqlite3, string
from datetime import date, datetime, timedelta
from flask import Flask, g, jsonify, request, send_from_directory

ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'admin123')
DB = os.getenv('DB_PATH', 'wisata.db')
app = Flask(__name__, static_folder='static', static_url_path='/static')

SCHEMA = """
CREATE TABLE IF NOT EXISTS regions(slug TEXT PRIMARY KEY, name TEXT, tagline TEXT);
CREATE TABLE IF NOT EXISTS destinations(id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT, name TEXT, description TEXT,
  price_label TEXT, price INTEGER, price_max INTEGER, price_weekend INTEGER, photos TEXT DEFAULT '[]', daily_quota INTEGER DEFAULT 500);
CREATE TABLE IF NOT EXISTS bookings(code TEXT PRIMARY KEY, destination_id INTEGER, visit_date TEXT, qty INTEGER, tier TEXT,
  unit_price INTEGER, total INTEGER, name TEXT, email TEXT, phone TEXT, status TEXT DEFAULT 'PAID',
  refund_amount INTEGER DEFAULT 0, refund_reason TEXT, created_at TEXT, updated_at TEXT);
"""

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    if 'db' in g: g.db.close()

def init():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute('SELECT 1 FROM regions').fetchone():
        d = json.load(open('data/destinations.json'))
        c.executemany('INSERT INTO regions VALUES(?,?,?)', [(r['slug'], r['name'], r['tagline']) for r in d['regions']])
        c.executemany('INSERT INTO destinations(id,region,name,description,price_label,price,price_max,price_weekend,photos) VALUES(?,?,?,?,?,?,?,?,?)',
            [(x['id'], x['region'], x['name'], x['description'], x['price_label'], x['price'], x['price_max'], x['price_weekend'], json.dumps(x['photos'])) for x in d['destinations']])
    c.commit(); c.close()

def dest(row):
    d = dict(row); d['photos'] = json.loads(d['photos'] or '[]'); return d

def err(msg, code=400): return jsonify(error=msg), code
def admin_only(): return request.headers.get('X-Admin-Token') == ADMIN_TOKEN

def unit_price(d, visit, tier):
    """Tarif per tiket: weekend (Sabtu/Minggu) bila ada; tier 'plus' memakai tarif atas (paket/wahana)."""
    if tier == 'plus' and d['price_max']: return d['price_max']
    if d['price_weekend'] and visit.weekday() >= 5: return d['price_weekend']
    return d['price'] or 0

def sold(dest_id, day, exclude=None):
    r = db().execute("SELECT COALESCE(SUM(qty),0) FROM bookings WHERE destination_id=? AND visit_date=? AND status='PAID' AND code!=?", (dest_id, day, exclude or '')).fetchone()
    return r[0]

def parse_visit(s):
    try: v = date.fromisoformat(s)
    except Exception: return None, 'Tanggal kunjungan tidak valid (format YYYY-MM-DD)'
    if v < date.today(): return None, 'Tanggal kunjungan tidak boleh di masa lalu'
    return v, None

# ---------- Wilayah & Destinasi ----------
@app.get('/api/regions')
def regions():
    rows = db().execute('SELECT r.*, (SELECT COUNT(*) FROM destinations d WHERE d.region=r.slug) AS total FROM regions r').fetchall()
    return jsonify([dict(r) for r in rows])

@app.get('/api/destinations')
def list_dest():
    q, reg = request.args.get('q', ''), request.args.get('region')
    sql, args = 'SELECT * FROM destinations WHERE name LIKE ?', [f'%{q}%']
    if reg: sql += ' AND region=?'; args.append(reg)
    return jsonify([dest(r) for r in db().execute(sql + ' ORDER BY id', args)])

@app.get('/api/destinations/<int:i>')
def get_dest(i):
    r = db().execute('SELECT * FROM destinations WHERE id=?', (i,)).fetchone()
    return jsonify(dest(r)) if r else err('Wisata tidak ditemukan', 404)

FIELDS = ['region', 'name', 'description', 'price_label', 'price', 'price_max', 'price_weekend', 'daily_quota']

@app.post('/api/destinations')
def create_dest():
    if not admin_only(): return err('Token admin diperlukan', 401)
    b = request.get_json(force=True)
    if not b.get('name') or not b.get('region'): return err('name dan region wajib diisi')
    vals = [b.get(f) for f in FIELDS]
    cur = db().execute(f"INSERT INTO destinations({','.join(FIELDS)},photos) VALUES({','.join('?'*len(FIELDS))},?)", vals + [json.dumps(b.get('photos', []))])
    db().commit(); return get_dest(cur.lastrowid), 201

@app.put('/api/destinations/<int:i>')
def update_dest(i):
    if not admin_only(): return err('Token admin diperlukan', 401)
    b = request.get_json(force=True); sets = [f for f in FIELDS + ['photos'] if f in b]
    if not sets: return err('Tidak ada field yang diubah')
    vals = [json.dumps(b[f]) if f == 'photos' else b[f] for f in sets]
    db().execute(f"UPDATE destinations SET {','.join(f+'=?' for f in sets)} WHERE id=?", vals + [i]); db().commit()
    return get_dest(i)

@app.delete('/api/destinations/<int:i>')
def delete_dest(i):
    if not admin_only(): return err('Token admin diperlukan', 401)
    if db().execute("SELECT 1 FROM bookings WHERE destination_id=? AND status='PAID'", (i,)).fetchone():
        return err('Masih ada pesanan aktif untuk wisata ini', 409)
    db().execute('DELETE FROM destinations WHERE id=?', (i,)); db().commit(); return '', 204

@app.get('/api/destinations/<int:i>/calendar')
def calendar(i):
    """Ketersediaan & harga per tanggal untuk satu bulan: ?month=YYYY-MM"""
    r = db().execute('SELECT * FROM destinations WHERE id=?', (i,)).fetchone()
    if not r: return err('Wisata tidak ditemukan', 404)
    try: y, m = map(int, request.args.get('month', date.today().strftime('%Y-%m')).split('-')); d0 = date(y, m, 1)
    except Exception: return err('month harus YYYY-MM')
    out, d = [], d0
    while d.month == m:
        out.append(dict(date=d.isoformat(), price=unit_price(r, d, 'base'), price_plus=r['price_max'], past=d < date.today(),
                        remaining=max(0, r['daily_quota'] - sold(i, d.isoformat()))))
        d += timedelta(days=1)
    return jsonify(out)

# ---------- Pemesanan ----------
def booking(row):
    b = dict(row); v = date.fromisoformat(b['visit_date']); days = (v - date.today()).days
    b['refundable_percent'] = refund_percent(days) if b['status'] == 'PAID' else 0
    b['destination'] = db().execute('SELECT name, region FROM destinations WHERE id=?', (b['destination_id'],)).fetchone()
    b['destination'] = dict(b['destination']) if b['destination'] else None
    return b

def refund_percent(days_left):  # kebijakan refund
    return 100 if days_left >= 3 else 50 if days_left >= 1 else 0

def new_code(): return 'WJ-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

@app.post('/api/bookings')
def create_booking():
    b = request.get_json(force=True)
    d = db().execute('SELECT * FROM destinations WHERE id=?', (b.get('destination_id'),)).fetchone()
    if not d: return err('Wisata tidak ditemukan', 404)
    visit, e = parse_visit(b.get('visit_date', ''))
    if e: return err(e)
    qty = int(b.get('qty', 0) or 0)
    if not 1 <= qty <= 20: return err('Jumlah tiket 1-20')
    if not (b.get('name') and '@' in str(b.get('email', ''))): return err('Nama dan email valid wajib diisi')
    tier = 'plus' if b.get('tier') == 'plus' and d['price_max'] else 'base'
    if sold(d['id'], visit.isoformat()) + qty > d['daily_quota']: return err('Kuota tanggal tersebut tidak mencukupi', 409)
    up = unit_price(d, visit, tier); now = datetime.now().isoformat(timespec='seconds'); code = new_code()
    db().execute('INSERT INTO bookings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (code, d['id'], visit.isoformat(), qty, tier, up, up * qty,
        b['name'], b['email'].lower(), b.get('phone', ''), 'PAID', 0, None, now, now))  # pembayaran disimulasikan (langsung PAID)
    db().commit()
    
    import mailer
    b_resp = booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone())
    try:
        mailer.send_booking_success(b_resp)
        b_resp['email_sent'] = True
    except Exception as e:
        app.logger.error(f"Mailer error: {e}")
        b_resp['email_sent'] = False
    
    return jsonify(b_resp), 201

@app.get('/api/bookings')
def list_bookings():
    email, code = request.args.get('email', '').lower(), request.args.get('code', '')
    if not (email or code or admin_only()): return err('Isi email atau kode booking')
    sql, args = 'SELECT * FROM bookings WHERE 1=1', []
    if email: sql += ' AND email=?'; args.append(email)
    if code: sql += ' AND code=?'; args.append(code)
    return jsonify([booking(r) for r in db().execute(sql + ' ORDER BY created_at DESC', args)])

def one(code):
    return db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone()

@app.get('/api/bookings/<code>')
def get_booking(code):
    r = one(code); return jsonify(booking(r)) if r else err('Booking tidak ditemukan', 404)

@app.put('/api/bookings/<code>')
def update_booking(code):
    """Ubah jadwal / jumlah / data pemesan (hanya status PAID)."""
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if r['status'] != 'PAID': return err('Booking tidak dapat diubah', 409)
    b = request.get_json(force=True); d = db().execute('SELECT * FROM destinations WHERE id=?', (r['destination_id'],)).fetchone()
    visit, e = parse_visit(b.get('visit_date', r['visit_date']))
    if e: return err(e)
    qty = int(b.get('qty', r['qty']))
    if not 1 <= qty <= 20: return err('Jumlah tiket 1-20')
    if sold(d['id'], visit.isoformat(), code) + qty > d['daily_quota']: return err('Kuota tidak mencukupi', 409)
    up = unit_price(d, visit, r['tier'])
    db().execute('UPDATE bookings SET visit_date=?,qty=?,unit_price=?,total=?,name=?,phone=?,updated_at=? WHERE code=?',
        (visit.isoformat(), qty, up, up * qty, b.get('name', r['name']), b.get('phone', r['phone']), datetime.now().isoformat(timespec='seconds'), code))
    db().commit()
    
    import mailer
    b_resp = get_booking(code).json
    try:
        mailer.send_booking_update(b_resp)
    except Exception as e:
        app.logger.error(f"Mailer error: {e}")
    return jsonify(b_resp)

@app.post('/api/bookings/<code>/refund')
def refund(code):
    """Refund: >=3 hari sebelum kunjungan 100%, 1-2 hari 50%, hari-H/lewat tidak bisa."""
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if r['status'] != 'PAID': return err('Booking sudah dibatalkan / di-refund', 409)
    pct = refund_percent((date.fromisoformat(r['visit_date']) - date.today()).days)
    if pct == 0: return err('Refund tidak tersedia pada hari kunjungan atau setelahnya', 422)
    amount = r['total'] * pct // 100; reason = (request.get_json(silent=True) or {}).get('reason', '')
    db().execute("UPDATE bookings SET status='REFUNDED', refund_amount=?, refund_reason=?, updated_at=? WHERE code=?",
        (amount, reason, datetime.now().isoformat(timespec='seconds'), code))
    db().commit()
    
    import mailer
    b_resp = get_booking(code).json
    try:
        mailer.send_booking_refund(b_resp)
    except Exception as e:
        app.logger.error(f"Mailer error: {e}")
    return jsonify(b_resp)

@app.delete('/api/bookings/<code>')
def delete_booking(code):
    if not admin_only(): return err('Token admin diperlukan', 401)
    db().execute('DELETE FROM bookings WHERE code=?', (code,)); db().commit(); return '', 204

@app.get('/')
def index(): return send_from_directory('static', 'index.html')

init()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
