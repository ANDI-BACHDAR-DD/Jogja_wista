import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import logging

logger = logging.getLogger('integrations')

_cache = {}
CACHE_TTL = 60

class IntegrationNotConfiguredError(Exception):
    pass

class UpstreamError(Exception):
    pass

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

    headers = {
        'Accept': 'application/json',
        'User-Agent': 'WisataJogja-Integration/1.0'
    }
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
    except Exception as e:
        logger.warning(f"Upstream request failed for path {clean_path}: {type(e).__name__}")
        raise UpstreamError("Gagal menghubungi layanan hulu")

def get_hotel_config():
    url = os.getenv('HOTEL_API_URL', '').strip()
    key = os.getenv('HOTEL_API_KEY', '').strip()
    path = os.getenv('HOTEL_SEARCH_PATH', '/api/v1/hotels').strip()
    return url, key, path

def get_transport_config():
    url = os.getenv('TRANSPORT_API_URL', '').strip()
    key = os.getenv('TRANSPORT_API_KEY', '').strip()
    path = os.getenv('TRANSPORT_SEARCH_PATH', '/api/v1/routes').strip()
    return url, key, path

def get_hotels(params):
    url, key, path = get_hotel_config()
    if not url:
        raise IntegrationNotConfiguredError("Integrasi hotel belum dikonfigurasi")
    return http_get(url, path, params=params, api_key=key, timeout=5)

def get_transport(params):
    url, key, path = get_transport_config()
    if not url:
        raise IntegrationNotConfiguredError("Integrasi transportasi belum dikonfigurasi")
    return http_get(url, path, params=params, api_key=key, timeout=5)

def ping_service(base_url, timeout=3):
    if not base_url:
        return False
    try:
        clean_base = base_url.rstrip('/')
        url = f"{clean_base}/api/v1/health"
        req = urllib.request.Request(url, headers={'User-Agent': 'WisataJogja-Ping/1.0'}, method='GET')
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

