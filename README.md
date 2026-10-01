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
| 📅 Kalender Kustom | Ketersediaan, harga per tanggal, kuota |
| 🎫 Pemesanan | Stepper 3 langkah, konfirmasi e-ticket |
| ↩ Refund | 100% ≥3 hari, 50% 1-2 hari, 0% hari-H |
| 👤 Akun | Daftar, masuk, keluar, token JWT-style |
| ⚙️ Admin | CRUD wisata (token header) |
| 📧 Email | Notifikasi konfirmasi, update, refund |
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
| POST | `/api/bookings` | Login |
| GET | `/api/bookings` | Login / email+kode |
| GET | `/api/bookings/{code}` | - |
| PUT | `/api/bookings/{code}` | Pemilik/Admin |
| POST | `/api/bookings/{code}/refund` | Pemilik/Admin |
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

Jika Anda memiliki `wisata.db` lama (sebelum fitur akun), tidak perlu dihapus.
Script `init()` di `app.py` otomatis menambahkan kolom `user_id` ke tabel `bookings` via `ALTER TABLE` yang dibungkus pengecekan `PRAGMA table_info`. Data lama tetap aman.

## Menjalankan Tes

```bash
source venv/bin/activate
python test_api.py
```

Output yang diharapkan: `Ran 17 tests in X.Xs | OK`

## Struktur Folder

```
Jogja_wisata/
├── app.py              # Backend Flask
├── mailer.py           # Notifikasi email
├── import_xlsx.py      # ETL dari Excel → JSON + foto
├── test_api.py         # Tes integrasi (17 tes)
├── requirements.txt
├── README.md
├── .gitignore          # Menyertakan .env
├── data/
│   └── destinations.json
├── static/
│   ├── index.html      # Frontend SPA
│   └── img/            # 124 foto wisata
└── wisata.db           # SQLite database
```
