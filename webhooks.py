import os
import json
import uuid
import hmac
import hashlib
import logging
import threading
import time
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger('webhooks')
_warned_no_secret = False

def _send_to_url(url, raw_body, headers):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=raw_body, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    return
        except Exception as e:
            if attempt == 2:
                logger.warning(f"Webhook delivery failed for {url} after 3 attempts: {e}")
            else:
                time.sleep(0.05)

def _send_all(urls, raw_body, headers):
    for u in urls:
        _send_to_url(u, raw_body, headers)

def emit_event(event, payload, sync=False):
    global _warned_no_secret
    try:
        secret = os.getenv('WEBHOOK_SECRET', '').strip()
        if not secret:
            if not _warned_no_secret:
                logger.warning("WEBHOOK_SECRET kosong. Pengiriman webhook dinonaktifkan.")
                _warned_no_secret = True
            return

        urls_str = os.getenv('WEBHOOK_URLS', '').strip()
        if not urls_str:
            return

        urls = [u.strip() for u in urls_str.split(',') if u.strip()]
        if not urls:
            return

        data = dict(payload)
        # PII handling: include name, email, phone only if WEBHOOK_INCLUDE_PII=1
        if os.getenv('WEBHOOK_INCLUDE_PII', '0') != '1':
            for k in ('name', 'email', 'phone', 'customer'):
                data.pop(k, None)

        event_payload = {
            "id": f"evt_{uuid.uuid4()}",
            "type": event,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": data
        }

        raw_body = json.dumps(event_payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        signature = "sha256=" + hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Wisata-Event": event,
            "X-Wisata-Signature": signature,
            "User-Agent": "WisataJogja-Webhook/1.0"
        }

        is_sync = sync or bool(os.getenv('VERCEL')) or os.getenv('WEBHOOK_SYNC') == '1' or os.getenv('TESTING') == '1'
        if is_sync:
            _send_all(urls, raw_body, headers)
        else:
            threading.Thread(target=_send_all, args=(urls, raw_body, headers), daemon=True).start()

    except Exception as e:
        logger.error(f"Error emitting webhook event {event}: {e}")
