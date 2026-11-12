# Panduan Integrasi Antar-Layanan (Interoperabilitas Wisata Jogja)

Dokumen ini ditujukan bagi developer tim **Hotel Service**, **Transport**, dan **Jogja Itinerary** untuk berinteraksi langsung dengan layanan **Wisata Jogja** melalui REST API v1.

---

## 1. Arsitektur Layanan

Ekosistem Jogja Itinerary terdiri dari 3 backend/layanan utama dan 1 frontend/klien gabungan:

```
                  ┌──────────────────────────────┐
                  │       Jogja Itinerary        │
                  │ (Klien Komposit / Agregator) │
                  └───────┬──────────────┬───────┘
                          │              │
          ┌───────────────┘              └────────────────┐
          ▼                                               ▼
┌──────────────────┐                            ┌───────────────────┐
│  Hotel Service   │◄────── S2S Integrations ──►│   Wisata Jogja    │
│  (Node/Express)  │◄──────── Webhooks ─────────┤  (Flask 3 + REST) │
└─────────┬────────┘                            └─────────┬─────────┘
          │                                               │
          │             ┌───────────────────┐             │
          └────────────►│ Transport Service │◄────────────┘
                        │ (React + TanStack)│
                        └───────────────────┘
```

- **Wisata Jogja** (Layanan ini): Mengelola katalog destinasi wisata DIY, kuota kunjungan, harga dinamis (weekday/weekend/plus tier), reservasi tiket, dan webhook event.
- **Hotel Service**: Layanan akomodasi (Node.js 22 + Express 4 + SQLite, REST `/api/v1`, auth Bearer).
- **Transport Service**: Layanan rute dan armada transportasi.
- **Itinerary Client**: Pengguna/klien komposit yang dapat merangkai paket dari ketiga layanan.

Wisata Jogja dapat berkomunikasi dua arah:
1. **Inbound (Service-to-Service)**: Hotel, Transport, atau Itinerary memanggil API `/api/v1/partner/*` menggunakan kunci partner rahasia.
2. **Outbound (Webhooks)**: Wisata Jogja mengirim notifikasi HTTP POST ke URL eksternal saat tiket dibuat, diubah tanggalnya, atau di-refund.
3. **Outbound (Klien Integrasi)**: Wisata Jogja dapat mencari hotel atau transportasi melalui endpoint proxy terkelola.

---

## 2. Autentikasi Partner (Service-to-Service)

Layanan partner tidak memerlukan akun pengguna (user registration/login). Autentikasi dilakukan via header HTTP:

```http
Authorization: Bearer <PARTNER_KEY>
```

- Kunci partner dikonfigurasi melalui environment variable `PARTNER_KEYS` di server Wisata Jogja.
- Format: `hotel:KUNCI_HOTEL,transport:KUNCI_TRANSPORT,itinerary:KUNCI_ITINERARY`.
- Panjang kunci minimal **24 karakter**. Kunci yang lebih pendek akan ditolak saat aplikasi dimulai.
- Jika header `Authorization` kosong atau kunci salah, server mengembalikan HTTP `401 Unauthorized`.
- Setiap partner hanya dapat mengakses dan mengelola pesanan miliknya sendiri (isolasi tenant multi-partner).

---

## 3. Format Error Standar

Semua error dikembalikan dalam format JSON seragam:

```json
{
  "error": "Pesan deskriptif dalam bahasa Indonesia",
  "code": "KODE_ERROR"
}
```

| HTTP Status | Nilai `code` | Deskripsi |
|-------------|--------------|-----------|
| `400` | `VALIDATION_ERROR` | Parameter request tidak valid, tanggal lampau, format salah |
| `401` | `UNAUTHORIZED` | Bearer token partner/user hilang atau tidak valid |
| `403` | `FORBIDDEN` | Akses ditolak (memerlukan hak akses admin atau kepemilikan) |
| `404` | `NOT_FOUND` | Destinasi atau booking tidak ditemukan / bukan milik partner |
| `405` | `VALIDATION_ERROR` | Metode HTTP tidak diizinkan |
| `409` | `CONFLICT` | Kuota habis, duplicate `external_ref`, status tidak sesuai |
| `410` | `GONE` | Batas waktu pembayaran pesanan telah habis |
| `422` | `UNPROCESSABLE` | Aksi tidak dapat diproses (misal refund pada hari-H) |
| `429` | `RATE_LIMITED` | Batas permintaan terlampaui (120 req/menit per partner) |
| `500` | `INTERNAL_ERROR` | Kesalahan internal server tanpa membocorkan stack trace |
| `502` | `UPSTREAM_ERROR` | Gagal memanggil layanan eksternal (Hotel/Transport) |
| `503` | `INTEGRATION_NOT_CONFIGURED` | URL atau kredensial integrasi hulu belum di-set |

Setiap respons juga menyertakan header pelacakan:
`X-Request-Id: <uuid4>`

---

## 4. Endpoint Partner

Base URL:
- Lokal: `http://localhost:5000/api/v1`
- Produksi: `https://wisata-jogja.vercel.app/api/v1` (atau domain kustom)
- Dokumentasi interaktif Swagger UI: `/api/docs`
- Spesifikasi OpenAPI JSON: `/api/v1/openapi.json`

### 4.1 Cek Ketersediaan & Tarif Tiket (Publik)
Digunakan sebelum memesan untuk memastikan kuota masih tersedia dan mengetahui kalkulasi harga (termasuk penyesuaian akhir pekan).

```bash
curl -X GET "http://localhost:5000/api/v1/destinations/1/availability?date=2026-11-20&qty=2&tier=base"
```

**Respons (200 OK):**
```json
{
  "destination_id": 1,
  "date": "2026-11-20",
  "qty": 2,
  "available": true,
  "remaining": 490,
  "unit_price": 15000,
  "total": 30000,
  "currency": "IDR",
  "is_weekend": false
}
```

---

### 4.2 Pembuatan Pesanan Partner (Service-to-Service)
Membuat tiket langsung dari sistem partner.
- `external_ref`: Referensi unik di sistem partner (misalnya ID booking hotel atau transaksi itinerary).
- `Idempotency-Key` (Header, opsional tapi sangat disarankan): Menjamin idempotensi transaksi.
- Status pesanan partner **langsung menjadi `PAID`** (pembayaran ditangani oleh sistem partner).
- Sistem Wisata Jogja langsung mengirim email konfirmasi tiket ke `customer.email`.

```bash
curl -X POST "http://localhost:5000/api/v1/partner/bookings" \
  -H "Authorization: Bearer <PARTNER_KEY>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: e1a2b3c4-d5e6-7f8a-9b0c-1234567890ab" \
  -d '{
    "destination_id": 1,
    "visit_date": "2026-11-20",
    "qty": 2,
    "tier": "base",
    "external_ref": "HOTEL-RES-2026-9901",
    "customer": {
      "name": "Budi Santoso",
      "email": "budi.santoso@example.com",
      "phone": "08123456789"
    }
  }'
```

**Respons Berhasil Baru (201 Created):**
```json
{
  "code": "WJ-7K9A2P1B",
  "destination_id": 1,
  "destination_name": "Keraton Yogyakarta",
  "visit_date": "2026-11-20",
  "qty": 2,
  "unit_price": 15000,
  "total": 30000,
  "status": "PAID",
  "source": "hotel",
  "external_ref": "HOTEL-RES-2026-9901",
  "refund_amount": 0,
  "created_at": "2026-11-12T10:00:00",
  "destination": {
    "name": "Keraton Yogyakarta",
    "region": "kota-yogyakarta"
  },
  "tier": "base"
}
```

**Panduan Idempotency-Key & Duplicate External Ref:**
1. Jika request dikirim ulang dengan **`Idempotency-Key` yang sama** oleh partner yang sama, server mengembalikan status **200 OK** beserta data pesanan yang sudah dibuat sebelumnya (tidak membuat pesanan ganda dan tidak memotong kuota dua kali).
2. Jika request dikirim dengan **`external_ref` yang sudah terdaftar** untuk partner tersebut tetapi menggunakan `Idempotency-Key` berbeda atau tanpa idempotency key, server mengembalikan **409 CONFLICT** (`{"error": "external_ref sudah digunakan...", "code": "CONFLICT"}`).

---

### 4.3 Cek Detail Pesanan Milik Partner
Mengambil detail pesanan berdasarkan kode booking Wisata Jogja. Partner hanya bisa melihat pesanan miliknya sendiri.

```bash
curl -X GET "http://localhost:5000/api/v1/partner/bookings/WJ-7K9A2P1B" \
  -H "Authorization: Bearer <PARTNER_KEY>"
```

**Respons (200 OK):**
Sama dengan struktur objek Booking di atas. Jika booking milik partner lain atau tidak ditemukan, mengembalikan **404 NOT_FOUND**.

---

### 4.4 Daftar / Cari Pesanan Milik Partner
Mendapatkan daftar pesanan dengan filter `external_ref` serta paginasi.

```bash
curl -X GET "http://localhost:5000/api/v1/partner/bookings?external_ref=HOTEL-RES-2026-9901&limit=10&offset=0" \
  -H "Authorization: Bearer <PARTNER_KEY>"
```

Header respons menyertakan total data: `X-Total-Count: 1`.

---

### 4.5 Reschedule / Ubah Tanggal Kunjungan
Mengubah tanggal kunjungan pesanan.
Aturan rescheduling:
- Tanggal lama dan tanggal baru harus `>= besok` (H+1). Pesanan pada hari-H tidak dapat diubah.
- Kuota pada tanggal baru harus mencukupi.

```bash
curl -X PUT "http://localhost:5000/api/v1/partner/bookings/WJ-7K9A2P1B" \
  -H "Authorization: Bearer <PARTNER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "visit_date": "2026-11-25"
  }'
```

**Respons (200 OK):** Objek booking dengan `visit_date` yang telah diperbarui.

---

### 4.6 Pengajuan Refund Pesanan Partner
Mengajukan pembatalan dan pengembalian dana tiket wisata.
Kebijakan persentase refund:
- `>= 3 hari` sebelum tanggal kunjungan: **100%** pengembalian dana.
- `1 - 2 hari` sebelum tanggal kunjungan: **50%** pengembalian dana.
- `Hari-H atau setelahnya`: Tidak dapat di-refund (**422 UNPROCESSABLE**).

```bash
curl -X POST "http://localhost:5000/api/v1/partner/bookings/WJ-7K9A2P1B/refund" \
  -H "Authorization: Bearer <PARTNER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Tamu membatalkan reservasi hotel"
  }'
```

**Respons (200 OK):**
```json
{
  "code": "WJ-7K9A2P1B",
  "status": "REFUNDED",
  "refund_amount": 30000,
  "total": 30000,
  "visit_date": "2026-11-25",
  "source": "hotel"
}
```

---

## 5. Webhook Keluar (Notifikasi ke Layanan Lain)

Wisata Jogja mengirim notifikasi HTTP POST ke semua URL yang tercantum pada env `WEBHOOK_URLS` (dipisahkan koma) saat status pesanan berubah.

### 5.1 Daftar Event
1. `booking.created`: Tiket berhasil diterbitkan (baik dari web maupun partner).
2. `booking.rescheduled`: Tanggal kunjungan berhasil diubah.
3. `booking.refunded`: Pesanan berhasil di-refund.

### 5.2 Struktur Payload & Header
Header yang dikirimkan:
- `Content-Type: application/json`
- `X-Wisata-Event: <tipe_event>`
- `X-Wisata-Signature: sha256=<hex_hmac_hash>`

Format body JSON:
```json
{
  "id": "evt_9c13b7d1-e631-419b-a37a-cb8bcae9e03d",
  "type": "booking.created",
  "created_at": "2026-11-12T10:00:00.123456+00:00",
  "data": {
    "code": "WJ-7K9A2P1B",
    "destination_id": 1,
    "destination_name": "Keraton Yogyakarta",
    "visit_date": "2026-11-20",
    "qty": 2,
    "unit_price": 15000,
    "total": 30000,
    "status": "PAID",
    "source": "hotel",
    "external_ref": "HOTEL-RES-2026-9901",
    "refund_amount": 0
  }
}
```
*Catatan Privasi Data (PII)*: Secara default, `name`, `email`, dan `phone` **tidak dikirimkan** dalam payload webhook. Data pemesan hanya disertakan jika env `WEBHOOK_INCLUDE_PII=1` diaktifkan di server.

### 5.3 Verifikasi Tanda Tangan (Signature)

Penerima wajib memverifikasi header `X-Wisata-Signature` untuk memastikan keaslian data dan integritas payload.

#### Contoh Verifikasi di Node.js (Express)
```javascript
const crypto = require('crypto');

function verifyWisataWebhook(req, secret) {
  const signatureHeader = req.headers['x-wisata-signature'];
  if (!signatureHeader || !signatureHeader.startsWith('sha256=')) {
    return false;
  }
  const receivedSig = signatureHeader.slice(7);
  
  // Pastikan menggunakan buffer mentah (raw body) sebelum di-parse JSON
  const expectedSig = crypto
    .createHmac('sha256', secret)
    .update(req.rawBody)
    .digest('hex');

  return crypto.timingSafeEqual(
    Buffer.from(receivedSig, 'hex'),
    Buffer.from(expectedSig, 'hex')
  );
}
```

#### Contoh Verifikasi di Python (Flask / FastAPI)
```python
import hmac
import hashlib

def verify_wisata_webhook(raw_body_bytes: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_sig = signature_header.split("sha256=", 1)[1]
    expected_sig = hmac.new(secret.encode('utf-8'), raw_body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)
```

### 5.4 Penanganan Retry & Idempotensi di Sisi Penerima
- Wisata Jogja menerapkan hingga **2 kali retry cepat** jika endpoint penerima mengalami timeout (> 5 detik) atau error HTTP.
- Penerima webhook harus menyimpan `id` event (`evt_*`) atau kombinasi `(code, type)` untuk mencegah pemrosesan duplikat.
- Kembalikan respon HTTP `2xx` sesegera mungkin (jangan menjalankan proses blocking yang lama sebelum merespons webhook).

---

## 6. Integrasi Hulu ke Hotel & Transport

Wisata Jogja juga menyediakan endpoint adaptor transparan untuk memanggil layanan Hotel dan Transport:

- `GET /api/v1/integrations/hotels?region=<slug>&check_in=&check_out=`
- `GET /api/v1/integrations/transport?origin=&destination=&date=`
- `GET /api/v1/integrations/status` (Cek kesehatan & kesiapan integrasi)

Format respon:
```json
{
  "source": "hotel",
  "data": { ... }
}
```
Hasil pemanggilan di-cache dalam memori selama **60 detik** untuk mengurangi beban upstream.

---

## 7. Daftar Environment Variables

Berikut konfigurasi environment yang tersedia:

| Variabel | Tipe | Default | Deskripsi |
|----------|------|---------|-----------|
| `PARTNER_KEYS` | String | *(kosong)* | Daftar key partner (format: `partner1:kunci1,partner2:kunci2`). Minimal 24 karakter per key. |
| `CORS_ORIGINS` | String | `*` (hanya GET) | Daftar origin yang diizinkan untuk CORS (dipisah koma). |
| `WEBHOOK_URLS` | String | *(kosong)* | Daftar URL penerima webhook (dipisah koma). |
| `WEBHOOK_SECRET` | String | *(kosong)* | Kunci rahasia HMAC-SHA256 untuk webhook payload. |
| `WEBHOOK_INCLUDE_PII` | String | `0` | Set ke `1` jika webhook diizinkan membawa name, email, dan phone. |
| `PUBLIC_BASE_URL` | String | *(kosong)* | Base URL publik layanan untuk dicantumkan di server OpenAPI spec. |
| `HOTEL_API_URL` | String | *(kosong)* | Base URL layanan Hotel. |
| `HOTEL_API_KEY` | String | *(kosong)* | API Key untuk autentikasi ke Hotel Service. |
| `HOTEL_SEARCH_PATH` | String | `/api/v1/hotels` | Path pencarian di Hotel Service. |
| `TRANSPORT_API_URL` | String | *(kosong)* | Base URL layanan Transport. |
| `TRANSPORT_API_KEY` | String | *(kosong)* | API Key untuk autentikasi ke Transport Service. |
| `TRANSPORT_SEARCH_PATH`| String | `/api/v1/routes` | Path pencarian di Transport Service. |
| `SECRET_KEY` | String | *(auto)* | Secret key Flask untuk session dan JWT tokens. |
| `ADMIN_TOKEN` | String | `admin123` | Token statis untuk header `X-Admin-Token`. |
| `ADMIN_EMAIL` | String | `admin@wisatajogja.id` | Email default admin. |
| `ADMIN_PASSWORD` | String | `admin123` | Password akun default admin. |
| `SMTP_*` | String | *(mock mode)* | Kredensial email SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`). |
| `WEEKEND_SURCHARGE` | Integer | `5000` | Tambahan harga tiket untuk akhir pekan jika destinasi tidak menetapkan `price_weekend`. |

---

## 8. Catatan Deployment Serverless (Vercel)

1. **Penyimpanan SQLite Sementara (`/tmp/wisata.db`)**:
   - Di Vercel serverless environment, filesystem bersifat *read-only* kecuali folder `/tmp`.
   - Database otomatis diinisialisasi ke `/tmp/wisata.db` saat env `VERCEL=1`.
   - **PENTING**: Data di `/tmp` akan di-reset saat cold start atau instance recycling oleh Vercel. Untuk produksi persisten penuh, disarankan menghubungkan SQLite ke storage terdistribusi (seperti Turso LibSQL) atau bermigrasi ke database PostgreSQL eksternal (Supabase, Neon, RDS).
2. **Pengiriman Webhook Sinkron**:
   - Di environment Vercel, fungsi background thread daemon dimatikan segera setelah response HTTP selesai. Oleh karena itu, pengiriman webhook di Vercel secara otomatis berjalan sinkron (`urllib.request` dengan timeout singkat 5s dan 2x retry) agar notifikasi terkirim sebelum container membeku.
