#!/usr/bin/env bash
# verify_hotel.sh - Skrip verifikasi integrasi Wisata Jogja -> Hotel JogjaStay
# Penggunaan: ./verify_hotel.sh [BASE_URL]
set -e

BASE_URL="${1:-http://localhost:5001}"
BASE_URL="${BASE_URL%/}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}  Verifikasi Integrasi Wisata Jogja -> Hotel JogjaStay${NC}"
echo -e "${CYAN}  Target Base URL: ${BASE_URL}${NC}"
echo -e "${CYAN}======================================================${NC}\n"

PASS_COUNT=0
FAIL_COUNT=0

check_status() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [ "$actual" -eq "$expected" ]; then
        echo -e "  [${GREEN}PASS${NC}] $label (Status: $actual)"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  [${RED}FAIL${NC}] $label (Expected: $expected, Actual: $actual)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# 1. Health check
echo -e "${YELLOW}[1/4] Menguji Health Check...${NC}"
HEALTH_HTTP=$(curl -s -o /tmp/health_resp.json -w "%{http_code}" "${BASE_URL}/api/v1/health" || echo "000")
check_status "GET /api/v1/health" 200 "$HEALTH_HTTP"
if [ "$HEALTH_HTTP" -eq 200 ]; then
    python3 -c "
import json
with open('/tmp/health_resp.json') as f:
    d = json.load(f)
print(f'         Status  : {d.get(\"status\")}')
print(f'         Service : {d.get(\"service\")}')
print(f'         Version : {d.get(\"version\")}')
"
fi
echo ""

# 2. Ambil destinasi dari 5 wilayah
echo -e "${YELLOW}[2/4] Mengambil 1 destinasi perwakilan dari 5 wilayah...${NC}"
DEST_HTTP=$(curl -s -o /tmp/dests.json -w "%{http_code}" "${BASE_URL}/api/v1/destinations" || echo "000")
check_status "GET /api/v1/destinations" 200 "$DEST_HTTP"

if [ "$DEST_HTTP" -eq 200 ]; then
    python3 -c "
import json

with open('/tmp/dests.json') as f:
    dests = json.load(f)

regions = [
    'kota-yogyakarta',
    'kabupaten-sleman',
    'kabupaten-bantul',
    'kabupaten-gunungkidul',
    'kabupaten-kulon-progo'
]

selected = {}
for d in dests:
    r = d.get('region')
    if r in regions and r not in selected:
        selected[r] = d

with open('/tmp/selected_dests.json', 'w') as f:
    json.dump(selected, f)
"
    echo -e "  Destinasi terpilih untuk 5 wilayah tersimpan."
fi
echo ""

# 3. Uji rekomendasi hotel untuk kelima wilayah
echo -e "${YELLOW}[3/4] Menguji Rekomendasi Hotel (5 Wilayah)...${NC}"
FIRST_HOTEL_ID=""

if [ -f /tmp/selected_dests.json ]; then
    REGIONS=("kota-yogyakarta" "kabupaten-sleman" "kabupaten-bantul" "kabupaten-gunungkidul" "kabupaten-kulon-progo")
    for reg in "${REGIONS[@]}"; do
        DEST_ID=$(python3 -c "import json; d=json.load(open('/tmp/selected_dests.json')); print(d.get('$reg', {}).get('id', ''))")
        DEST_NAME=$(python3 -c "import json; d=json.load(open('/tmp/selected_dests.json')); print(d.get('$reg', {}).get('name', ''))")
        
        if [ -n "$DEST_ID" ]; then
            HOTEL_HTTP=$(curl -s -o /tmp/hotel_recs.json -w "%{http_code}" "${BASE_URL}/api/v1/destinations/${DEST_ID}/hotels" || echo "000")
            check_status "GET /api/v1/destinations/${DEST_ID}/hotels ($reg)" 200 "$HOTEL_HTTP"
            
            if [ "$HOTEL_HTTP" -eq 200 ]; then
                python3 -c "
import json
with open('/tmp/hotel_recs.json') as f:
    data = json.load(f)
hotels = data.get('hotels', [])
count = data.get('count', len(hotels))
first_name = hotels[0].get('name') if hotels else '(Tidak ada hotel)'
first_id = hotels[0].get('id') if hotels else ''
print(f'         Destinasi : [#{DEST_ID}] {DEST_NAME}')
print(f'         Wilayah   : {reg}')
print(f'         Ditemukan : {count} hotel rekomendasi')
print(f'         Hotel #1  : {first_name} (ID: {first_id})')
if first_id:
    with open('/tmp/first_hotel_id.txt', 'w') as out:
        out.write(str(first_id))
"
            fi
        else
            echo -e "  [${YELLOW}SKIP${NC}] Tidak ada destinasi untuk wilayah $reg"
        fi
        echo ""
    done
fi

if [ -f /tmp/first_hotel_id.txt ]; then
    FIRST_HOTEL_ID=$(cat /tmp/first_hotel_id.txt)
fi

# 4. Uji detail hotel & 404
echo -e "${YELLOW}[4/4] Menguji Detail Hotel & Error Handling...${NC}"
if [ -n "$FIRST_HOTEL_ID" ]; then
    DETAIL_HTTP=$(curl -s -o /tmp/hotel_detail.json -w "%{http_code}" "${BASE_URL}/api/v1/integrations/hotels/${FIRST_HOTEL_ID}" || echo "000")
    check_status "GET /api/v1/integrations/hotels/${FIRST_HOTEL_ID}" 200 "$DETAIL_HTTP"
    if [ "$DETAIL_HTTP" -eq 200 ]; then
        python3 -c "
import json
with open('/tmp/hotel_detail.json') as f:
    d = json.load(f)
print(f'         Nama Hotel : {d.get(\"name\")}')
print(f'         Alamat     : {d.get(\"address\")}')
print(f'         Rating     : {d.get(\"rating\")}')
print(f'         Harga Mulai: {d.get(\"price_from\")}')
print(f'         Kamar      : {len(d.get(\"rooms\", []))} tipe kamar tersedia')
"
    fi
else
    echo -e "  [${YELLOW}SKIP${NC}] Tidak ada hotel_id untuk diuji detail"
fi
echo ""

# 5. Uji 404 untuk destinasi tak ada
ERR_HTTP=$(curl -s -o /tmp/hotel_err.json -w "%{http_code}" "${BASE_URL}/api/v1/destinations/999999/hotels" || echo "000")
check_status "GET /api/v1/destinations/999999/hotels (harus 404)" 404 "$ERR_HTTP"
if [ "$ERR_HTTP" -eq 404 ]; then
    python3 -c "
import json
with open('/tmp/hotel_err.json') as f:
    d = json.load(f)
assert d.get('code') == 'NOT_FOUND'
print(f'         Format Error: code={d.get(\"code\")}, error={d.get(\"error\")}')
"
fi
echo ""

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}  HASIL VERIFIKASI: ${GREEN}${PASS_COUNT} LULUS${NC}, ${RED}${FAIL_COUNT} GAGAL${NC}"
echo -e "${CYAN}======================================================${NC}"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
