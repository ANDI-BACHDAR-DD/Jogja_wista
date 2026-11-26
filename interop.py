"""Contract 0.2 provider for Wisata Jogja (tourist_attraction).

A hold is a normal row in `bookings` with status PENDING and `expires_at`, so it counts against the
daily quota through the existing `sold()` rule and is visible to staff. Confirm records the simulated
payment (PENDING -> PAID), release cancels it, and a lapsed hold becomes EXPIRED. Rows created here
carry source = 'interop:<partner>' so a partner can only ever read its own holds.

Wire names follow 01_KONTRAK_INTEROP_0.2.md. No real money moves; every price is SIMULATED.
"""
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

CONTRACT_VERSION = '0.2.0'
HOLD_TTL_MIN = 15
OFFER_TTL_SEC = 5 * 60
MAX_QTY = 20
MAX_LIMIT = 100
REF_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
KEY_RE = re.compile(r'^[A-Za-z0-9_-]{16,100}$')
PHONE_RE = re.compile(r'^[0-9+\- ]{9,20}$')
HOLD_FIELDS = {'offerId', 'quantity', 'customer', 'externalRef', 'consent', 'notes'}
CUSTOMER_FIELDS = {'name', 'email', 'phone'}
REGION_PREFIX = 'diy:'


def attach(api_bp, deps):
    """Register the six interop routes on the blueprint. `deps` carries the app helpers."""
    db = deps['db']
    current_partner = deps['current_partner']
    check_rate = deps['check_partner_rate_limit']
    unit_price = deps['unit_price']
    sold = deps['sold']
    expire_stale = deps['expire_stale']
    now_iso = deps['now_iso']
    new_code = deps['new_code']
    parse_visit = deps['parse_visit']

    def ierr(status, code, message):
        # Contract shape {code, message}; `error` keeps the legacy Wisata envelope readable.
        return jsonify(code=code, message=message, error=message), status

    def signing_key():
        key = os.getenv('INTEROP_OFFER_SIGNING_KEY', '')
        return key if len(key) >= 32 else None

    def durable():
        # Honest by default: SQLite on a serverless /tmp is lost on restart. Operators who mount a
        # persistent volume (or move to a persistent database) declare it explicitly.
        flag = os.getenv('INTEROP_DURABLE_STORAGE', '').strip().lower()
        if flag in ('true', '1', 'yes'):
            return True
        if flag in ('false', '0', 'no'):
            return False
        raw_path = deps['db_path']()
        if raw_path.startswith('/tmp'):
            return False
        real_p = os.path.realpath(raw_path)
        tmp_dir = os.path.realpath(tempfile.gettempdir())
        if real_p.startswith('/tmp') or real_p.startswith('/private/tmp') or real_p.startswith(tmp_dir):
            return False
        return True

    def auth():
        """Return (partner, None) or (None, error response). Same partner keys as /partner/*."""
        partner = current_partner()
        if not partner:
            return None, ierr(401, 'UNAUTHORIZED', 'Partner token required.')
        ok, retry = check_rate(partner)
        if not ok:
            resp, status = ierr(429, 'RATE_LIMITED', 'Too many requests.')
            resp.headers['Retry-After'] = str(retry)
            return None, (resp, status)
        return partner, None

    def sign(partner, raw):
        return hmac.new(signing_key().encode(), f'offer-v1:{partner}:{raw}'.encode(), hashlib.sha256).hexdigest()

    def make_offer_id(partner, dest_id, day, qty, unit, expiry_ms):
        raw = f'v1.{dest_id}.{day}.{qty}.{unit}.{expiry_ms}'
        return f'{raw}.{sign(partner, raw)}'

    def parse_offer_id(partner, offer_id):
        if not isinstance(offer_id, str) or len(offer_id) > 400 or '.' not in offer_id:
            return None
        raw, _, sig = offer_id.rpartition('.')
        if not hmac.compare_digest(sig, sign(partner, raw)):
            return None
        parts = raw.split('.')
        if len(parts) != 6 or parts[0] != 'v1':
            return None
        try:
            dest_id, day, qty, unit, expiry = int(parts[1]), parts[2], int(parts[3]), int(parts[4]), int(parts[5])
        except ValueError:
            return None
        if expiry <= int(time.time() * 1000):
            return None
        return dest_id, day, qty, unit

    def iso_utc(naive_local):
        """bookings store naive local datetimes; the wire carries UTC with a Z."""
        dt = datetime.fromisoformat(naive_local).astimezone(timezone.utc)
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def region_slug(raw):
        slug = raw[len(REGION_PREFIX):] if raw.startswith(REGION_PREFIX) else raw
        row = db().execute('SELECT slug FROM regions WHERE slug=?', (slug,)).fetchone()
        return row['slug'] if row else None

    def lapse_holds():
        """Expire lapsed holds and erase customer data from holds that did not become reservations."""
        expire_stale()
        db().execute(
            "UPDATE bookings SET name='', email='', phone='' WHERE source LIKE 'interop:%' "
            "AND status IN ('EXPIRED','CANCELLED') AND (name!='' OR email!='' OR phone!='')")
        db().commit()

    def hold_row(partner, hold_id):
        return db().execute('SELECT * FROM bookings WHERE code=? AND source=?', (hold_id, 'interop:' + partner)).fetchone()

    def hold_value(r):
        state = {'PENDING': 'awaiting_payment', 'PAID': 'reserved', 'EXPIRED': 'expired', 'CANCELLED': 'cancelled',
                 'REFUNDED': 'cancelled'}.get(r['status'], 'expired')
        if state == 'awaiting_payment' and r['expires_at'] and r['expires_at'] <= now_iso():
            state = 'expired'
        dest = db().execute('SELECT name FROM destinations WHERE id=?', (r['destination_id'],)).fetchone()
        out = {
            'holdId': r['code'], 'externalRef': r['external_ref'], 'offerId': r['offer_id'], 'provider': 'wisata',
            'entityType': 'tourist_attraction', 'resourceId': str(r['destination_id']),
            'startDate': r['visit_date'], 'endDate': r['visit_date'], 'quantity': r['qty'],
            'totalPrice': r['total'], 'currency': 'IDR', 'priceType': 'SIMULATED', 'simulation': True,
            'reservationState': state, 'paymentState': 'paid' if state == 'reserved' else 'unpaid',
            'fulfillmentState': 'not_assigned',
            'expiresAt': iso_utc(r['expires_at']) if r['expires_at'] else None,
        }
        if state == 'reserved':
            out['fulfillmentState'] = 'ticket_issued'
            out['voucher'] = {
                'code': r['code'], 'note': 'Pembayaran disimulasikan. Tunjukkan kode ini di loket.',
                'destinationName': dest['name'] if dest else None, 'visitDate': r['visit_date'], 'quantity': r['qty'],
                'totalPrice': r['total'], 'currency': 'IDR', 'priceType': 'SIMULATED', 'simulation': True,
            }
        return out

    # ── GET /interop/capabilities ────────────────────────────────────────────
    @api_bp.get('/interop/capabilities')
    def interop_capabilities():
        _, e = auth()
        if e:
            return e
        if not signing_key():
            return ierr(503, 'INTEROP_NOT_CONFIGURED', 'Offer signing key missing.')
        return jsonify({
            'contract': CONTRACT_VERSION, 'provider': 'wisata', 'entityTypes': ['tourist_attraction'],
            'holds': True, 'holdTtlMinutes': HOLD_TTL_MIN, 'durableStorage': durable(), 'location': 'region',
            'requiredCustomerFields': ['name', 'email'], 'optionalCustomerFields': ['phone'],
            'maxQuantity': MAX_QTY, 'paymentSupported': False, 'paymentMode': 'simulated',
        })

    # ── GET /interop/offers ──────────────────────────────────────────────────
    @api_bp.get('/interop/offers')
    def interop_offers():
        partner, e = auth()
        if e:
            return e
        if not signing_key():
            return ierr(503, 'INTEROP_NOT_CONFIGURED', 'Offer signing key missing.')
        lapse_holds()
        visit, msg = parse_visit(request.args.get('startDate', '').strip())
        if msg:
            return ierr(400, 'INVALID_DATES', 'startDate must be YYYY-MM-DD and not in the past.')
        if request.args.get('entityType', 'tourist_attraction') != 'tourist_attraction':
            return jsonify(provider='wisata', generatedAt=iso_utc(now_iso()), offers=[])
        try:
            qty = int(request.args.get('quantity', 1))
            limit = int(request.args.get('limit', 50))
        except ValueError:
            return ierr(400, 'INVALID_FILTER', 'quantity and limit must be integers.')
        if not 1 <= qty <= MAX_QTY or limit < 1:
            return ierr(400, 'INVALID_FILTER', f'quantity must be 1-{MAX_QTY}.')
        limit = min(limit, MAX_LIMIT)
        region = request.args.get('regionId', '').strip()
        slug = None
        if region:
            slug = region_slug(region)
            if not slug:
                return ierr(400, 'INVALID_REGION', 'Unknown regionId.')
        # lat/lng/radiusKm are accepted and ignored: Wisata has no coordinates, so regionId decides.
        sql = 'SELECT * FROM destinations' + (' WHERE region=?' if slug else '') + ' ORDER BY name, id'
        rows = db().execute(sql, (slug,) if slug else ()).fetchall()
        day = visit.isoformat()
        expiry_ms = int((time.time() + OFFER_TTL_SEC) * 1000)
        expires_at = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        offers = []
        for d in rows:
            remaining = max(0, d['daily_quota'] - sold(d['id'], day))
            if remaining < qty:
                continue
            unit = unit_price(d, visit, 'base')
            photos = json.loads(d['photos'] or '[]')
            offers.append({
                'offerId': make_offer_id(partner, d['id'], day, qty, unit, expiry_ms), 'expiresAt': expires_at,
                'provider': 'wisata', 'entityType': 'tourist_attraction', 'resourceId': str(d['id']),
                'regionId': REGION_PREFIX + d['region'], 'name': d['name'], 'description': d['description'] or '',
                'imageUrl': photos[0] if photos else None, 'price': unit, 'priceUnit': 'ticket', 'currency': 'IDR',
                'priceType': 'SIMULATED', 'simulation': True, 'period': {'startDate': day, 'endDate': day},
                'quantity': qty, 'totalPrice': unit * qty, 'available': True, 'remaining': remaining,
                'location': {'lat': None, 'lng': None}, 'attributes': {'tier': 'base'},
            })
            if len(offers) >= limit:
                break
        return jsonify(provider='wisata', generatedAt=iso_utc(now_iso()), offers=offers)

    # ── POST /interop/holds ──────────────────────────────────────────────────
    @api_bp.post('/interop/holds')
    def interop_create_hold():
        partner, e = auth()
        if e:
            return e
        if not signing_key():
            return ierr(503, 'INTEROP_NOT_CONFIGURED', 'Offer signing key missing.')
        key = request.headers.get('Idempotency-Key', '')
        if not KEY_RE.match(key):
            return ierr(400, 'IDEMPOTENCY_REQUIRED', 'Valid Idempotency-Key (16-100 chars A-Za-z0-9_-) required.')
        if not (request.mimetype or '').lower() == 'application/json':
            return ierr(415, 'UNSUPPORTED_MEDIA_TYPE', 'Use application/json.')
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - HOLD_FIELDS:
            return ierr(400, 'BAD_JSON', 'Invalid hold request.')
        cust = body.get('customer')
        if body.get('consent') is not True:
            return ierr(400, 'CONSENT_REQUIRED', 'consent must be true before customer data is sent.')
        ext = body.get('externalRef')
        if not isinstance(ext, str) or not REF_RE.match(ext):
            return ierr(400, 'INVALID_HOLD', 'externalRef must be 1-64 characters of A-Z a-z 0-9 - _.')
        if not isinstance(cust, dict) or set(cust) - CUSTOMER_FIELDS:
            return ierr(400, 'INVALID_CUSTOMER', 'customer needs name and email (phone optional).')
        name = (cust.get('name') or '').strip() if isinstance(cust.get('name'), str) else ''
        email = (cust.get('email') or '').strip().lower() if isinstance(cust.get('email'), str) else ''
        phone = (cust.get('phone') or '').strip() if isinstance(cust.get('phone'), str) else ''
        if not 2 <= len(name) <= 100 or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) or len(email) > 120 \
                or (phone and not PHONE_RE.match(phone)):
            return ierr(400, 'INVALID_CUSTOMER', 'Valid name and email are required; phone is optional.')
        if isinstance(body.get('notes'), str) and len(body['notes']) > 500:
            return ierr(400, 'INVALID_HOLD', 'notes too long.')
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        source = 'interop:' + partner

        lapse_holds()
        old = db().execute('SELECT * FROM bookings WHERE source=? AND (idempotency_key=? OR external_ref=?) '
                           'ORDER BY CASE WHEN idempotency_key=? THEN 0 ELSE 1 END LIMIT 1',
                           (source, key, ext, key)).fetchone()
        if old:
            if old['request_fingerprint'] != fingerprint or old['idempotency_key'] != key:
                return ierr(409, 'IDEMPOTENCY_CONFLICT', 'Key or externalRef already used for a different request.')
            return jsonify(hold_value(old)), 200

        parsed = parse_offer_id(partner, body.get('offerId'))
        if not parsed:
            return ierr(422, 'INVALID_OFFER', 'Offer expired or invalid; obtain a new offer.')
        dest_id, day, qty, unit = parsed
        if body.get('quantity') is not None and body['quantity'] != qty:
            return ierr(422, 'INVALID_OFFER', 'quantity does not match the offer.')
        d = db().execute('SELECT * FROM destinations WHERE id=?', (dest_id,)).fetchone()
        visit, msg = parse_visit(day)
        if not d or msg or unit_price(d, visit, 'base') != unit:
            return ierr(422, 'INVALID_OFFER', 'Offer no longer matches the current catalog.')

        conn = db()
        conn.execute('BEGIN IMMEDIATE')  # serialise the quota check and the insert
        try:
            if sold(d['id'], day) + qty > d['daily_quota']:
                conn.rollback()
                return ierr(409, 'NOT_AVAILABLE', 'Not enough tickets left on that date.')
            code, now = new_code(), now_iso()
            expires = (datetime.now() + timedelta(minutes=HOLD_TTL_MIN)).isoformat(timespec='seconds')
            conn.execute(
                'INSERT INTO bookings(code,destination_id,visit_date,qty,tier,unit_price,total,name,email,phone,status,'
                'refund_amount,refund_reason,created_at,updated_at,user_id,expires_at,source,external_ref,idempotency_key,'
                'request_fingerprint,offer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (code, d['id'], day, qty, 'base', unit, unit * qty, name, email, phone, 'PENDING', 0, None, now, now,
                 None, expires, source, ext, key, fingerprint, body['offerId']))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return jsonify(hold_value(hold_row(partner, code))), 201

    # ── GET /interop/holds/{id} ──────────────────────────────────────────────
    @api_bp.get('/interop/holds/<hold_id>')
    def interop_get_hold(hold_id):
        partner, e = auth()
        if e:
            return e
        lapse_holds()
        r = hold_row(partner, hold_id)
        if not r:
            return ierr(404, 'NOT_FOUND', 'Hold not found.')
        return jsonify(hold_value(r))

    def guarded(hold_id):
        partner, e = auth()
        if e:
            return None, None, e
        if not KEY_RE.match(request.headers.get('Idempotency-Key', '')):
            return None, None, ierr(400, 'IDEMPOTENCY_REQUIRED', 'Valid Idempotency-Key required.')
        lapse_holds()
        r = hold_row(partner, hold_id)
        if not r:
            return None, None, ierr(404, 'NOT_FOUND', 'Hold not found.')
        return partner, r, None

    # ── POST /interop/holds/{id}/confirm ─────────────────────────────────────
    @api_bp.post('/interop/holds/<hold_id>/confirm')
    def interop_confirm(hold_id):
        partner, r, e = guarded(hold_id)
        if e:
            return e
        if r['status'] == 'PENDING':
            now = now_iso()
            # The simulated payment is recorded here; the ticket is only valid once PAID.
            cur = db().execute(
                "UPDATE bookings SET status='PAID', paid_at=?, payment_method='simulated', expires_at=NULL, updated_at=? "
                "WHERE code=? AND source=? AND status='PENDING' AND expires_at > ?",
                (now, now, hold_id, 'interop:' + partner, now))
            db().commit()
            r = hold_row(partner, hold_id)
            if cur.rowcount == 0 and r['status'] != 'PAID':
                lapse_holds()
                return ierr(409, 'HOLD_EXPIRED', 'Hold expired before confirmation.')
        if r['status'] == 'EXPIRED':
            return ierr(409, 'HOLD_EXPIRED', 'Hold expired before confirmation.')
        if r['status'] == 'CANCELLED':
            return ierr(409, 'HOLD_RELEASED', 'Hold was released.')
        return jsonify(hold_value(r))

    # ── POST /interop/holds/{id}/release ─────────────────────────────────────
    @api_bp.post('/interop/holds/<hold_id>/release')
    def interop_release(hold_id):
        partner, r, e = guarded(hold_id)
        if e:
            return e
        if r['status'] == 'PAID':
            return ierr(409, 'ALREADY_CONFIRMED', 'Confirmed hold cannot be released.')
        if r['status'] == 'PENDING':
            db().execute(
                "UPDATE bookings SET status='CANCELLED', name='', email='', phone='', expires_at=NULL, updated_at=? "
                "WHERE code=? AND source=? AND status='PENDING'", (now_iso(), hold_id, 'interop:' + partner))
            db().commit()
            r = hold_row(partner, hold_id)
        return jsonify(hold_value(r))
