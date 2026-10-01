# Wisata Jogja

Modul pemesanan tiket objek wisata di DIY untuk proyek **Jogja Itinerary** (mata kuliah Interoperabilitas Lanjut).

## Stack
- **Backend**: Python 3.10+, Flask 3, SQLite (bawaan)
- **Frontend**: HTML + CSS + JavaScript murni (SPA, satu file `static/index.html`)
- **Dependensi**: Flask, flask-cors, openpyxl, Pillow, itsdangerous, requests

## Cara Instal & Menjalankan

```bash
pip install -r requirements.txt
python import_xlsx.py   # ekstrak data & gambar dari Excel (sekali saja)
python app.py
```

> **macOS**: Jika port 5000 terpakai AirPlay, gunakan `PORT=5001 python app.py`

Buka browser: `http://localhost:5000`

## Fitur

| Fitur | Keterangan |
|---|---|
| 🗺️ Jelajahi Destinasi | 62 wisata, 5 wilayah, filter & pencarian |
| 📅 Kalender Kustom | Ketersediaan, harga per tanggal (termasuk akhir pekan), kuota |
| 🎫 Pemesanan | Stepper 3 langkah, kode booking `WJ-XXXXXXXX`, status awal PENDING |
| 💳 Pembayaran Simulasi | Halaman `/bayar/{code}`: countdown 15 menit, metode QRIS/VA/e-wallet |
| 📅 Ubah Tanggal | Hanya `visit_date`; harga lama terkunci; bayar selisih bila lebih mahal |
| ↩ Refund | 100% ≥3 hari, 50% 1-2 hari, 0% hari-H (hanya status PAID) |
| 👤 Akun | Daftar, masuk, keluar, token JWT-style |
| ⚙️ Admin | CRUD wisata (token header) |
| 📧 Email | Notifikasi konfirmasi (saat bayar), update, refund |
| 🌙 Tema | Terang/gelap, disimpan di localStorage |
| ❤️ Favorit | Tersimpan di localStorage |

## Sistem Akun

### Endpoint Auth

| Metode | Path | Keterangan |
|---|---|---|
| POST | `/api/auth/register` | Daftar akun baru |
| POST | `/api/auth/login` | Masuk |
| GET | `/api/auth/me` | Data user (butuh token) |
| POST | `/api/auth/logout` | Keluar (204) |

**Contoh Register:**
```bash
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Budi Santoso","email":"budi@example.com","password":"rahasia123"}'
```

**Contoh Login:**
```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"budi@example.com","password":"rahasia123"}'
# Response: {"token":"...", "user":{...}}
```

**Menggunakan Token (semua request berikutnya):**
```bash
curl http://localhost:5000/api/auth/me \
  -H "Authorization: Bearer <token>"
```

### Aturan Akun & Otorisasi
- **POST /api/bookings** wajib login (header `Authorization: Bearer <token>`)
- `GET /api/bookings` tanpa parameter → mengembalikan pesanan milik user yang login
- Refund/ubah hanya boleh oleh pemilik booking atau admin
- Selain itu: HTTP 403 Forbidden

## Alur Pembayaran (Simulasi)

1. Pesan tiket → booking **PENDING**, `expires_at` = +15 menit.
2. Buka `#/bayar/{code}` → pilih metode bayar (QRIS/VA/e-wallet) → instruksi tampil.
3. Klik **Saya Sudah Bayar** → `POST /pay` → status **PAID**.
4. PENDING yang lewat batas waktu → **EXPIRED** otomatis (lazy).
5. **Batalkan** pada PENDING → langsung EXPIRED (tanpa refund).

**Metode pembayaran:** `qris`, `va_bca`, `va_bni`, `va_mandiri`, `gopay`, `ovo`, `dana`.

**Harga akhir pekan:** destinasi dengan `price_weekend` memakai harga itu; destinasi lainnya = harga dasar + `WEEKEND_SURCHARGE` (default Rp5.000). Harga Rp0 tidak dikenai tambahan.

**Ubah tanggal:** hanya `visit_date` yang boleh dikirim. Harga lama terkunci. Jika tanggal baru lebih mahal → bayar selisih dulu sebelum tanggal aktif. Jika lebih murah → total tetap (tanpa pengembalian).

## Ringkasan Semua Endpoint

| Metode | Path | Auth |
|---|---|---|
| GET | `/api/regions` | - |
| GET | `/api/destinations` | - |
| GET | `/api/destinations/{id}` | - |
| GET | `/api/destinations/{id}/calendar` | - |
| POST | `/api/destinations` | Admin |
| PUT | `/api/destinations/{id}` | Admin |
| DELETE | `/api/destinations/{id}` | Admin |
| POST | `/api/bookings` | Login (status awal PENDING + `expires_at`) |
| GET | `/api/bookings` | Login / email+kode |
| GET | `/api/bookings/{code}` | - |
| PUT | `/api/bookings/{code}` | Pemilik/Admin (hanya `{visit_date}`) |
| POST | `/api/bookings/{code}/pay` | Pemilik (bayar simulasi `{payment_method}`) |
| POST | `/api/bookings/{code}/cancel` | Pemilik/Admin (batalkan PENDING) |
| POST | `/api/bookings/{code}/refund` | Pemilik/Admin (hanya PAID) |
| DELETE | `/api/bookings/{code}` | Admin |

## Environment Variables

| Variable | Default | Keterangan |
|---|---|---|
| `PORT` | `5000` | Port server |
| `DB_PATH` | `wisata.db` | Path database SQLite |
| `ADMIN_TOKEN` | `admin123` | Token admin legacy (X-Admin-Token) |
| `SECRET_KEY` | *(acak tiap start)* | Kunci signing token auth (**wajib di-set di produksi**) |
| `ADMIN_EMAIL` | `admin@wisatajogja.id` | Email admin default |
| `ADMIN_PASSWORD` | `Admin12345` | Password admin default (**ganti di produksi!**) |
| `PAYMENT_WINDOW_MIN` | `15` | Menit kedaluwarsa pembayaran simulasi |
| `WEEKEND_SURCHARGE` | `5000` | Tambahan harga akhir pekan (Sabtu/Minggu) untuk destinasi tanpa `price_weekend` |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | *(kosong)* | Akun email pengirim |
| `SMTP_PASS` | *(kosong)* | App Password |
| `MAIL_FROM_NAME` | `Wisata Jogja` | Nama pengirim email |

### Cara Set via File .env (Direkomendasikan)
Buat file `.env` di root folder (sudah ada di `.gitignore`):
```bash
SECRET_KEY=isi_dengan_string_acak_panjang
ADMIN_EMAIL=admin@domainanda.id
ADMIN_PASSWORD=PasswordKuat123!
SMTP_USER=email.anda@gmail.com
SMTP_PASS=xxxx_xxxx_xxxx_xxxx
```
Lalu muat saat menjalankan:
```bash
set -a; source .env; set +a; python app.py
```

## Notifikasi Email

### Mode Dev (Tanpa SMTP)
Jika `SMTP_USER` tidak di-set, email tidak terkirim — isinya dicetak ke console.

### Mengaktifkan Gmail
1. Aktifkan **2-Step Verification** di akun Google Anda
2. Buka: [Google Account > Security > App passwords](https://myaccount.google.com/apppasswords)
3. Buat App Password untuk "Mail" → salin 16 karakter
4. Simpan ke `.env` sebagai `SMTP_PASS`

**JANGAN** simpan password langsung di kode. File `.env` sudah ada di `.gitignore`.

## Upgrade dari Database Lama

Jika Anda memiliki `wisata.db` lama (sebelum fitur akun & pembayaran), tidak perlu dihapus.
Script `init()` di `app.py` otomatis menambahkan kolom baru via `ALTER TABLE` yang dibungkus pengecekan `PRAGMA table_info`:
- `user_id` ke tabel `bookings` (fitur akun)
- `expires_at`, `paid_at`, `payment_method`, `pending_visit_date`, `pending_unit_price`, `due_amount` ke tabel `bookings` (fitur pembayaran simulasi & ubah tanggal)

Data lama tetap aman.

## Status Booking

| Status | Arti |
|---|---|
| `PENDING` | Baru dibuat, menunggu pembayaran (batas waktu 15 menit) |
| `PAID` | Lunas (via simulasi pembayaran) |
| `REFUNDED` | Dikembalikan dana |
| `EXPIRED` | PENDING kedaluwarsa atau dibatalkan |

## Menjalankan Tes

```bash
source venv/bin/activate
python test_api.py
```

Output yang diharapkan: `Ran 43 tests in X.Xs | OK`

## Struktur Folder

```
Jogja_wisata/
├── app.py              # Backend Flask
├── mailer.py           # Notifikasi email
├── import_xlsx.py      # ETL dari Excel → JSON + foto
├── test_api.py         # Tes integrasi (43 tes)
├── requirements.txt
├── vercel.json         # Konfigurasi deploy Vercel
├── README.md
├── .gitignore          # Menyertakan .env
├── data/
│   └── destinations.json
├── public/
│   └── index.html      # Frontend SPA (dilayani dari public/)
├── static/
│   ├── index.html      # Backup frontend
│   └── img/            # 124 foto wisata
└── wisata.db           # SQLite database
```
