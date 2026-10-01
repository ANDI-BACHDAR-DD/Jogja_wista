# PRD – Aplikasi Wisata Jogja (Modul Objek Wisata)
**Mata kuliah:** Interoperabilitas Lanjut · **Proyek:** Jogja Itinerary (agregator 3 aplikasi) · **Versi:** 1.0

## 1. Ringkasan
Web app pemesanan tiket objek wisata di DIY dengan **5 wilayah** (Kota Yogyakarta, Sleman, Bantul, Gunungkidul, Kulon Progo) berisi **62 objek wisata** dari `Tiket_Wisata_Jogja.xlsx` (nama, deskripsi, harga, 2 foto). Aplikasi ini berdiri sendiri dan menyediakan REST API agar dapat dihubungkan ke **Jogja Itinerary** bersama aplikasi Transport (React + TanStack, Azam & Raissa) dan Hotel (Django, Ai & Putra).

## 2. Tujuan & Metrik
| Tujuan | Metrik keberhasilan |
|---|---|
| Wisatawan memesan tiket tanpa akun | Pemesanan selesai < 2 menit, ≤ 4 langkah |
| Data wisata dapat dikelola | CRUD wisata oleh admin tanpa ubah kode |
| Siap diintegrasikan | Semua fitur tersedia via REST JSON; 100% endpoint punya contoh respons |
| Refund jelas | Aturan refund otomatis & konsisten |

**Di luar cakupan v1:** payment gateway nyata (pembayaran disimulasikan, langsung `PAID`), login pengguna, e-ticket QR, multi-bahasa.

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
| F4 | Pilih bulan & tanggal | Dropdown bulan/tahun + kalender; tanggal lampau/kuota habis dinonaktifkan; harga per tanggal tampil (weekend otomatis) | Must |
| F5 | Pesan tiket | Jumlah 1–20, jenis tarif (dasar/paket bila ada rentang harga), data pemesan, total otomatis, kode booking `WJ-XXXXXXXX` | Must |
| F6 | Pesanan saya | Cari by email/kode, lihat status (Lunas/Refund) | Must |
| F7 | Ubah pesanan (Update) | Ganti tanggal, jumlah, nama/HP selama status Lunas; harga dihitung ulang | Should |
| F8 | Refund | Pembatalan dengan alasan; nominal sesuai kebijakan | Must |
| F9 | CRUD wisata (Admin) | Tambah, ubah, hapus wisata; hapus ditolak jika ada pesanan aktif | Must |
| F10 | Hapus pesanan (Admin) | Hapus data booking | Could |
| F11 | Kuota harian | Kuota default 500 tiket/wisata/hari; pesanan melebihi kuota ditolak | Should |

### Aturan Harga (dari spreadsheet)
- Harga tunggal → dipakai langsung. Rentang (mis. Rp12.000–Rp20.000) → **tarif dasar** = nilai bawah, **paket/wahana** = nilai atas.
- Weekday/weekend (Gembira Loka, Taman Pelangi) → tarif weekend dipakai untuk Sabtu/Minggu.
- "Bayar sukarela" (Studio Alam Gamplong) → tiket Rp0; biaya wahana dibayar di lokasi.
- Tarif jeep dihitung **per jeep** (maks. 4 orang) – label asli ditampilkan; `qty` diartikan jumlah unit.
- Label harga asli selalu ditampilkan agar catatan seperti "+ retribusi kawasan" tidak hilang.

### Kebijakan Refund
| Waktu pembatalan | Pengembalian |
|---|---|
| ≥ 3 hari sebelum kunjungan | 100% |
| 1–2 hari sebelum | 50% |
| Hari-H / lewat | Tidak dapat refund |
Booking yang sudah `REFUNDED` tidak dapat di-refund atau diubah lagi.

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
[Transport: React+TanStack] ─┐
[Hotel: Django]             ─┼─► [Jogja Itinerary] ─► REST ─► [Wisata: Flask + SQLite]
[Browser wisatawan]         ─┘
```

## 7. Model Data
- **regions**(slug PK, name, tagline)
- **destinations**(id PK, region FK, name, description, price_label, price, price_max, price_weekend, photos JSON, daily_quota)
- **bookings**(code PK, destination_id FK, visit_date, qty, tier, unit_price, total, name, email, phone, status `PAID|REFUNDED`, refund_amount, refund_reason, created_at, updated_at)

## 8. Kontrak API (dasar integrasi Jogja Itinerary)
| Method & Path | Fungsi | Auth |
|---|---|---|
| GET `/api/regions` | 5 wilayah + jumlah wisata | – |
| GET `/api/destinations?region=sleman&q=candi` | Daftar/filter wisata | – |
| GET `/api/destinations/{id}` | Detail wisata | – |
| GET `/api/destinations/{id}/calendar?month=2026-11` | Harga & sisa kuota per tanggal | – |
| POST `/api/destinations` · PUT/DELETE `/api/destinations/{id}` | CRUD wisata | Admin |
| POST `/api/bookings` | Buat pesanan `{destination_id, visit_date, qty, tier, name, email, phone}` | – |
| GET `/api/bookings?email=&code=` · GET `/api/bookings/{code}` | Lihat pesanan | – |
| PUT `/api/bookings/{code}` | Ubah tanggal/jumlah/data | – |
| POST `/api/bookings/{code}/refund` | Refund `{reason}` | – |
| DELETE `/api/bookings/{code}` | Hapus pesanan | Admin |

Kode error: `400` validasi · `401` token admin · `404` tidak ditemukan · `409` konflik (kuota/status) · `422` refund tidak diizinkan.

**Rencana integrasi:** Itinerary memanggil `GET /api/destinations` untuk menampilkan opsi wisata per hari, lalu `POST /api/bookings` saat pengguna checkout. Aktifkan CORS (`flask-cors`) bila dipanggil langsung dari frontend React. Saran: samakan format tanggal ISO `YYYY-MM-DD` dan simpan `booking.code` di itinerary sebagai referensi lintas layanan.

## 9. Alur Utama
1. Beranda → pilih wilayah → pilih wisata.
2. Detail → pilih bulan & tanggal → isi jumlah & data → **Pesan & Bayar** → kode booking.
3. Pesanan Saya → ubah tanggal atau **Refund** → nominal sesuai kebijakan.
4. Admin → masukkan token → tambah/ubah/hapus wisata.

## 10. Rencana Pengujian
`test_api.py` memverifikasi: 5 wilayah & 62 wisata, filter wilayah, CRUD wisata + otorisasi, tarif weekend, ubah pesanan, kuota, refund 100%, refund ganda ditolak, tanggal lampau ditolak.

## 11. Cara Menjalankan
```bash
pip install -r requirements.txt
python app.py            # buka http://localhost:5000
python test_api.py       # jalankan tes
# Admin: menu "Admin", token default admin123 (ubah via env ADMIN_TOKEN)
```

## 12. Risiko & Pengembangan Lanjut
| Risiko | Mitigasi |
|---|---|
| Harga di spreadsheet dapat berubah | Admin dapat mengubah harga; label asli tetap tampil |
| Pembayaran masih simulasi | Tahap berikut: Midtrans/Xendit + status `PENDING` |
| Admin hanya token statis | Tahap berikut: login & role |
| SQLite untuk multi-pengguna berat | Pindah ke PostgreSQL |
Pengembangan lanjut: e-ticket QR, email konfirmasi, ulasan, paket gabungan rute (mis. Prambanan + Ratu Boko + Breksi).
