# Skenario pengujian interoperabilitas

## A. Uji kontrak otomatis (per penyedia)

```
cd tools && npm install
node interop-contract-check.mjs --base https://<penyedia> --token <token mitra> --token2 <token mitra lain> --region diy:kabupaten-sleman [--confirm]
```

`--confirm` menjalankan jalur konfirmasi dan mengubah data penyedia: hanya untuk staging dengan data dummy. Skrip keluar dengan kode 1 bila ada pemeriksaan gagal. Hasil terakhir: Wisata lokal 26 lulus, 0 gagal. Transport dan Hotel belum diuji karena belum dideploy dari patch.

| Nomor | Yang dibuktikan |
| --- | --- |
| 01 | Tanpa token dan token salah ditolak 401 |
| 02 | `capabilities` sesuai skema, `holds=true`, TTL 15, kontrak 0.2.0 |
| 03 | `offers` sesuai skema, tanggal salah 400 |
| 04 | Hold 201 sesuai skema, `awaiting_payment`, kedaluwarsa paling lama 15 menit |
| 05 | Kunci sama dan isi sama 200 hold sama, isi beda 409 `IDEMPOTENCY_CONFLICT` |
| 06 | Hold dihitung sebagai stok |
| 07 | `consent=false` 400 `CONSENT_REQUIRED`, `externalRef` 65 karakter 400, `offerId` diubah 422 `INVALID_OFFER`, tanpa kunci 400, tubuh kesalahan `{code,message}` |
| 08 | GET sama dengan hold, id tidak dikenal 404, mitra lain 404 |
| 09 | Release 200, dua kali 200, confirm sesudah release 409 `HOLD_RELEASED`, stok kembali |
| 10 | Confirm 200 `reserved` + `voucher.code`, dua kali sama, release sesudahnya 409 `ALREADY_CONFIRMED` |

## B. Skenario proses bisnis (bukti untuk laporan)

| Kode | Skenario | Hasil yang diharapkan | Bukti |
| --- | --- | --- | --- |
| E1 | Hotel memesan kamar + kendaraan Transport | Kamar tercatat, voucher kendaraan `reserved`, urutan panggilan hold lalu confirm | Layar voucher dan baris `booking_interop_groups` bernilai `RESERVED` |
| E2 | Kamar habis setelah hold kendaraan | Kendaraan dilepas, tidak ada booking, stok kendaraan kembali | Status `RELEASED`, `GET` hold `cancelled` |
| E3 | Respons hold hilang lalu pengguna mengulang | Tetap satu hold dan satu booking | `interop_holds` berisi satu baris untuk `externalRef` itu |
| E4 | Hold kedaluwarsa sebelum confirm | `409 HOLD_EXPIRED`, pesanan tidak dilanjutkan, pengguna diminta memilih ulang | Respons dan pesan antarmuka |
| E5 | Penyedia mati atau `capabilities` gagal | Panel add-on hilang, pesan kamar saja tetap berhasil | Layar dan log |
| E6 | Tiket Wisata kuota habis saat hold | `409 NOT_AVAILABLE`, hold lain di pesanan dilepas | Respons dan kuota di Wisata |
| E7 | Pengguna tidak menyetujui consent | Tidak ada panggilan POST ke penyedia | Log penyedia kosong |
| E8 | Itinerary memesan paket 3 penyedia, satu gagal | Semua hold dilepas, tidak ada reservasi | Jurnal saga dan tiga `GET` hold `cancelled` |
| E9 | Confirm sebagian berhasil lalu timeout | Status `PARTIAL` atau `UNKNOWN`, tidak ada pembatalan otomatis | Jurnal saga dan `GET` rekonsiliasi |
| E10 | Mitra A membaca hold mitra B | 404 | Respons |

E1 dan E2 sudah punya uji otomatis di repo Hotel (`test/interop-consumer.test.mjs`) dengan penyedia tiruan; E1 sampai E10 terhadap sistem yang dideploy dijalankan pada staging dan dicatat sebagai bukti.

## Pembayaran simulasi dan rekomendasi (BPI V5)

| ID | Skenario | Yang terjadi | Bukti |
|---|---|---|---|
| 03 | `regionId` ketat | semua offer berwilayah sama; wilayah lain tidak bocor | checker langkah 03 |
| 11 | Confirm dengan `payment` | `reserved`, `paymentState: paid`, `payment.reference`, voucher; ulang sama persis menjawab sama | checker langkah 11 |
| 11 | Jumlah salah / penyedia tanpa dukungan | `400 INVALID_PAYMENT` atau `400 PAYMENT_NOT_SUPPORTED`; hold tidak berubah | checker langkah 11 |
| E10 | Hotel di Sleman dipilih | rekomendasi hanya tiket wisata dan kendaraan Sleman untuk tanggal menginap | layar add-on dan log offers |
| E11 | Satu hold add-on gagal | add-on lain dilepas, checkout lanjut tanpa add-on itu | baris jurnal `RELEASED`, pesanan utama tercatat |
| E12 | Pembayaran simulasi gagal | semua hold dilepas, tidak ada pesanan | `GET` hold `cancelled` |
