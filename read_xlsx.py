import openpyxl

wb = openpyxl.load_workbook('Tiket_Wisata_Jogja.xlsx')
sheet = wb.active
for i, row in enumerate(sheet.iter_rows(values_only=True)):
    if i < 4: continue
    if row[0] and isinstance(row[0], str) and row[0].endswith('.'):
        print(f"REGION: {row[0]}")
    elif row[1]:
        print(f"  {row[1]}: {row[3]}")
