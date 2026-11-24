#!/bin/bash
set -e
source venv/bin/activate
python -m pytest test_api.py test_interop.py -q
git status --short
read -p "Pesan commit: " MSG
git add -A
if git diff --cached --name-only | grep -E '(^|/)(\.env|wisata\.db|venv/)'; then
  echo "STOP: ada file rahasia/besar ikut ter-stage"; git reset; exit 1
fi
git commit -m "$MSG"
git push origin main
echo "Terkirim. Pantau deploy di vercel.com/dashboard"
