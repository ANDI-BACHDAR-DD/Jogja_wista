# Contract 0.2 provider (Wisata Jogja)

Routes (also under `/api/interop` because the blueprint is mounted twice): `GET /api/v1/interop/capabilities`, `GET offers`, `POST holds`, `GET holds/{id}`, `POST holds/{id}/confirm`, `POST holds/{id}/release`. Implementation: `interop.py`; tests: `test_interop_0_2.py`.

- **A hold is a `bookings` row** with `status=PENDING` and `expires_at` (15 minutes). It counts against `daily_quota` through the existing `sold()` rule and is visible to staff. `source` is `interop:<partner>`, so a partner can only read its own holds.
- **Confirm** records the simulated payment: `PENDING -> PAID`, response `reserved` / `paid` with `simulation: true`, `voucher.code` = booking code. **Release** sets `CANCELLED` and erases name/email/phone. A lapsed hold becomes `EXPIRED` (also erased). Release after confirm is `409 ALREADY_CONFIRMED`.
- **Offers** are signed (HMAC-SHA256, 5 min, bound to partner, destination, date, quantity and unit price). `regionId` accepts `diy:kabupaten-sleman` or `kabupaten-sleman`; `lat/lng/radiusKm` are ignored (no coordinates). Only `startDate` is used.
- **Auth** reuses `PARTNER_KEYS` (`name:key`, key >= 24 chars). Use partner names `hotel`, `transport`, `itinerary`.

Environment: `INTEROP_OFFER_SIGNING_KEY` (>= 32 chars, required; capabilities returns 503 without it), `INTEROP_DURABLE_STORAGE` (`true` only when `DB_PATH` is on persistent storage).

**Known limit (W2):** on Vercel the database is SQLite in `/tmp`, so `capabilities.durableStorage` is `false` and consumers that require durable holds will not enable booking. Move `DB_PATH` to persistent storage (or a hosted database) and set `INTEROP_DURABLE_STORAGE=true` to turn this on.
