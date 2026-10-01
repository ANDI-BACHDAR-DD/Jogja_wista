import os, json, re
import openpyxl

def slugify(text):
    text = re.sub(r'^\d+\.\s*', '', text)
    text = text.split('—')[0].strip()
    return text.lower().replace(' ', '-').replace('/', '-')

def main():
    os.makedirs('data', exist_ok=True)
    os.makedirs('static/img', exist_ok=True)

    wb = openpyxl.load_workbook('Tiket_Wisata_Jogja.xlsx', data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))

    regions = []
    destinations = []
    current_region_slug = None
    
    # map images to row and col
    img_map = {}
    for img in sheet._images:
        r = img.anchor._from.row
        c = img.anchor._from.col
        if r not in img_map:
            img_map[r] = {}
        img_map[r][c] = img

    dest_id = 1
    for r_idx, row in enumerate(rows):
        val0 = row[0]
        if isinstance(val0, str) and val0.endswith('.'):
            # Region
            name_part = val0.split('—')[0].strip()
            name = re.sub(r'^\d+\.\s*', '', name_part)
            tagline = val0.split('—')[1].strip() if '—' in val0 else ''
            slug = slugify(name_part)
            current_region_slug = slug
            regions.append({"slug": slug, "name": name, "tagline": tagline})
        elif isinstance(val0, (int, float)) and val0 > 0:
            # Destination
            name = row[1]
            desc = row[2]
            price_label = row[3]
            
            price = 0
            price_max = 0
            price_weekend = 0
            
            nums = [int(x.replace('.', '')) for x in re.findall(r'Rp([\d\.]+)', str(price_label))]
            text_lower = str(price_label).lower()
            
            if "sukarela" in text_lower:
                price = 0
            elif "weekend" in text_lower and len(nums) >= 2:
                price = nums[0]
                price_weekend = nums[1]
            elif nums:
                price = min(nums)
                if max(nums) > price:
                    price_max = max(nums)
            
            # extract photos
            photos = []
            if r_idx in img_map:
                cols = sorted(img_map[r_idx].keys())
                for i, c in enumerate(cols):
                    if i >= 2: break
                    img_obj = img_map[r_idx][c]
                    img_path = f"/static/img/{dest_id}-{i+1}.jpg"
                    local_path = f"static/img/{dest_id}-{i+1}.jpg"
                    with open(local_path, 'wb') as f:
                        f.write(img_obj._data())
                    photos.append(img_path)
            
            destinations.append({
                "id": dest_id,
                "region": current_region_slug,
                "name": name,
                "description": desc,
                "price_label": price_label,
                "price": price,
                "price_max": price_max,
                "price_weekend": price_weekend,
                "photos": photos,
                "daily_quota": 500
            })
            dest_id += 1

    with open('data/destinations.json', 'w') as f:
        json.dump({"regions": regions, "destinations": destinations}, f, indent=2)

    print(f"Imported {len(regions)} regions and {len(destinations)} destinations.")

if __name__ == '__main__':
    main()
