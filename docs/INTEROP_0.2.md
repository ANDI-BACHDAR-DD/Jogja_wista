# Contract 0.2 provider (Wisata Jogja)

Routes (also under `/api/interop` because the blueprint is mounted twice): `GET /api/v1/interop/capabilities`, `GET offers`, `POST holds`, `GET holds/{id}`, `POST holds/{id}/confirm`, `POST holds/{id}/release`. Implementation: `interop.py`; tests: `test_interop_0_2.py`.

- **A hold is a `bookings` row** with `status=PENDING` and `expires_at` (15 minutes). It counts against `daily_quota` through the existing `sold()` rule and is visible to staff. `source` is `interop:<partner>`, so a partner can only read its own holds.
- **Confirm** records the simulated payment: `PENDING -> PAID`, response `reserved` / `paid` with `simulation: true`, `voucher.code` = booking code. **Release** sets `CANCELLED` and erases name/email/phone. A lapsed hold becomes `EXPIRED` (also erased). Release after confirm is `409 ALREADY_CONFIRMED`.
- **Offers** are signed (HMAC-SHA256, 5 min, bound to partner, destination, date, quantity and unit price). `regionId` accepts `diy:kabupaten-sleman` or `kabupaten-sleman`; `lat/lng/radiusKm` are ignored (no coordinates). Only `startDate` is used.
- **Auth** reuses `PARTNER_KEYS` (`name:key`, key >= 24 chars). Use partner names `hotel`, `transport`, `itinerary`.

Environment: `INTEROP_OFFER_SIGNING_KEY` (>= 32 chars, required; capabilities returns 503 without it), `INTEROP_DURABLE_STORAGE` (`true` only when `DB_PATH` is on persistent storage).

## W2 — Durable Storage (syarat untuk transaksi live)

`capabilities.durableStorage` jujur secara default:
- `false` bila `DB_PATH` mengarah ke `/tmp` atau direktori temp OS (kasus Vercel gratis).
- `true` bila operator menyetel `INTEROP_DURABLE_STORAGE=true` **DAN** sudah memindahkan `DB_PATH` ke penyimpanan persisten.

> **Peringatan:** `INTEROP_DURABLE_STORAGE=true` hanya boleh disetel setelah database benar-benar persisten.
> Menyetelnya tanpa memindahkan DB adalah klaim palsu — klien seperti JogjaTrip akan
> mengaktifkan hold yang bisa hilang saat instans Vercel restart.

**Langkah W2 untuk operator:**
1. Siapkan database persisten: Turso (SQLite over HTTP), PlanetScale, Vercel Postgres, atau mount volume.
2. Set `DB_PATH` di env Vercel ke koneksi string atau path penyimpanan tetap.
3. Verifikasi hold bertahan setelah cold start sebelum menyetel `INTEROP_DURABLE_STORAGE=true`.
4. Jalankan `tools/interop-contract-check.mjs --confirm` pada staging untuk mendapat bukti 26/26 PASS.

**Known limit:** Tanpa W2 selesai, `durableStorage: false` dan konsumen (JogjaTrip) tidak akan mengaktifkan booking melalui Contract 0.2.
