from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, confusion_matrix


KLASOR = Path(__file__).resolve().parent
MODEL_KLASORU = KLASOR / "modeller"
MODEL_KLASORU.mkdir(exist_ok=True)

# CSV dosyalarını oku.
normal = pd.read_csv(
    KLASOR / "veri" / "normal.csv",
    sep=";",
    encoding="utf-8-sig",
)

test = pd.read_csv(
    KLASOR / "veri" / "test.csv",
    sep=";",
    encoding="utf-8-sig",
)

# Yazım hatasını düzelt ve temel kontrolleri yap.
for veri in [normal, test]:
    veri["durum"] = (
        veri["durum"]
        .str.strip()
        .replace({"wking": "working"})
    )

    if veri[["makine_id", "durum", "guc_kw"]].isna().any().any():
        raise ValueError("Model için gereken sütunlarda eksik değer var.")

    if not np.isfinite(veri["guc_kw"]).all():
        raise ValueError("Güç sütununda geçersiz sayısal değer var.")

if not normal["ariza_etiketi"].eq(0).all():
    raise ValueError("Normal dosyada arızalı etiketli kayıt var.")

if not test["ariza_etiketi"].isin([0, 1]).all():
    raise ValueError("Test etiketleri yalnızca 0 veya 1 olmalı.")

# Her makine ve durum için modeli ve karar eşiğini sakla.
modeller = {}

for (makine, durum), grup in normal.groupby(["makine_id", "durum"]):
    grup = grup.sort_values("baslangic_saniye")

    if len(grup) < 100:
        raise ValueError(f"{makine} / {durum}: Yeterli normal veri yok.")

    # İlk %80 eğitim, son %20 normal doğrulama verisi.
    sinir = int(len(grup) * 0.80)

    egitim = grup.iloc[:sinir][["guc_kw"]]
    dogrulama = grup.iloc[sinir:][["guc_kw"]]

    model = IsolationForest(
        n_estimators=200,
        contamination="auto",
        random_state=42,
        n_jobs=-1,
    )

    model.fit(egitim)

    # Düşük skor, daha sıra dışı ölçüm demektir.
    # Eşiği test verisine bakmadan normal doğrulama verisinden seç.
    skorlar = model.score_samples(dogrulama)
    esik = float(np.quantile(skorlar, 0.01))

    modeller[(makine, durum)] = {
        "model": model,
        "esik": esik,
    }

    print(
        f"{makine} / {durum} hazır | "
        f"Eğitim: {len(egitim)} | "
        f"Doğrulama: {len(dogrulama)}"
    )

# Test dosyasını modellerle değerlendir.
test["tahmin"] = -1
test["anomali_skoru"] = np.nan

for (makine, durum), grup in test.groupby(["makine_id", "durum"]):
    anahtar = (makine, durum)

    if anahtar not in modeller:
        raise ValueError(f"{makine} / {durum} için eğitilmiş model yok.")

    kayit = modeller[anahtar]
    skorlar = kayit["model"].score_samples(grup[["guc_kw"]])

    test.loc[grup.index, "tahmin"] = (
        skorlar < kayit["esik"]
    ).astype(int)

    # Büyük değer daha fazla anormallik gösterir; olasılık değildir.
    test.loc[grup.index, "anomali_skoru"] = kayit["esik"] - skorlar

print("\nTEST SONUÇLARI")
print(
    classification_report(
        test["ariza_etiketi"],
        test["tahmin"],
        labels=[0, 1],
        target_names=["Normal", "Arızalı"],
        digits=4,
        zero_division=0,
    )
)

print("Karışıklık matrisi — satır: gerçek, sütun: tahmin")
print(
    confusion_matrix(
        test["ariza_etiketi"],
        test["tahmin"],
        labels=[0, 1],
    )
)

# Model ve ayarlarını birlikte kaydet.
joblib.dump(
    {
        "ozellikler": ["guc_kw"],
        "modeller": modeller,
        "esik_yontemi": "normal_dogrulama_yuzde_1",
    },
    MODEL_KLASORU / "guc_anomali_modeli.joblib",
)

test.to_csv(
    KLASOR / "test_sonuclari.csv",
    sep=";",
    index=False,
    encoding="utf-8-sig",
)

print("\nModel kaydedildi: ai/modeller/guc_anomali_modeli.joblib")
print("Test tahminleri kaydedildi: ai/test_sonuclari.csv")