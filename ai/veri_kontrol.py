from pathlib import Path
import pandas as pd

klasor = Path(__file__).resolve().parent

normal = pd.read_csv(klasor / "veri" / "normal.csv", sep=";")
test = pd.read_csv(klasor / "veri" / "test.csv", sep=";")

print("Normal veri boyutu:", normal.shape)
print("Test veri boyutu:", test.shape)

print("\nNormal veride makine ve durum sayıları:")
print(normal.groupby(["makine_id", "durum"]).size())

print("\nNormal veride arıza etiketleri:")
print(normal["ariza_etiketi"].value_counts())

print("\nTest verisinde arıza etiketleri:")
print(test["ariza_etiketi"].value_counts())

print("\nNormal veride toplam eksik değer:")
print(normal.isna().sum().sum())

print("\nTest verisinde toplam eksik değer:")
print(test.isna().sum().sum())

normal["durum"] = normal["durum"].replace({"wking": "working"})
test["durum"] = test["durum"].replace({"wking": "working"})