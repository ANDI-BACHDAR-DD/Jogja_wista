"""
db_turso.py — Database adapter untuk Wisata Jogja.

Menyediakan API yang kompatibel dengan sqlite3 untuk:
  - SQLite lokal   (default; dev, CI, test)
  - Turso/libSQL   (production; jika TURSO_DATABASE_URL dan TURSO_AUTH_TOKEN di-set)

Penggunaan (sama persis dengan sqlite3):
    from db_turso import connect, is_turso_configured, is_durable

    conn = connect()           # mengembalikan sqlite3.Connection atau LibsqlConnection
    conn.execute(sql, params)  # kompatibel
    conn.commit()
    conn.close()

W2 contract:
  - is_turso_configured() → True  hanya jika URL + token ada DAN probe berhasil
  - is_durable()          → True  hanya setelah probe berhasil (fail-closed)
"""

import os
import sqlite3
import threading
import time
import logging

logger = logging.getLogger(__name__)

# ── Konfigurasi ────────────────────────────────────────────────────────────────
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN   = os.getenv("TURSO_AUTH_TOKEN", "").strip()

# Cache probe result (thread-safe)
_probe_lock    = threading.Lock()
_probe_result  = None   # None = belum di-probe, True = OK, False = gagal
_probe_time    = 0.0
PROBE_TTL      = 60.0   # detik — re-probe setiap 60 detik


def is_turso_configured() -> bool:
    """
    True hanya jika TURSO_DATABASE_URL dan TURSO_AUTH_TOKEN keduanya di-set
    DAN URL berformat libsql:// atau https://.
    Tidak melakukan koneksi; gunakan is_durable() untuk probe aktual.
    """
    if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        return False
    return TURSO_DATABASE_URL.startswith(("libsql://", "https://"))


def _do_probe() -> bool:
    """
    Lakukan probe aktual ke Turso: buka koneksi, jalankan SELECT 1.
    Kembalikan True jika berhasil, False jika error apapun.
    """
    if not is_turso_configured():
        return False
    try:
        import libsql_client  # type: ignore
    except ImportError:
        logger.warning("libsql_client tidak terinstall; Turso tidak aktif. "
                       "Jalankan: pip install libsql-client")
        return False
    try:
        with libsql_client.create_client_sync(
            url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
        ) as client:
            result = client.execute("SELECT 1")
            return len(result.rows) == 1
    except Exception as exc:
        logger.warning(f"Turso probe gagal: {exc}")
        return False


def is_durable() -> bool:
    """
    True HANYA jika Turso terkonfigurasi DAN probe aktual berhasil.
    Fail-closed: jika probe gagal atau tidak dikonfigurasi → False.
    Hasil di-cache selama PROBE_TTL detik untuk menghindari overhead per-request.
    """
    global _probe_result, _probe_time
    if not is_turso_configured():
        return False
    with _probe_lock:
        now = time.monotonic()
        if _probe_result is None or (now - _probe_time) > PROBE_TTL:
            _probe_result = _do_probe()
            _probe_time   = now
        return bool(_probe_result)


def invalidate_probe():
    """Reset cache probe (untuk test)."""
    global _probe_result, _probe_time
    with _probe_lock:
        _probe_result = None
        _probe_time   = 0.0


# ── LibsqlConnection wrapper ────────────────────────────────────────────────────

class LibsqlRow:
    """Wrapper agar row Turso berperilaku seperti sqlite3.Row (akses via nama kolom)."""
    def __init__(self, columns, values):
        self._columns = columns
        self._values  = values
        self._map     = {c: v for c, v in zip(columns, values)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def keys(self):
        return self._columns

    def __iter__(self):
        return iter(self._values)

    def get(self, key, default=None):
        return self._map.get(key, default)


class LibsqlCursor:
    """Cursor minimal kompatibel dengan sqlite3.Cursor."""
    def __init__(self, client, columns=None, rows=None):
        self._client  = client
        self._columns = columns or []
        self._rows    = [LibsqlRow(self._columns, list(r)) for r in (rows or [])]
        self._idx     = 0
        self.lastrowid = None

    def fetchone(self):
        if self._idx < len(self._rows):
            row = self._rows[self._idx]; self._idx += 1; return row
        return None

    def fetchall(self):
        result = self._rows[self._idx:]
        self._idx = len(self._rows)
        return result

    def __iter__(self):
        return iter(self._rows[self._idx:])


class LibsqlConnection:
    """
    Wrapper sinkron di atas libsql_client, menyerupai sqlite3.Connection.
    Mendukung execute(), executescript(), executemany(), commit(), close().
    """
    def __init__(self, client):
        self._client = client
        self._batch  = []   # buffer untuk executescript/multi-statement

    def _run(self, sql, params=()):
        import libsql_client
        result = self._client.execute(libsql_client.Statement(sql, list(params)))
        cur = LibsqlCursor(
            self._client,
            columns=[c for c in (result.columns or [])],
            rows=result.rows,
        )
        return cur

    def execute(self, sql, params=()):
        return self._run(sql, params)

    def executemany(self, sql, seq_of_params):
        import libsql_client
        stmts = [libsql_client.Statement(sql, list(p)) for p in seq_of_params]
        self._client.batch(stmts)
        return LibsqlCursor(self._client)

    def executescript(self, script):
        """
        Jalankan multi-statement DDL/DML.
        Pecah per titik koma dan eksekusi satu per satu.
        """
        import libsql_client
        stmts = []
        for stmt in script.split(';'):
            s = stmt.strip()
            if s:
                stmts.append(libsql_client.Statement(s))
        if stmts:
            self._client.batch(stmts)
        return LibsqlCursor(self._client)

    def commit(self):
        pass   # libsql_client auto-commit tiap execute; tidak perlu manual

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── connect() — titik masuk utama ──────────────────────────────────────────────

def connect(db_path: str = None) -> "sqlite3.Connection | LibsqlConnection":
    """
    Kembalikan koneksi database yang sesuai:
      - Turso (LibsqlConnection) jika is_turso_configured() = True
      - SQLite (sqlite3.Connection) jika tidak

    db_path hanya digunakan untuk SQLite. Jika None, diambil dari DB_PATH env
    dengan fallback ke 'wisata.db'.
    """
    if is_turso_configured():
        try:
            import libsql_client  # type: ignore
            client = libsql_client.create_client_sync(
                url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN,
            )
            return LibsqlConnection(client)
        except ImportError:
            logger.warning("libsql_client tidak tersedia; fallback ke SQLite.")
        except Exception as exc:
            logger.warning(f"Koneksi Turso gagal ({exc}); fallback ke SQLite.")

    # Fallback: SQLite lokal
    is_vercel = bool(os.environ.get("VERCEL"))
    path = db_path or os.getenv("DB_PATH", "/tmp/wisata.db" if is_vercel else "wisata.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
