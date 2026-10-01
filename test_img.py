import os
import openpyxl

wb = openpyxl.load_workbook('Tiket_Wisata_Jogja.xlsx', data_only=True)
sheet = wb.active

img = sheet._images[0]
print(type(img))
try:
    print(len(img._data()))
except Exception as e:
    print("No _data:", e)
