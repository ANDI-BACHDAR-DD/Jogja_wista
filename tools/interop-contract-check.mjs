#!/usr/bin/env node
// Shared Contract 0.2 test: run the SAME checks against any provider (Transport, Hotel, Wisata).
//   node interop-contract-check.mjs --base https://provider.example --token <partner token>
//        [--token2 <another partner's token>] [--start 2026-12-20] [--region diy:kabupaten-sleman]
//        [--entity vehicle_rental] [--confirm]
// Without --confirm nothing is ever confirmed (holds are created and released only).
// With --confirm one extra hold is confirmed: use it on staging with dummy data, never on production.
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {randomUUID} from 'node:crypto';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
// Change a character in the middle of the id. The last base64url character of a signature carries unused bits,
// so altering only that one can decode to the same bytes (about 1 in 16 ids) and wrongly stay valid.
function tamper(id) { const i = Math.floor(id.length / 2); return id.slice(0, i) + (id[i] === 'A' ? 'B' : 'A') + id.slice(i + 1); }

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, all) => {
  if (x.startsWith('--')) a.push([x.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return a;
}, []));
if (!args.base || !args.token) { console.error('usage: --base URL --token TOKEN [--token2 T] [--start YYYY-MM-DD] [--region diy:...] [--entity TYPE] [--confirm]'); process.exit(2); }
const base = String(args.base).replace(/\/+$/, '') + '/api/v1/interop';
const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'json-schema');
const ajv = new Ajv({allErrors: true, strict: false}); addFormats(ajv);
const schema = n => ajv.compile(JSON.parse(readFileSync(join(dir, n + '.schema.json'), 'utf8')));
const V = {caps: schema('capabilities'), offers: schema('offers-response'), hold: schema('hold-response'), error: schema('error')};
const day = n => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);
const start = args.start || day(30), end = day(Math.round((Date.parse(start) - Date.now()) / 864e5) + 2);

async function call(path, {method = 'GET', body, key, token = args.token, headers = {}} = {}) {
  const res = await fetch(base + path, {method, headers: {Accept: 'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {}), ...(body ? {'Content-Type': 'application/json'} : {}), ...(key ? {'Idempotency-Key': key} : {}), ...headers}, ...(body ? {body: JSON.stringify(body)} : {})});
  let data = null; try { data = await res.json(); } catch { /* non-JSON */ }
  return {status: res.status, data};
}
const results = []; const rec = (id, ok, note = '') => { results.push({id, ok, note}); console.log(`${ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'}  ${id}${note ? '  - ' + note : ''}`); };
const check = (id, cond, note) => rec(id, !!cond, cond ? '' : note);
const schemaOk = (id, v, data) => { const ok = v(data); rec(id, ok, ok ? '' : JSON.stringify(v.errors?.slice(0, 3))); return ok; };
const newKey = () => randomUUID().replaceAll('-', '');
const cleanup = [];

try {
  // 1. Capabilities and auth
  check('01 no token -> 401', (await call('/capabilities', {token: null})).status === 401, 'expected 401');
  check('01 wrong token -> 401', (await call('/capabilities', {token: 'x'.repeat(30)})).status === 401, 'expected 401');
  const caps = await call('/capabilities');
  if (!schemaOk('02 capabilities match schema', V.caps, caps.data)) throw new Error('capabilities unusable');
  check('02 holds=true, TTL 15, contract 0.2.0', caps.data.holds === true && caps.data.holdTtlMinutes === 15 && caps.data.contract === '0.2.0', JSON.stringify(caps.data));
  rec('02 durableStorage is honest (info)', caps.data.durableStorage ? true : null, caps.data.durableStorage ? '' : 'false: consumers will not enable booking');
  const fields = [...new Set([...(caps.data.requiredCustomerFields || ['name', 'phone']), ...(caps.data.optionalCustomerFields?.includes('email') ? ['email'] : [])])];
  const dummy = {name: 'Dummy QA', phone: '081234567890', email: 'qa-dummy@example.test'};
  const customer = Object.fromEntries(fields.map(f => [f, dummy[f]]));
  const entity = args.entity || caps.data.entityTypes[0];

  // 2. Offers
  const qs = new URLSearchParams({startDate: start, endDate: end, entityType: entity, quantity: '1', limit: '20', ...(args.region ? {regionId: args.region} : {})});
  const offers = await call('/offers?' + qs);
  if (!schemaOk('03 offers match schema', V.offers, offers.data)) throw new Error('offers unusable');
  const offer = offers.data.offers[0];
  if (!offer) { rec('03 at least one offer for the chosen dates', null, 'no offer: pick other --start/--region'); throw new Error('no offer'); }
  const stockBefore = offer.remaining;
  check('03 bad dates -> 400', (await call('/offers?startDate=not-a-date')).status === 400, 'expected 400');

  // 3. Hold, replay, conflicts
  const ref = 'CT-' + randomUUID().slice(0, 12), k1 = newKey();
  const body = {offerId: offer.offerId, externalRef: ref, consent: true, customer};
  const h1 = await call('/holds', {method: 'POST', body, key: k1});
  if (!schemaOk('04 hold 201 matches schema', V.hold, h1.data) || h1.status !== 201) { check('04 hold created', false, `status ${h1.status} ${JSON.stringify(h1.data)}`); throw new Error('hold failed'); }
  cleanup.push(h1.data.holdId);
  check('04 awaiting_payment, externalRef echoed, expiry within 15 min', h1.data.reservationState === 'awaiting_payment' && h1.data.externalRef === ref && Date.parse(h1.data.expiresAt) - Date.now() <= 15 * 60e3 + 5e3 && Date.parse(h1.data.expiresAt) > Date.now(), JSON.stringify(h1.data));
  const h1b = await call('/holds', {method: 'POST', body, key: k1});
  check('05 replay same key+body -> 200 same hold', h1b.status === 200 && h1b.data.holdId === h1.data.holdId, `${h1b.status}`);
  const conflict = await call('/holds', {method: 'POST', body: {...body, notes: 'different body'}, key: k1});
  check('05 same key, other body -> 409 IDEMPOTENCY_CONFLICT', conflict.status === 409 && conflict.data?.code === 'IDEMPOTENCY_CONFLICT', `${conflict.status} ${conflict.data?.code}`);
  const stock = (await call('/offers?' + qs)).data.offers.find(o => o.resourceId === offer.resourceId);
  check('06 a hold counts as stock (remaining dropped or offer gone)', !stock || stock.remaining <= stockBefore - 1, `before ${stockBefore} after ${stock?.remaining}`);

  // 4. Validation
  const noConsent = await call('/holds', {method: 'POST', body: {...body, externalRef: 'CT-' + randomUUID().slice(0, 12), consent: false}, key: newKey()});
  check('07 consent=false -> 400 CONSENT_REQUIRED', noConsent.status === 400 && noConsent.data?.code === 'CONSENT_REQUIRED', `${noConsent.status} ${noConsent.data?.code}`);
  const longRef = await call('/holds', {method: 'POST', body: {...body, externalRef: 'A'.repeat(65)}, key: newKey()});
  check('07 externalRef 65 chars -> 400', longRef.status === 400, `${longRef.status}`);
  const bad = await call('/holds', {method: 'POST', body: {...body, externalRef: 'CT-' + randomUUID().slice(0, 12), offerId: tamper(offer.offerId)}, key: newKey()});
  check('07 tampered offerId -> 422 INVALID_OFFER', bad.status === 422 && bad.data?.code === 'INVALID_OFFER', `${bad.status} ${bad.data?.code}`);
  const noKey = await call('/holds', {method: 'POST', body: {...body, externalRef: 'CT-' + randomUUID().slice(0, 12)}});
  check('07 missing Idempotency-Key -> 400', noKey.status === 400, `${noKey.status}`);
  for (const r of [bad, noConsent, conflict]) if (r.data && !V.error(r.data)) { rec('07 error body matches {code,message}', false, JSON.stringify(V.error.errors?.slice(0, 2))); break; }

  // 5. Read, ownership
  const g = await call('/holds/' + h1.data.holdId);
  check('08 GET hold = same state', g.status === 200 && g.data.holdId === h1.data.holdId && g.data.reservationState === 'awaiting_payment', `${g.status}`);
  check('08 unknown hold -> 404', (await call('/holds/NOPE-' + randomUUID().slice(0, 8))).status === 404, 'expected 404');
  if (args.token2) check('08 another partner cannot read it -> 404', (await call('/holds/' + h1.data.holdId, {token: args.token2})).status === 404, 'expected 404');
  else rec('08 another partner cannot read it', null, 'pass --token2 to test');

  // 6. Release path
  const r1 = await call(`/holds/${h1.data.holdId}/release`, {method: 'POST', key: newKey()});
  check('09 release -> 200 cancelled', r1.status === 200 && r1.data.reservationState === 'cancelled', `${r1.status} ${r1.data?.reservationState}`);
  check('09 release twice -> 200', (await call(`/holds/${h1.data.holdId}/release`, {method: 'POST', key: newKey()})).status === 200, 'expected 200');
  const c0 = await call(`/holds/${h1.data.holdId}/confirm`, {method: 'POST', key: newKey()});
  check('09 confirm after release -> 409 HOLD_RELEASED', c0.status === 409 && c0.data?.code === 'HOLD_RELEASED', `${c0.status} ${c0.data?.code}`);
  const back = (await call('/offers?' + qs)).data.offers.find(o => o.resourceId === offer.resourceId);
  check('09 release returns the stock', !!back && back.remaining >= stockBefore, `before ${stockBefore} after ${back?.remaining}`);

  // 7. Confirm path (mutates the provider: opt-in)
  if (args.confirm) {
    const o2 = (await call('/offers?' + qs)).data.offers[0];
    const h2 = await call('/holds', {method: 'POST', body: {offerId: o2.offerId, externalRef: 'CT-' + randomUUID().slice(0, 12), consent: true, customer}, key: newKey()});
    if (h2.status === 201) {
      const c = await call(`/holds/${h2.data.holdId}/confirm`, {method: 'POST', key: newKey()});
      check('10 confirm -> 200 reserved + voucher.code/note', c.status === 200 && V.hold(c.data) && c.data.reservationState === 'reserved' && !!c.data.voucher?.code && !!c.data.voucher?.note, `${c.status} ${JSON.stringify(c.data)}`);
      check('10 confirm twice -> same answer', (await call(`/holds/${h2.data.holdId}/confirm`, {method: 'POST', key: newKey()})).data?.holdId === h2.data.holdId, 'expected same hold');
      const rr = await call(`/holds/${h2.data.holdId}/release`, {method: 'POST', key: newKey()});
      check('10 release after confirm -> 409 ALREADY_CONFIRMED', rr.status === 409 && rr.data?.code === 'ALREADY_CONFIRMED', `${rr.status} ${rr.data?.code}`);
    } else check('10 second hold for the confirm path', false, `${h2.status} ${JSON.stringify(h2.data)}`);
  } else rec('10 confirm path', null, 'pass --confirm on staging to exercise it');
} catch (e) { if (!/unusable|no offer|hold failed/.test(e.message)) rec('crash', false, e.message); }
finally {
  for (const id of cleanup) { try { await call(`/holds/${id}/release`, {method: 'POST', key: newKey()}); } catch { /* best effort */ } }
}
const failed = results.filter(r => r.ok === false).length, skipped = results.filter(r => r.ok === null).length;
console.log(`\n${results.length - failed - skipped} passed, ${failed} failed, ${skipped} skipped against ${base}`);
process.exit(failed ? 1 : 0);
