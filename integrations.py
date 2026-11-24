import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import logging

logger = logging.getLogger('integrations')

_cache = {}
CACHE_TTL = 60

DEFAULT_HOTEL_API_URL = 'https://jogjastay-hotel-service.jogjawisata.workers.dev'
DEFAULT_TRANSPORT_API_URL = 'https://jogjatrans-service.jogjawisata.workers.dev'
DEFAULT_TRANSPORT_PATH = '/api/v1/rentals/vehicles'

WISATA_TO_HOTEL_REGION = {
    'kota-yogyakarta': 'kota-yogyakarta',
    'kabupaten-sleman': 'kabupaten-sleman',
    'sleman': 'kabupaten-sleman',
    'kabupaten-bantul': 'kabupaten-bantul',
    'bantul': 'kabupaten-bantul',
    'kabupaten-gunungkidul': 'kabupaten-gunungkidul',
    'gunungkidul': 'kabupaten-gunungkidul',
    'kabupaten-kulon-progo': 'kabupaten-kulon-progo',
    'kulon-progo': 'kabupaten-kulon-progo',
}

HOTEL_REGION_LABELS = {
    'kota-yogyakarta': 'Kota Yogyakarta',
    'kabupaten-sleman': 'Kabupaten Sleman',
    'kabupaten-bantul': 'Kabupaten Bantul',
    'kabupaten-gunungkidul': 'Kabupaten Gunungkidul',
    'kabupaten-kulon-progo': 'Kabupaten Kulon Progo',
}

CITY_TO_REGION = {
    "kota yogyakarta": ("kota-yogyakarta", "Kota Yogyakarta"),
    "yogyakarta": ("kota-yogyakarta", "Kota Yogyakarta"),
    "sleman": ("kabupaten-sleman", "Kabupaten Sleman"),
    "kabupaten sleman": ("kabupaten-sleman", "Kabupaten Sleman"),
    "kabupaten-sleman": ("kabupaten-sleman", "Kabupaten Sleman"),
    "bantul": ("kabupaten-bantul", "Kabupaten Bantul"),
    "kabupaten bantul": ("kabupaten-bantul", "Kabupaten Bantul"),
    "kabupaten-bantul": ("kabupaten-bantul", "Kabupaten Bantul"),
    "gunungkidul": ("kabupaten-gunungkidul", "Kabupaten Gunungkidul"),
    "gunung kidul": ("kabupaten-gunungkidul", "Kabupaten Gunungkidul"),
    "kabupaten gunungkidul": ("kabupaten-gunungkidul", "Kabupaten Gunungkidul"),
    "kabupaten-gunungkidul": ("kabupaten-gunungkidul", "Kabupaten Gunungkidul"),
    "kulon progo": ("kabupaten-kulon-progo", "Kabupaten Kulon Progo"),
    "kulonprogo": ("kabupaten-kulon-progo", "Kabupaten Kulon Progo"),
    "kabupaten kulon progo": ("kabupaten-kulon-progo", "Kabupaten Kulon Progo"),
    "kabupaten-kulon-progo": ("kabupaten-kulon-progo", "Kabupaten Kulon Progo"),
    "kota-yogyakarta": ("kota-yogyakarta", "Kota Yogyakarta")
}

class IntegrationNotConfiguredError(Exception):
    pass

class UpstreamError(Exception):
    pass

class UpstreamNotFoundError(Exception):
    pass

class InvalidParamsError(Exception):
    pass

DEFAULT_HEADERS = {
    "User-Agent": "WisataJogja/1.0 (interoperabilitas; layanan Wisata)",
    "Accept": "application/json"
}

def _clean_cache():
    now = time.time()
    expired = [k for k, (ts, _) in _cache.items() if now - ts > CACHE_TTL]
    for k in expired:
        _cache.pop(k, None)

def http_get(base_url, path, params=None, api_key=None, timeout=5, use_cache=True):
    if not base_url:
        raise IntegrationNotConfiguredError("Layanan belum dikonfigurasi")
    
    clean_base = base_url.rstrip('/')
    clean_path = '/' + path.lstrip('/')
    query_str = ''
    if params:
        filtered = sorted([(k, v) for k, v in params.items() if v is not None and v != ''])
        if filtered:
            query_str = '?' + urllib.parse.urlencode(filtered)
            
    full_url = f"{clean_base}{clean_path}{query_str}"
    cache_key = full_url

    if use_cache:
        _clean_cache()
        if cache_key in _cache:
            ts, cached_data = _cache[cache_key]
            if time.time() - ts < CACHE_TTL:
                return cached_data

    headers = dict(DEFAULT_HEADERS)
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    req = urllib.request.Request(full_url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode('utf-8')
            data = json.loads(raw_body)
            if use_cache:
                _cache[cache_key] = (time.time(), data)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpstreamNotFoundError("Data tidak ditemukan")
        body_snippet = ""
        try:
            body_bytes = e.read()
            if body_bytes:
                body_snippet = body_bytes.decode('utf-8', errors='replace')[:200]
        except Exception:
            body_snippet = ""
        logger.error(f"Upstream HTTP error {e.code} for path {clean_path}: {body_snippet}")
        raise UpstreamError("Gagal menghubungi layanan hulu")
    except Exception as e:
        logger.error(f"Upstream request failed for path {clean_path}: {type(e).__name__}")
        raise UpstreamError("Gagal menghubungi layanan hulu")

def get_hotel_config():
    if 'HOTEL_API_URL' in os.environ:
        url = os.environ.get('HOTEL_API_URL', '').strip()
    else:
        # Default fallback
        is_testing = os.getenv('TESTING') == '1'
        try:
            from flask import current_app
            if current_app and current_app.config.get('TESTING'):
                is_testing = True
        except Exception:
            pass
        if is_testing:
            url = ''
        else:
            url = DEFAULT_HOTEL_API_URL

    key = os.getenv('HOTEL_API_KEY', '').strip()
    path = os.getenv('HOTEL_SEARCH_PATH', '/api/v1/hotels').strip()
    return url, key, path

def get_hotel_timeout():
    try:
        return float(os.getenv('HOTEL_TIMEOUT', 5))
    except Exception:
        return 5

def _is_testing():
    if os.getenv('TESTING') == '1':
        return True
    try:
        from flask import current_app
        return bool(current_app and current_app.config.get('TESTING'))
    except Exception:
        return False

def get_transport_config():
    if 'TRANSPORT_API_URL' in os.environ:
        url = os.environ.get('TRANSPORT_API_URL', '').strip()
    else:
        url = '' if _is_testing() else DEFAULT_TRANSPORT_API_URL
    key = os.getenv('TRANSPORT_API_KEY', '').strip()
    path = os.getenv('TRANSPORT_SEARCH_PATH', DEFAULT_TRANSPORT_PATH).strip()
    return url, key, path

def get_hotels(params):
    url, key, path = get_hotel_config()
    timeout = get_hotel_timeout()
    if not url:
        raise IntegrationNotConfiguredError("Integrasi hotel belum dikonfigurasi")
    return http_get(url, path, params=params, api_key=key, timeout=timeout)

def get_hotel_detail(hotel_id):
    url, key, path = get_hotel_config()
    timeout = get_hotel_timeout()
    if not url:
        raise IntegrationNotConfiguredError("Integrasi hotel belum dikonfigurasi")
    detail_path = f"{path.rstrip('/')}/{hotel_id}"
    raw = http_get(url, detail_path, api_key=key, timeout=timeout)
    if isinstance(raw, dict) and raw.get('error') and raw.get('code') in ('HOTEL_NOT_FOUND', 'NOT_FOUND'):
        raise UpstreamNotFoundError("Hotel tidak ditemukan")
    return raw

def normalize_hotel(raw, base_url=None):
    if not isinstance(raw, dict):
        return None
    if not base_url:
        url, _, _ = get_hotel_config()
        base_url = url or DEFAULT_HOTEL_API_URL
        
    h_id = raw.get("hotelId") or raw.get("id")
    name = raw.get("name")
    
    raw_city = raw.get("city") or raw.get("region") or ""
    city_str = str(raw_city).strip()
    
    norm_reg, norm_lbl = CITY_TO_REGION.get(
        city_str.lower(),
        (raw.get("region") or (city_str if city_str else None), raw.get("region_label") or (city_str if city_str else None))
    )
    
    img = raw.get("imageUrl") or raw.get("image") or raw.get("photo")
    if img and isinstance(img, str):
        img = img.strip()
        if img.startswith("http://") or img.startswith("https://"):
            image_url = img
        elif img.startswith("/"):
            clean_base = base_url.rstrip("/")
            image_url = f"{clean_base}/{img.lstrip('/')}"
        else:
            image_url = None
    else:
        image_url = None
        
    price_val = raw.get("price_from")
    if price_val is None:
        price_val = raw.get("price") or raw.get("pricePerNight") or raw.get("min_price")
    if price_val is None and "rooms" in raw and isinstance(raw["rooms"], list):
        room_prices = [r.get("pricePerNight") for r in raw["rooms"] if isinstance(r, dict) and r.get("pricePerNight") is not None]
        if room_prices:
            price_val = min(room_prices)
            
    price_from = None
    if price_val is not None:
        try:
            if isinstance(price_val, str):
                cleaned = price_val.replace("Rp", "").replace(".", "").replace(",", "").strip()
                price_from = int(float(cleaned))
            else:
                price_from = int(price_val)
        except Exception:
            price_from = None
            
    currency = raw.get("currency") or ("IDR" if price_from is not None else None)
    address = raw.get("address")
    
    rating = raw.get("rating")
    if rating is not None:
        try:
            rating = float(rating)
            if rating.is_integer():
                rating = int(rating)
        except Exception:
            rating = None
            
    return {
        "id": h_id,
        "name": name,
        "region": norm_reg,
        "region_label": norm_lbl,
        "image": image_url,
        "price_from": price_from,
        "currency": currency,
        "address": address,
        "rating": rating
    }

def _real_date(value):
    import datetime as _dt
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None

def rental_params(params):
    """Validasi dan whitelist parameter katalog rental JogjaTrans.
    Hanya parameter yang dikenal yang diteruskan; parameter lain dibuang."""
    start = _real_date(params.get('startDate'))
    end = _real_date(params.get('endDate'))
    if not start or not end:
        raise InvalidParamsError('startDate dan endDate wajib berupa tanggal kalender nyata (YYYY-MM-DD)')
    if end < start:
        raise InvalidParamsError('endDate tidak boleh sebelum startDate')
    if (end - start).days + 1 > 30:
        raise InvalidParamsError('Periode sewa maksimal 30 hari')
    out = {'startDate': start.isoformat(), 'endDate': end.isoformat()}
    if params.get('type') is not None:
        if params['type'] not in ('all', 'mobil', 'motor'):
            raise InvalidParamsError('type harus all, mobil, atau motor')
        out['type'] = params['type']
    if params.get('withDriver') is not None:
        if params['withDriver'] not in ('true', 'false'):
            raise InvalidParamsError('withDriver harus true atau false')
        out['withDriver'] = params['withDriver']
    if params.get('category') is not None:
        if not re.fullmatch(r'[a-z0-9_-]{1,30}', params['category']):
            raise InvalidParamsError('category tidak valid')
        out['category'] = params['category']
    return out

def get_transport(params):
    url, key, path = get_transport_config()
    if not url:
        raise IntegrationNotConfiguredError("Integrasi transportasi belum dikonfigurasi")
    # Jalur bawaan = katalog rental JogjaTrans (kontrak tervalidasi).
    # Bila TRANSPORT_SEARCH_PATH diganti eksplisit, parameter diteruskan apa adanya (perilaku lama).
    if 'TRANSPORT_SEARCH_PATH' not in os.environ:
        params = rental_params(params)
    return http_get(url, path, params=params, api_key=key, timeout=5)

def ping_service(base_url, timeout=3):
    if not base_url:
        return False
    try:
        clean_base = base_url.rstrip('/')
        url = f"{clean_base}/api/v1/health"
        req = urllib.request.Request(url, headers=dict(DEFAULT_HEADERS), method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

def get_status():
    h_url, _, _ = get_hotel_config()
    t_url, _, _ = get_transport_config()
    return {
        "hotel": {
            "configured": bool(h_url),
            "reachable": ping_service(h_url) if h_url else False
        },
        "transport": {
            "configured": bool(t_url),
            "reachable": ping_service(t_url) if t_url else False
        }
    }
