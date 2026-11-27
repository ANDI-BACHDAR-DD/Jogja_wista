"""Add-ons at Wisata checkout (Contract 0.2 consumer): hotel and vehicle rental from the other providers.

One basket, one simulated payment, all in this app:

  main ticket booking (PENDING, itself a time-boxed hold)
    1. hold every chosen add-on at its provider        (definite refusal -> continue without that add-on)
    2. pay ONCE (simulated): the ticket booking becomes PAID
    3. confirm every held add-on, carrying the same simulated payment (provider records it as paid + voucher)
    any failure before the payment -> release every hold

Rules kept from the contract: intent is journaled before any request; stable idempotency keys; an unknown
answer never creates a second hold or a new key and is reconciled with GET hold; after a confirm succeeded
nothing is cancelled automatically (the order is PARTIAL and a person reconciles). No real money moves.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

PROVIDERS = {
    'hotel': {'entity': 'lodging', 'env': 'HOTEL'},
    'transport': {'entity': 'vehicle_rental', 'env': 'TRANSPORT'},
}
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
DEFINITE = {
    400: {'CONSENT_REQUIRED', 'VALIDATION_ERROR', 'INVALID_REQUEST', 'INVALID_IDEMPOTENCY_KEY', 'INVALID_EXTERNAL_REF', 'INVALID_HOLD',
          'INVALID_CUSTOMER', 'INVALID_QUANTITY', 'BAD_JSON', 'IDEMPOTENCY_REQUIRED', 'INVALID_PAYMENT', 'PAYMENT_NOT_SUPPORTED'},
    401: {'UNAUTHORIZED', 'INVALID_TOKEN'},
    409: {'NOT_AVAILABLE', 'HOLD_EXPIRED', 'HOLD_RELEASED', 'HOLD_NOT_ACTIVE', 'ALREADY_CONFIRMED'},
    415: {'UNSUPPORTED_MEDIA_TYPE'}, 422: {'INVALID_OFFER'}, 503: {'INTEROP_NOT_CONFIGURED'},
}


class Unknown(Exception):
    """The provider's answer cannot be trusted or never arrived: reconcile, never resend with a new key."""


class Rejected(Exception):
    def __init__(self, status, code):
        super().__init__(f'{status} {code}')
        self.status, self.code = status, code


def enabled():
    return os.getenv('ADDON_ENABLED', '').strip().lower() == 'true'


def _origin(provider):
    base = os.getenv(f"ADDON_{PROVIDERS[provider]['env']}_URL", '').strip().rstrip('/')
    token = os.getenv(f"ADDON_{PROVIDERS[provider]['env']}_TOKEN", '').strip()
    u = urllib.parse.urlparse(base)
    local = u.hostname in ('127.0.0.1', 'localhost') and os.getenv('ADDON_ALLOW_LOCAL', '') == '1'
    if not base or not (u.scheme == 'https' or (u.scheme == 'http' and local)) or u.username or u.path not in ('', '/'):
        return None, None
    if len(token) < 24 or re.search(r'\s', token):
        return None, None
    return base, token


def configured():
    return [p for p in PROVIDERS if enabled() and _origin(p)[0]]


def _http(method, url, headers, body, timeout):
    """Replaceable in tests. Returns (status, parsed_json_or_None)."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(512_001)
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(512_001), e.code
    if len(raw) > 512_000:
        raise Unknown('too large')
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _call(provider, method, path, key=None, body=None, query=None):
    base, token = _origin(provider)
    if not base:
        raise Rejected(503, 'ADDON_NOT_CONFIGURED')
    url = base + '/api/v1/interop' + path + ('?' + urllib.parse.urlencode(query) if query else '')
    headers = {'Accept': 'application/json', 'Authorization': 'Bearer ' + token}
    if key:
        headers['Idempotency-Key'] = key
    if body is not None:
        headers['Content-Type'] = 'application/json'
    try:
        status, data = _http(method, url, headers, body, 5)
    except Unknown:
        raise
    except Exception:
        raise Unknown('unreachable')
    if 200 <= status < 300:
        if not isinstance(data, dict):
            raise Unknown('invalid json')
        return data
    code = data.get('code') if isinstance(data, dict) else None
    if isinstance(code, str) and code in DEFINITE.get(status, ()):
        raise Rejected(status, code)
    raise Unknown(f'{status}')


def _day(d, n):
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def check_ready(provider):
    d = _call(provider, 'GET', '/capabilities')
    ok = (d.get('contract') == '0.2.0' and d.get('provider') == provider and d.get('holds') is True and d.get('durableStorage') is True
          and d.get('holdTtlMinutes') == 15 and PROVIDERS[provider]['entity'] in (d.get('entityTypes') or []))
    if not ok:
        raise Rejected(503, 'NOT_READY')
    return d.get('paymentMode') == 'simulated'


def recommend(visit_date, region_slug, provider, quantity=1):
    """Recommendations are scoped: same region as the ticket's destination, dates around the visit."""
    if provider not in PROVIDERS or not region_slug:
        return []
    check_ready(provider)
    d = _call(provider, 'GET', '/offers', query={
        'startDate': visit_date, 'endDate': _day(visit_date, 1), 'regionId': 'diy:' + region_slug,
        'entityType': PROVIDERS[provider]['entity'], 'quantity': 1, 'limit': 20})
    out = []
    for o in d.get('offers') or []:
        if o.get('regionId') == 'diy:' + region_slug and o.get('available') and isinstance(o.get('totalPrice'), int):
            out.append({k: o.get(k) for k in ('offerId', 'provider', 'name', 'description', 'imageUrl', 'regionId', 'totalPrice', 'period', 'remaining')})
    return out


# ── journal ────────────────────────────────────────────────────────────────
DDL = """CREATE TABLE IF NOT EXISTS addon_orders(
  booking_code TEXT NOT NULL, provider TEXT NOT NULL, offer_id TEXT NOT NULL, external_ref TEXT NOT NULL, expected_total INTEGER NOT NULL,
  state TEXT NOT NULL, hold_id TEXT, held_total INTEGER, voucher TEXT, payment_state TEXT, payment_reference TEXT, error_code TEXT,
  updated_at TEXT, PRIMARY KEY(booking_code, provider))"""


def ensure(conn):
    conn.execute(DDL)
    conn.commit()


def _h(*parts):
    return hashlib.sha256(':'.join(parts).encode()).hexdigest()


def hold_key(code, provider):
    return 'WH-' + _h('hold', code, provider)[:40]


def confirm_key(code, provider):
    return 'WC-' + _h('confirm', code, provider)[:40]


def release_key(code, provider):
    return 'WR-' + _h('release', code, provider)[:40]


def external_ref(code, provider):
    return ('WA-' + code + '-' + provider)[:64]


def payment_reference(code):
    return 'PAY_' + _h('pay', code)[:24]


def _row(conn, code, provider):
    return conn.execute('SELECT * FROM addon_orders WHERE booking_code=? AND provider=?', (code, provider)).fetchone()


def _set(conn, code, provider, now, **f):
    cols = ','.join(f'{k}=?' for k in f)
    conn.execute(f'UPDATE addon_orders SET {cols}, updated_at=? WHERE booking_code=? AND provider=?', (*f.values(), now, code, provider))
    conn.commit()


def list_orders(conn, code):
    ensure(conn)
    return [dict(r) for r in conn.execute('SELECT * FROM addon_orders WHERE booking_code=? ORDER BY provider', (code,)).fetchall()]


def public(r):
    return {'provider': r['provider'], 'state': r['state'], 'holdId': r['hold_id'], 'totalPrice': r['held_total'] or r['expected_total'],
            'voucher': json.loads(r['voucher']) if r['voucher'] else None, 'paymentState': r['payment_state'],
            **({'errorCode': r['error_code']} if r['error_code'] else {})}


def _hold_ok(provider, d, ref, offer_id):
    return (isinstance(d.get('holdId'), str) and ID_RE.match(d['holdId']) and d.get('reservationState') == 'awaiting_payment'
            and d.get('externalRef') == ref and isinstance(d.get('totalPrice'), int) and d.get('offerId') == offer_id)


def _release_one(conn, code, provider, now):
    r = _row(conn, code, provider)
    if not r or r['state'] != 'HELD':
        return
    _set(conn, code, provider, now, state='RELEASE_PENDING')
    try:
        _call(provider, 'POST', f"/holds/{r['hold_id']}/release", key=release_key(code, provider))
        _set(conn, code, provider, now, state='RELEASED')
    except Rejected as e:
        # Already released/expired is as good as released; confirmed is not ours to undo.
        _set(conn, code, provider, now, state='RELEASED' if e.code in ('HOLD_RELEASED', 'HOLD_EXPIRED') else 'RELEASE_UNKNOWN', error_code=e.code)
    except Unknown:
        _set(conn, code, provider, now, state='RELEASE_UNKNOWN', error_code='OUTCOME_UNKNOWN')


def run_checkout(conn, code, requests, customer, now, pay_main):
    """requests: [{provider, offerId, expectedTotalPrice}] (at most one per provider, caller validated).
    pay_main(): performs the single simulated payment of the ticket booking; raises on failure.
    Returns (status, items). status: CONFIRMED | PARTIAL | UNKNOWN | CANCELLED_ADDONS_NONE (no add-on requested/held)."""
    ensure(conn)
    # 1. hold everything (journal first)
    for rq in requests:
        p = rq['provider']
        if _row(conn, code, p):
            continue  # replay: the existing record decides, never a second hold
        conn.execute('INSERT INTO addon_orders(booking_code,provider,offer_id,external_ref,expected_total,state,updated_at) VALUES(?,?,?,?,?,?,?)',
                     (code, p, rq['offerId'], external_ref(code, p), rq['expectedTotalPrice'], 'HOLD_PENDING', now))
        conn.commit()
    unknown = False
    for rq in requests:
        p = rq['provider']
        r = _row(conn, code, p)
        # An unknown hold is retried with the SAME key and body: the contract guarantees a replay, never a second hold.
        if r['state'] not in ('HOLD_PENDING', 'HOLD_UNKNOWN'):
            continue
        try:
            check_ready(p)
            body = {'offerId': r['offer_id'], 'quantity': 1, 'externalRef': r['external_ref'], 'consent': True,
                    'customer': {k: v for k, v in customer.items() if v}}
            d = _call(p, 'POST', '/holds', key=hold_key(code, p), body=body)
            if not _hold_ok(p, d, r['external_ref'], r['offer_id']):
                raise Unknown('bad hold')
            if d['totalPrice'] != r['expected_total']:
                _set(conn, code, p, now, state='HELD', hold_id=d['holdId'], held_total=d['totalPrice'])
                _release_one(conn, code, p, now)
                _set(conn, code, p, now, error_code='OFFER_CHANGED')
                continue
            _set(conn, code, p, now, state='HELD', hold_id=d['holdId'], held_total=d['totalPrice'])
        except Rejected as e:
            # BPI: the add-on could not be held -> the main order continues without it.
            _set(conn, code, p, now, state='HOLD_FAILED', error_code=e.code)
        except Unknown:
            _set(conn, code, p, now, state='HOLD_UNKNOWN', error_code='OUTCOME_UNKNOWN')
            unknown = True
    held = [rq['provider'] for rq in requests if _row(conn, code, rq['provider'])['state'] == 'HELD']
    if unknown:
        for p in held:
            _release_one(conn, code, p, now)
        return 'UNKNOWN', [public(_row(conn, code, rq['provider'])) for rq in requests]

    # 2. pay once. Failure here gives every hold back.
    try:
        pay_main()
    except Exception:
        for p in held:
            _release_one(conn, code, p, now)
        raise

    # 3. confirm one by one with the same simulated payment. Nothing is cancelled after a confirm.
    ref = payment_reference(code)
    confirmed = 0
    status = 'CONFIRMED'
    for p in held:
        r = _row(conn, code, p)
        if r['state'] not in ('HELD', 'CONFIRM_PENDING', 'CONFIRM_UNKNOWN'):
            continue
        _set(conn, code, p, now, state='CONFIRM_PENDING', payment_reference=ref)
        pays = False
        try:
            pays = check_ready(p)
            body = {'payment': {'method': 'simulated', 'reference': ref, 'amount': r['held_total']}} if pays else None
            d = _call(p, 'POST', f"/holds/{r['hold_id']}/confirm", key=confirm_key(code, p), body=body)
            ok = (d.get('holdId') == r['hold_id'] and d.get('reservationState') == 'reserved' and isinstance(d.get('voucher'), dict)
                  and d['voucher'].get('code') and (not pays or (d.get('paymentState') == 'paid' and (d.get('payment') or {}).get('reference') == ref)))
            if not ok:
                raise Unknown('unverifiable confirm')
            _set(conn, code, p, now, state='CONFIRMED', voucher=json.dumps(d['voucher']), payment_state=d.get('paymentState'))
            confirmed += 1
        except Rejected as e:
            _set(conn, code, p, now, state='CONFIRM_FAILED', error_code=e.code)
            status = 'PARTIAL'
        except Unknown:
            # Read-only evidence; the order stays UNKNOWN for a person. No new key, no cancel.
            try:
                s = _call(p, 'GET', f"/holds/{r['hold_id']}")
                if s.get('reservationState') == 'reserved' and isinstance(s.get('voucher'), dict):
                    _set(conn, code, p, now, state='CONFIRMED', voucher=json.dumps(s['voucher']), payment_state=s.get('paymentState'))
                    confirmed += 1
                    if pays and s.get('paymentState') != 'paid':
                        status = 'PARTIAL'
                    continue
            except (Unknown, Rejected):
                pass
            _set(conn, code, p, now, state='CONFIRM_UNKNOWN', error_code='OUTCOME_UNKNOWN')
            status = 'UNKNOWN'
    return status, [public(_row(conn, code, rq['provider'])) for rq in requests]
