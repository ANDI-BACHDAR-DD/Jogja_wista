"""Wisata Jogja - Backend REST API (Flask + SQLite). Jalankan: python app.py"""
import json, os, random, re, sqlite3, string, time, uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from flask import Flask, Blueprint, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

# ── Konfigurasi ────────────────────────────────────────────────────────────────
IS_VERCEL = bool(os.environ.get('VERCEL'))
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', 'admin123')
DB = os.getenv('DB_PATH', '/tmp/wisata.db' if IS_VERCEL else 'wisata.db')
SECRET_KEY = os.getenv('SECRET_KEY', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@wisatajogja.id')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'Admin12345')
PAYMENT_WINDOW_MIN = 15  # Menit kedaluwarsa pembayaran simulasi
WEEKEND_SURCHARGE = int(os.getenv('WEEKEND_SURCHARGE', '5000'))  # 0 = nonaktif

if not SECRET_KEY:
    import secrets
    SECRET_KEY = secrets.token_hex(32)
    print("⚠️  SECRET_KEY tidak di-set. Gunakan env SECRET_KEY untuk produksi.")

if ADMIN_PASSWORD == 'Admin12345':
    print("⚠️  Gunakan env ADMIN_PASSWORD untuk mengganti password admin default.")

app = Flask(__name__, static_folder=None, static_url_path=None)
api_bp = Blueprint('api', __name__)

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
    # Upgrade database lama: tambah kolom via ALTER TABLE (dicek dengan PRAGMA)
    cols = [row[1] for row in c.execute("PRAGMA table_info(bookings)").fetchall()]
    if 'user_id' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if 'expires_at' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN expires_at TEXT")
    if 'paid_at' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN paid_at TEXT")
    if 'payment_method' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN payment_method TEXT")
    if 'pending_visit_date' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN pending_visit_date TEXT")
    if 'pending_unit_price' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN pending_unit_price INTEGER")
    if 'due_amount' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN due_amount INTEGER")
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

# ── Error Codes & Helpers ────────────────────────────────────────────────────────
ERROR_CODES = {
    400: 'VALIDATION_ERROR',
    401: 'UNAUTHORIZED',
    403: 'FORBIDDEN',
    404: 'NOT_FOUND',
    409: 'CONFLICT',
    410: 'GONE',
    422: 'UNPROCESSABLE',
    429: 'RATE_LIMITED',
    500: 'INTERNAL_ERROR',
    502: 'UPSTREAM_ERROR',
    503: 'INTEGRATION_NOT_CONFIGURED',
}

def dest(row):
    d = dict(row); d['photos'] = json.loads(d['photos'] or '[]'); return d

def err(msg, code=400, err_code=None):
    c = err_code or ERROR_CODES.get(code, 'INTERNAL_ERROR' if code >= 500 else 'VALIDATION_ERROR')
    return jsonify(error=msg, code=c), code

@app.errorhandler(404)
def handle_404(e):
    return jsonify(error="Tidak ditemukan", code="NOT_FOUND"), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify(error="Metode tidak diizinkan", code="VALIDATION_ERROR"), 405

@app.errorhandler(500)
def handle_500(e):
    return jsonify(error="Terjadi kesalahan pada server", code="INTERNAL_ERROR"), 500

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    code_str = ERROR_CODES.get(e.code, 'VALIDATION_ERROR' if e.code < 500 else 'INTERNAL_ERROR')
    return jsonify(error=e.description or str(e), code=code_str), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {e}")
    return jsonify(error="Terjadi kesalahan pada server", code="INTERNAL_ERROR"), 500

@app.before_request
def assign_request_id():
    g.request_id = request.headers.get('X-Request-Id') or str(uuid.uuid4())
    app.logger.info(f"[{g.request_id}] {request.method} {request.path}")

@app.after_request
def handle_cors_and_request_id(response):
    req_id = getattr(g, 'request_id', None) or str(uuid.uuid4())
    response.headers['X-Request-Id'] = req_id
    
    cors_env = os.environ.get('CORS_ORIGINS', '').strip()
    origins = [o.strip() for o in cors_env.split(',') if o.strip()] if cors_env else []
    
    if request.path.startswith('/api'):
        eff_method = request.headers.get('Access-Control-Request-Method', request.method)
        if not origins:
            if eff_method not in ('GET', 'HEAD'):
                response.headers.pop('Access-Control-Allow-Origin', None)
                response.headers.pop('Access-Control-Allow-Methods', None)
                response.headers.pop('Access-Control-Allow-Headers', None)
        else:
            req_origin = request.headers.get('Origin')
            if req_origin not in origins and '*' not in origins:
                response.headers.pop('Access-Control-Allow-Origin', None)
                response.headers.pop('Access-Control-Allow-Methods', None)
                response.headers.pop('Access-Control-Allow-Headers', None)
    return response

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
    """Satu fungsi harga untuk kalender, booking, dan ubah tanggal."""
    is_we = visit.weekday() >= 5  # Sabtu=5, Minggu=6
    if tier == 'plus' and d['price_max']:
        base = d['price_max']
        if is_we and WEEKEND_SURCHARGE > 0 and base > 0:
            return base + WEEKEND_SURCHARGE
        return base
    if d['price_weekend'] and is_we:
        return d['price_weekend']  # Tarif spreadsheet sudah final
    base = d['price'] or 0
    if is_we and WEEKEND_SURCHARGE > 0 and base > 0:
        return base + WEEKEND_SURCHARGE
    return base

def is_weekend_date(visit):
    return visit.weekday() >= 5

def weekend_note(d, visit):
    """Keterangan legend akhir pekan untuk frontend."""
    if not is_weekend_date(visit) or WEEKEND_SURCHARGE <= 0:
        return None
    if d['price_weekend']:
        return 'Tarif akhir pekan'
    base = d['price'] or 0
    if base <= 0:
        return None
    return f'Akhir pekan +Rp{WEEKEND_SURCHARGE:,}'

def now_iso():
    return datetime.now().isoformat(timespec='seconds')

def expire_stale():
    """Lazy expiry (tanpa job, cocok untuk Vercel):
    - PENDING lewat waktu -> EXPIRED
    - PAID dengan pending_visit_date lewat waktu -> buang pending, tanggal lama tetap
    """
    now = now_iso()
    db().execute("UPDATE bookings SET status='EXPIRED', updated_at=? WHERE status='PENDING' AND expires_at IS NOT NULL AND expires_at < ?",
        (now, now))
    db().execute("UPDATE bookings SET pending_visit_date=NULL, pending_unit_price=NULL, due_amount=NULL, expires_at=NULL, updated_at=? WHERE status='PAID' AND pending_visit_date IS NOT NULL AND expires_at IS NOT NULL AND expires_at < ?",
        (now, now))
    db().commit()

def sold(dest_id, day, exclude=None):
    """Kuota terjual = PAID + PENDING yang belum kedaluwarsa."""
    r = db().execute("""SELECT COALESCE(SUM(qty),0) FROM bookings
        WHERE destination_id=? AND visit_date=? AND code!=?
          AND (status='PAID' OR (status='PENDING' AND expires_at IS NOT NULL AND expires_at > ?))""",
        (dest_id, day, exclude or '', now_iso())).fetchone()
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
@api_bp.post('/auth/register')
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

@api_bp.post('/auth/login')
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

@api_bp.get('/auth/me')
def me():
    u = require_login()
    if isinstance(u, tuple): return u
    return jsonify(safe_user(u))

@api_bp.post('/auth/logout')
def logout():
    return '', 204

# ── Health ──────────────────────────────────────────────────────────────────────
@api_bp.get('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": "wisata",
        "version": "1.0.0",
        "time": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    })

# ── Wilayah & Destinasi ─────────────────────────────────────────────────────────
@api_bp.get('/regions')
def regions():
    rows = db().execute('SELECT r.*, (SELECT COUNT(*) FROM destinations d WHERE d.region=r.slug) AS total FROM regions r').fetchall()
    return jsonify([dict(r) for r in rows])

@api_bp.get('/destinations')
def list_dest():
    q = request.args.get('q', '').strip()
    reg = request.args.get('region')
    ids_param = request.args.get('ids')
    
    where = ['1=1']
    args = []
    if q:
        where.append('name LIKE ?')
        args.append(f'%{q}%')
    if reg:
        where.append('region=?')
        args.append(reg)
    if ids_param is not None:
        ids = []
        for x in ids_param.split(','):
            x = x.strip()
            if x.isdigit():
                ids.append(int(x))
        ids = ids[:50]
        if ids:
            placeholders = ','.join('?' for _ in ids)
            where.append(f'id IN ({placeholders})')
            args.extend(ids)
        else:
            where.append('1=0')
            
    where_sql = ' AND '.join(where)
    count_row = db().execute(f'SELECT COUNT(*) FROM destinations WHERE {where_sql}', args).fetchone()
    total_count = count_row[0] if count_row else 0
    
    has_limit = 'limit' in request.args
    has_offset = 'offset' in request.args
    
    sql = f'SELECT * FROM destinations WHERE {where_sql} ORDER BY id'
    query_args = list(args)
    if has_limit or has_offset:
        try:
            limit = int(request.args.get('limit', 100))
        except (ValueError, TypeError):
            limit = 100
        limit = max(1, min(limit, 200))
        try:
            offset = int(request.args.get('offset', 0))
        except (ValueError, TypeError):
            offset = 0
        offset = max(0, offset)
        sql += ' LIMIT ? OFFSET ?'
        query_args.extend([limit, offset])
        
    rows = db().execute(sql, query_args).fetchall()
    resp = jsonify([dest(r) for r in rows])
    resp.headers['X-Total-Count'] = str(total_count)
    return resp

@api_bp.get('/destinations/<int:i>')
def get_dest(i):
    r = db().execute('SELECT * FROM destinations WHERE id=?', (i,)).fetchone()
    return jsonify(dest(r)) if r else err('Wisata tidak ditemukan', 404)

FIELDS = ['region', 'name', 'description', 'price_label', 'price', 'price_max', 'price_weekend', 'daily_quota']

@api_bp.post('/destinations')
def create_dest():
    if not admin_only(): return err('Akses ditolak', 403)
    b = request.get_json(force=True)
    if not b.get('name') or not b.get('region'): return err('name dan region wajib diisi')
    vals = [b.get(f) for f in FIELDS]
    cur = db().execute(f"INSERT INTO destinations({','.join(FIELDS)},photos) VALUES({','.join('?'*len(FIELDS))},?)", vals + [json.dumps(b.get('photos', []))])
    db().commit(); return get_dest(cur.lastrowid), 201

@api_bp.put('/destinations/<int:i>')
def update_dest(i):
    if not admin_only(): return err('Akses ditolak', 403)
    b = request.get_json(force=True); sets = [f for f in FIELDS + ['photos'] if f in b]
    if not sets: return err('Tidak ada field yang diubah')
    vals = [json.dumps(b[f]) if f == 'photos' else b[f] for f in sets]
    db().execute(f"UPDATE destinations SET {','.join(f+'=?' for f in sets)} WHERE id=?", vals + [i]); db().commit()
    return get_dest(i)

@api_bp.delete('/destinations/<int:i>')
def delete_dest(i):
    if not admin_only(): return err('Akses ditolak', 403)
    if db().execute("SELECT 1 FROM bookings WHERE destination_id=? AND status='PAID'", (i,)).fetchone():
        return err('Masih ada pesanan aktif untuk wisata ini', 409)
    db().execute('DELETE FROM destinations WHERE id=?', (i,)); db().commit(); return '', 204

@api_bp.get('/destinations/<int:i>/calendar')
def calendar(i):
    expire_stale()
    r = db().execute('SELECT * FROM destinations WHERE id=?', (i,)).fetchone()
    if not r: return err('Wisata tidak ditemukan', 404)
    try: y, m = map(int, request.args.get('month', date.today().strftime('%Y-%m')).split('-')); d0 = date(y, m, 1)
    except Exception: return err('month harus YYYY-MM')
    out, d = [], d0
    while d.month == m:
        is_we = d.weekday() >= 5
        price_plus = r['price_max']
        if is_we and WEEKEND_SURCHARGE > 0 and price_plus and price_plus > 0:
            price_plus += WEEKEND_SURCHARGE
        out.append(dict(date=d.isoformat(), price=unit_price(r, d, 'base'), price_plus=price_plus,
                        past=d < date.today(), is_weekend=is_we,
                        remaining=max(0, r['daily_quota'] - sold(i, d.isoformat())),
                        weekend_note=weekend_note(r, d)))
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

@api_bp.post('/bookings')
def create_booking():
    expire_stale()
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
    up = unit_price(d, visit, tier); now = now_iso(); code = new_code()
    expires_at = (datetime.now() + timedelta(minutes=PAYMENT_WINDOW_MIN)).isoformat(timespec='seconds')
    db().execute('INSERT INTO bookings(code,destination_id,visit_date,qty,tier,unit_price,total,name,email,phone,status,refund_amount,refund_reason,created_at,updated_at,user_id,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (code, d['id'], visit.isoformat(), qty, tier, up, up * qty, name, email, b.get('phone', ''), 'PENDING', 0, None, now, now, u['id'], expires_at))
    db().commit()
    b_resp = booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone())
    return jsonify(b_resp), 201

@api_bp.get('/bookings')
def list_bookings():
    expire_stale()
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

@api_bp.get('/bookings/<code>')
def get_booking(code):
    expire_stale()
    r = one(code); return jsonify(booking(r)) if r else err('Booking tidak ditemukan', 404)

def can_modify_booking(r):
    """Cek apakah user boleh modify booking ini."""
    if admin_only(): return True
    u = current_user()
    if u and r['user_id'] == u['id']: return True
    return False

PAYMENT_METHODS = {'qris', 'va_bca', 'va_bni', 'va_mandiri', 'gopay', 'ovo', 'dana'}

@api_bp.post('/bookings/<code>/pay')
def pay_booking(code):
    expire_stale()
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if not can_modify_booking(r): return err('Akses ditolak', 403)
    b = request.get_json(silent=True) or {}
    method = b.get('method', '')
    if method not in PAYMENT_METHODS:
        return err('Metode pembayaran tidak valid')
    # Kasus PENDING (booking baru)
    if r['status'] == 'PENDING':
        if r['expires_at'] and r['expires_at'] < now_iso():
            db().execute("UPDATE bookings SET status='EXPIRED', updated_at=? WHERE code=?", (now_iso(), code))
            db().commit()
            return err('Waktu pembayaran habis', 410)
        db().execute("UPDATE bookings SET status='PAID', paid_at=?, payment_method=?, updated_at=? WHERE code=?",
            (now_iso(), method, now_iso(), code))
        db().commit()
        import mailer
        b_resp = booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone())
        try:
            mailer.send_booking_success(b_resp)
            b_resp['email_sent'] = True
        except Exception as ex:
            app.logger.error(f"Mailer error: {ex}")
            b_resp['email_sent'] = False
        return jsonify(b_resp)
    # Booking sudah EXPIRED (mungkin baru saja di-mark oleh expire_stale)
    if r['status'] == 'EXPIRED':
        return err('Waktu pembayaran habis', 410)
    # Kasus PAID dengan pending_visit_date (Fase 3: bayar selisih)
    if r['status'] == 'PAID' and r['pending_visit_date']:
        if r['expires_at'] and r['expires_at'] < now_iso():
            # Pending kedaluwarsa: buang pending, tanggal lama tetap
            db().execute("UPDATE bookings SET pending_visit_date=NULL, pending_unit_price=NULL, due_amount=NULL, expires_at=NULL, updated_at=? WHERE code=?",
                (now_iso(), code))
            db().commit()
            return err('Waktu pembayaran habis', 410)
        due = r['due_amount'] or 0
        new_up = r['pending_unit_price'] or r['unit_price']
        qty = r['qty']
        db().execute("UPDATE bookings SET visit_date=?, unit_price=?, total=?, pending_visit_date=NULL, pending_unit_price=NULL, due_amount=NULL, expires_at=NULL, paid_at=?, payment_method=?, updated_at=? WHERE code=?",
            (r['pending_visit_date'], new_up, new_up * qty, now_iso(), method, now_iso(), code))
        db().commit()
        import mailer
        b_resp = booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone())
        try: mailer.send_booking_update(b_resp)
        except Exception as ex: app.logger.error(f"Mailer error: {ex}")
        return jsonify(b_resp)
    return err('Booking tidak dapat dibayar', 409)

@api_bp.post('/bookings/<code>/cancel')
def cancel_booking(code):
    expire_stale()
    r = one(code)
    if not r: return err('Booking tidak ditemukan', 404)
    if not can_modify_booking(r): return err('Akses ditolak', 403)
    if r['status'] != 'PENDING': return err('Hanya pesanan menunggu pembayaran yang dapat dibatalkan', 409)
    db().execute("UPDATE bookings SET status='EXPIRED', updated_at=? WHERE code=?", (now_iso(), code))
    db().commit()
    return jsonify(booking(db().execute('SELECT * FROM bookings WHERE code=?', (code,)).fetchone()))

@api_bp.put('/bookings/<code>')
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
    now = now_iso()
    new_up = unit_price(d, new_visit, r['tier'])
    old_up = r['unit_price']
    # Harga baru <= harga lama: tanggal langsung berubah, harga tetap
    if new_up <= old_up:
        db().execute('UPDATE bookings SET visit_date=?,updated_at=? WHERE code=?',
            (new_visit.isoformat(), now, code))
        db().commit()
        import mailer
        b_resp = get_booking(code).json
        try: mailer.send_booking_update(b_resp)
        except Exception as ex: app.logger.error(f"Mailer error: {ex}")
        return jsonify(b_resp)
    # Harga baru > harga lama: simpan pending, minta pembayaran selisih
    due = (new_up - old_up) * r['qty']
    expires_at = (datetime.now() + timedelta(minutes=PAYMENT_WINDOW_MIN)).isoformat(timespec='seconds')
    db().execute('UPDATE bookings SET pending_visit_date=?, pending_unit_price=?, due_amount=?, expires_at=?, updated_at=? WHERE code=?',
        (new_visit.isoformat(), new_up, due, expires_at, now, code))
    db().commit()
    b_resp = get_booking(code).json
    b_resp['requires_payment'] = True
    b_resp['due_amount'] = due
    b_resp['expires_at'] = expires_at
    return jsonify(b_resp)

@api_bp.post('/bookings/<code>/refund')
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

@api_bp.delete('/bookings/<code>')
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
CORS(app, resources={r"/api/*": {
    "origins": "*",
    "allow_headers": ["Authorization", "Content-Type", "Idempotency-Key", "X-Admin-Token"],
    "expose_headers": ["X-Request-Id", "X-Total-Count"],
    "methods": ["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"]
}})

app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(api_bp, url_prefix='/api/v1', name='api_v1')

init()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=not IS_VERCEL)
