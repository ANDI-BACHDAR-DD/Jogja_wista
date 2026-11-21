# PRD – Aplikasi Wisata Jogja (Modul Objek Wisata)
**Mata kuliah:** Interoperabilitas Lanjut · **Proyek:** Jogja Itinerary (agregator 3 aplikasi) · **Versi:** 1.0

## 1. Ringkasan
Web app pemesanan tiket objek wisata di DIY dengan **5 wilayah** (Kota Yogyakarta, Sleman, Bantul, Gunungkidul, Kulon Progo) berisi **62 objek wisata** dari `Tiket_Wisata_Jogja.xlsx` (nama, deskripsi, harga, 2 foto).

Layanan ini berdiri sendiri sebagai **layanan otonom dan interoperabel**. Selain melayani wisatawan lewat web app, Wisata Jogja dapat berkomunikasi langsung antar-layanan (Service-to-Service) dengan **Hotel Service** (Node.js 22 + Express 4 + SQLite, REST `/api/v1`, Bearer auth) dan **Transport Service** (React + TanStack), serta melayani klien agregator **Jogja Itinerary** yang mengambil data dari ketiga sistem.

---

## 2. Tujuan & Metrik
| Tujuan | Metrik keberhasilan |
|---|---|
| Wisatawan memesan tiket tanpa akun | Pemesanan selesai < 2 menit, ≤ 4 langkah |
| Data wisata dapat dikelola | CRUD wisata oleh admin tanpa ubah kode |
| Siap diintegrasikan | Semua fitur tersedia via REST JSON; 100% endpoint punya contoh respons |
| Refund jelas | Aturan refund otomatis & konsisten |

**Di luar cakupan v1:** payment gateway nyata (pembayaran disimulasikan lewat `/pay`), login pengguna, e-ticket QR, multi-bahasa.

## 3. Persona
- **Wisatawan** – mencari wisata per wilayah, memesan tiket, mengubah jadwal, refund.
- **Admin pengelola** – mengelola data wisata (tambah/ubah/hapus), memantau pesanan.
- **Sistem Jogja Itinerary** – konsumen API (menampilkan wisata & membuat pesanan dari itinerary).

## 4. Kebutuhan Fungsional
| ID | Fitur | Deskripsi | Prioritas |
|---|---|---|---|
| F1 | Jelajah per wilayah | Tab 5 wilayah + "Semua", jumlah wisata per wilayah, tagline wilayah | Must |
| F2 | Pencarian | Cari berdasarkan nama wisata | Must |
| F3 | Detail wisata | Nama, galeri 2 foto, deskripsi, label harga asli dari spreadsheet | Must |
| F4 | Pilih bulan & tanggal | Dropdown bulan/tahun + kalender; tanggal lampau/kuota habis dinonaktifkan; harga per tanggal tampil (weekend otomatis + `is_weekend` + `weekend_note`) | Must |
| F5 | Pesan tiket | Jumlah 1–20, jenis tarif (dasar/paket bila ada rentang harga), data pemesan, total otomatis, kode booking `WJ-XXXXXXXX`; status awal **PENDING** dengan batas bayar 15 menit | Must |
| F6 | Pesanan saya | Cari by email/kode, lihat status (PENDING/Lunas/Refund/Expired) | Must |
| F7 | Ubah pesanan (Update) | Ganti **hanya `visit_date`** selama status Lunas; harga lama terkunci; jika tanggal baru lebih mahal → `requires_payment` + bayar selisih | Should |
| F8 | Refund | Pembatalan dengan alasan; nominal sesuai kebijakan | Must |
| F9 | CRUD wisata (Admin) | Tambah, ubah, hapus wisata; hapus ditolak jika ada pesanan aktif | Must |
| F10 | Hapus pesanan (Admin) | Hapus data booking | Could |
| F11 | Kuota harian | Kuota default 500 tiket/wisata/hari; pesanan melebihi kuota ditolak; PENDING yang belum kedaluwarsa tetap dihitung | Should |
| F12 | Pembayaran simulasi | Halaman `/bayar/{code}`: countdown 15 menit, pilih metode (QRIS/VA/e-wallet), instruksi per metode, tombol "Saya Sudah Bayar", batalkan PENDING | Must |
| F13 | Rekomendasi Penginapan JogjaStay | Bagian rekomendasi penginapan di wilayah destinasi dari API JogjaStay + modal detail in-app (pencocokan regional, tanpa klaim jarak) | Should |

### Aturan Harga (dari spreadsheet)
- Harga tunggal → dipakai langsung. Rentang (mis. Rp12.000–Rp20.000) → **tarif dasar** = nilai bawah, **paket/wahana** = nilai atas.
- Weekday/weekend → tarif weekend dipakai untuk Sabtu/Minggu. Destinasi tanpa `price_weekend` → harga dasar + `WEEKEND_SURCHARGE` (default Rp5.000). Harga Rp0 tidak dikenai tambahan.
- "Bayar sukarela" (Studio Alam Gamplong) → tiket Rp0; biaya wahana dibayar di lokasi.
- Tarif jeep dihitung **per jeep** (maks. 4 orang) – label asli ditampilkan; `qty` diartikan jumlah unit.
- Label harga asli selalu ditampilkan agar catatan seperti "+ retribusi kawasan" tidak hilang.

### Alur Pembayaran (Simulasi)
1. `POST /api/bookings` → booking masuk **PENDING**, `expires_at` = sekarang + 15 menit, email konfirmasi belum dikirim.
2. Redirect ke halaman `/bayar/{code}`: countdown mm:ss, pilih metode bayar, instruksi per metode.
3. `POST /api/bookings/{code}/pay` `{payment_method}` → status **PAID**, `paid_at` terisi, email konfirmasi terkirim.
4. PENDING yang lewat `expires_at` → **EXPIRED** (lazy via `expire_stale()`); EXPIRED tidak dihitung kuota.
5. `POST /api/bookings/{code}/cancel` → PENDING → **EXPIRED** (tanpa refund).

### Aturan Ubah Tanggal
- Hanya `visit_date` yang boleh dikirim; field lain → `400`.
- Status harus **PAID**; old & new tanggal harus ≥ besok.
- Harga **terkunci**: `unit_price` & `total` tidak berubah meski tanggal baru berbeda tarif.
- Jika harga tanggal baru > harga lama → response `200 {requires_payment: true, due_amount, expires_at}`, tanggal **belum berubah**; bayar selisih via `POST /pay` → tanggal baru aktif.
- Pending price change yang lewat waktu → pending dibuang, tanggal lama tetap berlaku.

### Kebijakan Refund
| Waktu pembatalan | Pengembalian |
|---|---|
| ≥ 3 hari sebelum kunjungan | 100% |
| 1–2 hari sebelum | 50% |
| Hari-H / lewat | Tidak dapat refund |
Refund hanya untuk status **PAID**. PENDING → `409` (batalkan lewat `/cancel`). Booking `REFUNDED`/`EXPIRED` tidak dapat di-refund atau diubah.

## 5. Kebutuhan Non-Fungsional
Responsif (mobile-first) · dark mode otomatis · waktu muat daftar < 2 detik (foto dikompres ≤ 900px) · validasi input di server · akses admin dengan header `X-Admin-Token` (env `ADMIN_TOKEN`) · semua respons JSON UTF-8 · lazy-load gambar.

## 6. Arsitektur & Teknologi
| Lapisan | Teknologi |
|---|---|
| Frontend | HTML + JavaScript murni (SPA hash-routing), tanpa build step, disajikan Flask |
| Backend | Python 3 + **Flask**, REST JSON |
| Database | SQLite (`wisata.db`), mudah diganti PostgreSQL |
| Data awal | `import_xlsx.py` membaca Excel → `data/destinations.json` + foto di `static/img` |

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

## 7. Model Data
- **regions**(slug PK, name, tagline)
- **destinations**(id PK, region FK, name, description, price_label, price, price_max, price_weekend, photos JSON, daily_quota)
- **bookings**(code PK, destination_id FK, visit_date, qty, tier, unit_price, total, name, email, phone, status `PENDING|PAID|REFUNDED|EXPIRED`, refund_amount, refund_reason, payment_method, paid_at, expires_at, pending_visit_date, pending_unit_price, due_amount, user_id, created_at, updated_at, source `web|<partner>`, external_ref, idempotency_key)

## 8. Kontrak API v1 & Interoperabilitas

Dokumentasi lengkap dan OpenAPI 3.0.3 tersedia secara interaktif di `/api/docs` dan `/api/v1/openapi.json`.
Semua endpoint tersedia di bawah prefix `/api/v1/...` serta backward-compatible di `/api/...`.

### 8.1 Endpoint Publik & Wisatawan
| Method & Path | Fungsi | Auth |
|---|---|---|
| GET `/api/v1/health` | Status kesehatan layanan (service, version, timestamp UTC) | – |
| GET `/api/v1/regions` | 5 wilayah + jumlah wisata | – |
| GET `/api/v1/destinations` | Daftar/filter wisata (opsional: `limit`, `offset`, `ids=1,2,3`, header `X-Total-Count`) | – |
| GET `/api/v1/destinations/{id}` | Detail wisata | – |
| GET `/api/v1/destinations/{id}/calendar` | Harga & sisa kuota per tanggal (`price`, `price_plus`, `is_weekend`, `weekend_note`) | – |
| GET `/api/v1/destinations/{id}/availability` | Real-time availability & tarif (parameter: `date`, `qty`, `tier`) | – |
| POST `/api/v1/bookings` | Buat pesanan wisatawan → status PENDING + `expires_at` (15 menit) | Login |
| GET `/api/v1/bookings` | Lihat pesanan user login / admin | User / Admin |
| GET `/api/v1/bookings/{code}` | Detail pesanan | – |
| PUT `/api/v1/bookings/{code}` | Ubah tanggal (`visit_date`) | Pemilik/Admin |
| POST `/api/v1/bookings/{code}/pay` | Pembayaran simulasi → status PAID | Pemilik |
| POST `/api/v1/bookings/{code}/cancel` | Batalkan PENDING → EXPIRED | Pemilik/Admin |
| POST `/api/v1/bookings/{code}/refund` | Refund dana (hanya status PAID) | Pemilik/Admin |

### 8.2 Endpoint Partner (Service-to-Service)
Autentikasi menggunakan header `Authorization: Bearer <PARTNER_KEY>`.
- **Asumsi Pembayaran Partner**: Pesanan dari partner diasumsikan pembayarannya sudah ditangani oleh sistem partner, sehingga langsung diterbitkan dengan **status `PAID`** (`payment_method='partner'`).
- **Idempotensi**: Partner menyertakan header `Idempotency-Key` untuk menjamin request ulang mengembalikan pesanan yang sama (HTTP 200) tanpa duplikasi transaksi.

| Method & Path | Fungsi | Auth |
|---|---|---|
| POST `/api/v1/partner/bookings` | Buat pesanan tiket langsung (status langsung PAID) | Partner Key |
| GET `/api/v1/partner/bookings/{code}` | Detail pesanan milik partner terkait (isolasi tenant) | Partner Key |
| GET `/api/v1/partner/bookings` | Daftar pesanan partner (filter `external_ref`, paginasi) | Partner Key |
| PUT `/api/v1/partner/bookings/{code}` | Ubah tanggal kunjungan tiket partner | Partner Key |
| POST `/api/v1/partner/bookings/{code}/refund` | Refund tiket partner (kebijakan 100% / 50% / hangus) | Partner Key |

### 8.3 Webhook Keluar & Integrasi
- **Webhooks**: Wisata Jogja memancarkan event `booking.created`, `booking.rescheduled`, `booking.refunded` bertanda tangan HMAC-SHA256 (`X-Wisata-Signature`) ke URL yang terdaftar di `WEBHOOK_URLS`.
- **Integrasi Hulu**: Endpoint adaptor ke Hotel (`/api/v1/integrations/hotels`), Transport (`/api/v1/integrations/transport`), dan pengecekan kesiapan (`/api/v1/integrations/status`).

Format Error Standar: `{"error": "<pesan>", "code": "<KODE>"}` dengan kode seragam:
`VALIDATION_ERROR`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `GONE`, `UNPROCESSABLE`, `RATE_LIMITED`, `INTERNAL_ERROR`, `UPSTREAM_ERROR`, `INTEGRATION_NOT_CONFIGURED`.
| POST `/api/bookings/{code}/cancel` | Batalkan PENDING → EXPIRED | Pemilik/Admin |
| POST `/api/bookings/{code}/refund` | Refund `{reason}` (hanya PAID) | Pemilik/Admin |
| DELETE `/api/bookings/{code}` | Hapus pesanan | Admin |

Kode error: `400` validasi · `401` token admin/auth · `403` bukan pemilik · `404` tidak ditemukan · `409` konflik (kuota/status) · `410` kedaluwarsa · `422` refund tidak diizinkan.

Metode pembayaran diterima: `qris`, `va_bca`, `va_bni`, `va_mandiri`, `gopay`, `ovo`, `dana`.

**Rencana integrasi:** Itinerary memanggil `GET /api/destinations` untuk menampilkan opsi wisata per hari, lalu `POST /api/bookings` saat pengguna checkout. Aktifkan CORS (`flask-cors`) bila dipanggil langsung dari frontend React. Saran: samakan format tanggal ISO `YYYY-MM-DD` dan simpan `booking.code` di itinerary sebagai referensi lintas layanan.

## 9. Alur Utama
1. Beranda → pilih wilayah → pilih wisata.
2. Detail → pilih bulan & tanggal → isi jumlah & data → **Pesan & Bayar** → kode booking (PENDING).
3. Halaman `/bayar/{code}` → pilih metode bayar → **Saya Sudah Bayar** → status PAID.
4. Pesanan Saya → ubah tanggal (bayar selisih bila perlu) atau **Refund** → nominal sesuai kebijakan.
5. Admin → masukkan token → tambah/ubah/hapus wisata.

## 10. Rencana Pengujian
`test_api.py` memverifikasi: 5 wilayah & 62 wisata, filter wilayah, CRUD wisata + otorisasi, tarif weekend (termasuk `WEEKEND_SURCHARGE`), ubah tanggal (harga terkunci, `requires_payment`, pending expired), alur pembayaran simulasi (PENDING → PAID → EXPIRED), kuota, refund 100%, refund ganda ditolak, tanggal lampau ditolak.

## 11. Cara Menjalankan
```bash
pip install -r requirements.txt
python app.py            # buka http://localhost:5000
python test_api.py       # jalankan tes (43 tes)
# Admin: menu "Admin", token default admin123 (ubah via env ADMIN_TOKEN)
```

## 12. Risiko & Pengembangan Lanjut
| Risiko | Mitigasi |
|---|---|
| Harga di spreadsheet dapat berubah | Admin dapat mengubah harga; label asli tetap tampil |
| Pembayaran masih simulasi | Tahap berikut: Midtrans/Xendit |
| Admin hanya token statis | Tahap berikut: login & role |
| SQLite untuk multi-pengguna berat | Pindah ke PostgreSQL |
| Harga akhir pekan ditambah via env | `WEEKEND_SURCHARGE` dapat disesuaikan per deployment |
Pengembangan lanjut: e-ticket QR, ulasan, paket gabungan rute (mis. Prambanan + Ratu Boko + Breksi).
