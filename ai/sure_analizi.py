from pathlib import Path
import pandas as pd

klasor = Path(__file__).resolve().parent

veri = pd.read_csv(
    klasor / "veri" / "normal.csv",
    sep=";",
    encoding="utf-8-sig",
)

veri["durum"] = (
    veri["durum"].str.strip().replace({"wking": "working"})
)

for makine, grup in veri.groupby("makine_id"):
    grup = grup.sort_values("baslangic_saniye").copy()

    # Durum her değiştiğinde yeni bir çalışma/bekleme dönemi başlar.
    grup["donem"] = grup["durum"].ne(grup["durum"].shift()).cumsum()

    donemler = grup.groupby("donem").agg(
        durum=("durum", "first"),
        baslangic=("baslangic_saniye", "first"),
        bitis=("bitis_saniye", "last"),
    )

    donemler["sure"] = donemler["bitis"] - donemler["baslangic"]

    # İlk ve son dönem kayıt sınırında kesilmiş olabilir.
    # Başlangıç beklemesini de normal ara beklemelerden ayırıyoruz.
    ara_donemler = donemler.iloc[1:-1]
    beklemeler = ara_donemler.loc[
        ara_donemler["durum"].eq("idle"), "sure"
    ]

    # Parça sayısının arttığı kayıtlar, tamamlanma anlarıdır.
    parca_artisi = grup["tamamlanan_parca"].diff()
    tamamlanmalar = grup.loc[parca_artisi.gt(0)].copy()

    # İki tamamlanma arasındaki gerçek süre.
    cevrimler = tamamlanmalar["bitis_saniye"].diff().dropna()

    # İki tamamlanma arasındaki aktif çalışma süresi.
    aktif_sureler = tamamlanmalar["calisma_saniye"].diff().dropna()

    print(f"\n--- {makine} ---")

    for ad, sureler in [
        ("Ara boşta kalma", beklemeler),
        ("Parçalar arası toplam süre", cevrimler),
        ("Parça başına aktif çalışma", aktif_sureler),
    ]:
        if sureler.empty:
            print(f"{ad}: Yeterli tamamlanmış dönem yok.")
        else:
            print(
                f"{ad}: "
                f"adet={len(sureler)}, "
                f"ortanca={sureler.median():.2f} sn, "
                f"en uzun={sureler.max():.2f} sn"
            )

    if parca_artisi.gt(1).any():
        print("Dikkat: Bazı kayıtlarda parça sayısı birden fazla artıyor.")

    if parca_artisi.lt(0).any():
        print("Dikkat: Parça sayacı sıfırlanmış; koşuları ayırmak gerekir.")