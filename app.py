"""Wisata Jogja - Backend REST API (Flask + SQLite). Jalankan: python app.py"""
import json, os, random, re, sqlite3, string, time
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

# ── Konfigurasi ────────────────────────────────────────────────────────────────
IS_VERCEL = bool(os.environ.get('VERCEL'))
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'admin123')
DB = os.getenv('DB_PATH', '/tmp/wisata.db' if IS_VERCEL else 'wisata.db')
SECRET_KEY = os.getenv('SECRET_KEY', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@wisatajogja.id')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'Admin12345')

if not SECRET_KEY:
    import secrets
    SECRET_KEY = secrets.token_hex(32)
    print("⚠️  SECRET_KEY tidak di-set. Gunakan env SECRET_KEY untuk produksi.")

if ADMIN_PASSWORD == 'Admin12345':
    print("⚠️  Gunakan env ADMIN_PASSWORD untuk mengganti password admin default.")

app = Flask(__name__, static_folder=None, static_url_path=None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

# ── Serializer Token ────────────────────────────────────────────────────────────
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
_ser = URLSafeTimedSerializer(SECRET_KEY)
TOKEN_MAX_AGE = 7 * 24 * 3600  # 7 hari

def make_token(user_id):
    return _ser.dumps(user_id, salt='auth')

def verify_token(token):
    try:
        return _ser.loads(token, salt='auth', max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

# ── Rate Limiter Login ──────────────────────────────────────────────────────────
_login_fails = defaultdict(list)

def is_rate_limited(ip):
    now = time.time()
    _login_fails[ip] = [t for t in _login_fails[ip] if now - t < 60]
    return len(_login_fails[ip]) >= 5

def record_fail(ip):
    _login_fails[ip].append(time.time())

# ── Schema ──────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS regions(slug TEXT PRIMARY KEY, name TEXT, tagline TEXT);
CREATE TABLE IF NOT EXISTS destinations(id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT, name TEXT, description TEXT,
  price_label TEXT, price INTEGER, price_max INTEGER, price_weekend INTEGER, photos TEXT DEFAULT '[]', daily_quota INTEGER DEFAULT 500);
CREATE TABLE IF NOT EXISTS bookings(code TEXT PRIMARY KEY, destination_id INTEGER, visit_date TEXT, qty INTEGER, tier TEXT,
  unit_price INTEGER, total INTEGER, name TEXT, email TEXT, phone TEXT, status TEXT DEFAULT 'PAID',
  refund_amount INTEGER DEFAULT 0, refund_reason TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, role TEXT DEFAULT 'user', created_at TEXT);
"""

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    if 'db' in g: g.db.close()

def init():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    # Tambah kolom user_id ke bookings bila belum ada (upgrade database lama)
    cols = [row[1] for row in c.execute("PRAGMA table_info(bookings)").fetchall()]
    if 'user_id' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id)")
    c.commit()
    # Isi data awal (idempotent: hanya jika tabel kosong)
    if not c.execute('SELECT 1 FROM regions').fetchone():
        d = json.load(open(os.path.join(BASE_DIR, 'data', 'destinations.json')))
        c.executemany('INSERT INTO regions VALUES(?,?,?)', [(r['slug'], r['name'], r['tagline']) for r in d['regions']])
        c.executemany('INSERT INTO destinations(id,region,name,description,price_label,price,price_max,price_weekend,photos) VALUES(?,?,?,?,?,?,?,?,?)',
            [(x['id'], x['region'], x['name'], x['description'], x['price_label'], x['price'], x['price_max'], x['price_weekend'], json.dumps(x['photos'])) for x in d['destinations']])
    # Admin otomatis
    if not c.execute('SELECT 1 FROM users WHERE email=?', (ADMIN_EMAIL,)).fetchone():
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
            ('Admin', ADMIN_EMAIL, generate_password_hash(ADMIN_PASSWORD), 'admin', datetime.now().isoformat(timespec='seconds')))
    c.commit(); c.close()

# ── Helpers ─────────────────────────────────────────────────────────────────────
def dest(row):
    d = dict(row); d['photos'] = json.loads(d['photos'] or '[]'); return d

def err(msg, code=400): return jsonify(error=msg), code

def admin_only():
    """Menerima header X-Admin-Token ATAU token user dengan role admin."""
    if request.headers.get('X-Admin-Token') == ADMIN_TOKEN:
        return True
    u = current_user()
    return u and u['role'] == 'admin'

def current_user():
    """Ambil user dari Bearer token. Return None bila tidak ada/expired."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    uid = verify_token(auth[7:])
    if not uid:
        return None
    row = db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    return dict(row) if row else None

def require_login():
    u = current_user()
    if not u:
        return err('Login diperlukan', 401)
    return u

def unit_price(d, visit, tier):
    if tier == 'plus' and d['price_max']: return d['price_max']
    if d['price_weekend'] and visit.weekday() >= 5: return d['price_weekend']
    return d['price'] or 0

def sold(dest_id, day, exclude=None):
    r = db().execute("SELECT COALESCE(SUM(qty),0) FROM bookings WHERE destination_id=? AND visit_date=? AND status='PAID' AND code!=?",
        (dest_id, day, exclude or '')).fetchone()
    return r[0]

def parse_visit(s):
    try: v = date.fromisoformat(s)
    except Exception: return None, 'Tanggal kunjungan tidak valid (format YYYY-MM-DD)'
    if v < date.today(): return None, 'Tanggal kunjungan tidak boleh di masa lalu'
    return v, None

def safe_user(u):
    """Return user dict tanpa password_hash."""
    return {k: v for k, v in u.items() if k != 'password_hash'}

# ── Auth Endpoints ──────────────────────────────────────────────────────────────
@app.post('/api/auth/register')
def register():
    b = request.get_json(force=True) or {}
    name = (b.get('name') or '').strip()
    email = (b.get('email') or '').strip().lower()
    password = b.get('password') or ''
    if not name: return err('Nama wajib diisi')
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email): return err('Format email tidak valid')
    if len(password) < 8: return err('Password minimal 8 karakter', 400)
    if db().execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
        return err('Email sudah terdaftar', 409)
    phash = generate_password_hash(password)
    cur = db().execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (name, email, phash, 'user', datetime.now().isoformat(timespec='seconds')))
    db().commit()
    uid = cur.lastrowid
    u = dict(db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    token = make_token(uid)
    return jsonify(token=token, user=safe_user(u)), 201

@app.post('/api/auth/login')
def login():
    ip = request.remote_addr
    if is_rate_limited(ip):
        return err('Terlalu banyak percobaan login. Coba lagi dalam 1 menit.', 429)
    b = request.get_json(force=True) or {}
    email = (b.get('email') or '').strip().lower()
    password = b.get('password') or ''
    row = db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    if not row or not check_password_hash(row['password_hash'], password):
        record_fail(ip)
        return err('Email atau kata sandi salah', 401)
    u = dict(row)
    token = make_token(u['id'])
    return jsonify(token=token, user=safe_user(u))

@app.get('/api/auth/me')
def me():
    u = require_login()
    if isinstance(u, tuple): return u
    return jsonify(safe_user(u))

@app.post('/api/auth/logout')
def logout():
    return '', 204

# ── Wilayah & Destinasi ─────────────────────────────────────────────────────────
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
    if not admin_only(): return err('Akses ditolak', 403)
    b = request.get_json(force=True)
    if not b.get('name') or not b.get('region'): return err('name dan region wajib diisi')
    vals = [b.get(f) for f in FIELDS]
    cur = db().execute(f"INSERT INTO destinations({','.join(FIELDS)},photos) VALUES({','.join('?'*len(FIELDS))},?)", vals + [json.dumps(b.get('photos', []))])
    db().commit(); return get_dest(cur.lastrowid), 201

@app.put('/api/destinations/<int:i>')
def update_dest(i):
    if not admin_only(): return err('Akses ditolak', 403)
    b = request.get_json(force=True); sets = [f for f in FIELDS + ['photos'] if f in b]
    if not sets: return err('Tidak ada field yang diubah')
    vals = [json.dumps(b[f]) if f == 'photos' else b[f] for f in sets]
    db().execute(f"UPDATE destinations SET {','.join(f+'=?' for f in sets)} WHERE id=?", vals + [i]); db().commit()
    return get_dest(i)

@app.delete('/api/destinations/<int:i>')
def delete_dest(i):
    if not admin_only(): return err('Akses ditolak', 403)
    if db().execute("SELECT 1 FROM bookings WHERE destination_id=? AND status='PAID'", (i,)).fetchone():
        return err('Masih ada pesanan aktif untuk wisata ini', 409)
    db().execute('DELETE FROM destinations WHERE id=?', (i,)); db().commit(); return '', 204

@app.get('/api/destinations/<int:i>/calendar')
def calendar(i):
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

# ── Pemesanan ───────────────────────────────────────────────────────────────────
def booking(row):
    b = dict(row); v = date.fromisoformat(b['visit_date']); days = (v - date.today()).days
    b['refundable_percent'] = refund_percent(days) if b['status'] == 'PAID' else 0
    b['destination'] = db().execute('SELECT name, region FROM destinations WHERE id=?', (b['destination_id'],)).fetchone()
    b['destination'] = dict(b['destination']) if b['destination'] else None
    return b

def refund_percent(days_left):
    return 100 if days_left >= 3 else 50 if days_left >= 1 else 0

def new_code(): return 'WJ-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def one(code):
    return db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone()

@app.post('/api/bookings')
def create_booking():
    u = require_login()
    if isinstance(u, tuple): return u
    b = request.get_json(force=True)
    d = db().execute('SELECT * FROM destinations WHERE id=?', (b.get('destination_id'),)).fetchone()
    if not d: return err('Wisata tidak ditemukan', 404)
    visit, e = parse_visit(b.get('visit_date', ''))
    if e: return err(e)
    qty = int(b.get('qty', 0) or 0)
    if not 1 <= qty <= 20: return err('Jumlah tiket 1-20')
    # Nama dan email dari akun jika tidak dikirim
    name = (b.get('name') or u['name']).strip()
    email = (b.get('email') or u['email']).strip().lower()
    if not (name and '@' in email): return err('Nama dan email valid wajib diisi')
    tier = 'plus' if b.get('tier') == 'plus' and d['price_max'] else 'base'
    if sold(d['id'], visit.isoformat()) + qty > d['daily_quota']: return err('Kuota tanggal tersebut tidak mencukupi', 409)
    up = unit_price(d, visit, tier); now = datetime.now().isoformat(timespec='seconds'); code = new_code()
    db().execute('INSERT INTO bookings(code,destination_id,visit_date,qty,tier,unit_price,total,name,email,phone,status,refund_amount,refund_reason,created_at,updated_at,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (code, d['id'], visit.isoformat(), qty, tier, up, up * qty, name, email, b.get('phone', ''), 'PAID', 0, None, now, now, u['id']))
    db().commit()
    import mailer
    b_resp = booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone())
    try:
        mailer.send_booking_success(b_resp)
        b_resp['email_sent'] = True
    except Exception as ex:
        app.logger.error(f"Mailer error: {ex}")
        b_resp['email_sent'] = False
    return jsonify(b_resp), 201

@app.get('/api/bookings')
def list_bookings():
    u = current_user()
    email_q, code_q = request.args.get('email', '').lower(), request.args.get('code', '')
    # Admin bisa lihat semua dengan filter
    if admin_only():
        sql, args = 'SELECT * FROM bookings WHERE 1=1', []
        if email_q: sql += ' AND email=?'; args.append(email_q)
        if code_q: sql += ' AND code=?'; args.append(code_q)
        return jsonify([booking(r) for r in db().execute(sql + ' ORDER BY created_at DESC', args)])
    # User login: lihat pesanan milik sendiri
    if u:
        sql, args = 'SELECT * FROM bookings WHERE user_id=?', [u['id']]
        if code_q: sql += ' AND code=?'; args.append(code_q)
        return jsonify([booking(r) for r in db().execute(sql + ' ORDER BY created_at DESC', args)])
    # Legacy: cari via email+kode tanpa login
    if email_q or code_q:
        sql, args = 'SELECT * FROM bookings WHERE 1=1', []
        if email_q: sql += ' AND email=?'; args.append(email_q)
        if code_q: sql += ' AND code=?'; args.append(code_q)
        return jsonify([booking(r) for r in db().execute(sql + ' ORDER BY created_at DESC', args)])
    return err('Login atau isi email/kode booking', 401)

@app.get('/api/bookings/<code>')
def get_booking(code):
    r = one(code); return jsonify(booking(r)) if r else err('Booking tidak ditemukan', 404)

def can_modify_booking(r):
    """Cek apakah user boleh modify booking ini."""
    if admin_only(): return True
    u = current_user()
    if u and r['user_id'] == u['id']: return True
    return False

@app.put('/api/bookings/<code>')
def update_booking(code):
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if not can_modify_booking(r): return err('Akses ditolak', 403)
    if r['status'] != 'PAID': return err('Booking tidak dapat diubah', 409)
    b = request.get_json(silent=True) or {}
    # Hanya visit_date yang boleh dikirim
    extra = set(b.keys()) - {'visit_date'}
    if extra:
        return err('Hanya tanggal kunjungan yang dapat diubah')
    if 'visit_date' not in b:
        return err('visit_date wajib diisi')
    d = db().execute('SELECT * FROM destinations WHERE id=?', (r['destination_id'],)).fetchone()
    # Tanggal lama dan baru harus >= besok
    tomorrow = date.today() + timedelta(days=1)
    try:
        old_visit = date.fromisoformat(r['visit_date'])
    except Exception:
        return err('Tanggal lama tidak valid')
    try:
        new_visit = date.fromisoformat(b['visit_date'])
    except Exception:
        return err('Tanggal kunjungan tidak valid (format YYYY-MM-DD)')
    if old_visit < tomorrow:
        return err('Pesanan pada hari-H tidak dapat diubah tanggalnya')
    if new_visit < tomorrow:
        return err('Tanggal baru tidak boleh hari ini atau lampau')
    if sold(d['id'], new_visit.isoformat(), code) + r['qty'] > d['daily_quota']:
        return err('Kuota tidak mencukupi', 409)
    # Harga TERKUNCI: unit_price dan total tidak berubah
    db().execute('UPDATE bookings SET visit_date=?,updated_at=? WHERE code=?',
        (new_visit.isoformat(), datetime.now().isoformat(timespec='seconds'), code))
    db().commit()
    import mailer
    b_resp = get_booking(code).json
    try: mailer.send_booking_update(b_resp)
    except Exception as ex: app.logger.error(f"Mailer error: {ex}")
    return jsonify(b_resp)

@app.post('/api/bookings/<code>/refund')
def refund(code):
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if not can_modify_booking(r): return err('Akses ditolak', 403)
    if r['status'] != 'PAID': return err('Booking sudah dibatalkan / di-refund', 409)
    pct = refund_percent((date.fromisoformat(r['visit_date']) - date.today()).days)
    if pct == 0: return err('Refund tidak tersedia pada hari kunjungan atau setelahnya', 422)
    amount = r['total'] * pct // 100; reason = (request.get_json(silent=True) or {}).get('reason', '')
    db().execute("UPDATE bookings SET status='REFUNDED', refund_amount=?, refund_reason=?, updated_at=? WHERE code=?",
        (amount, reason, datetime.now().isoformat(timespec='seconds'), code))
    db().commit()
    import mailer
    b_resp = get_booking(code).json
    try: mailer.send_booking_refund(b_resp)
    except Exception as ex: app.logger.error(f"Mailer error: {ex}")
    return jsonify(b_resp)

@app.delete('/api/bookings/<code>')
def delete_booking(code):
    if not admin_only(): return err('Akses ditolak', 403)
    db().execute('DELETE FROM bookings WHERE code=?', (code,)); db().commit(); return '', 204

@app.get('/')
def index():
    return send_from_directory(PUBLIC_DIR, 'index.html')

@app.get('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(PUBLIC_DIR, 'static'), filename)

from flask_cors import CORS
CORS(app)

init()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=not IS_VERCEL)
