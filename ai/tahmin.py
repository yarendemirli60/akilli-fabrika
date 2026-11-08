from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd

if __package__:
    from .sure_kontrol import SureKontrol
else:
    from sure_kontrol import SureKontrol


KLASOR = Path(__file__).resolve().parent


class AnomaliTespit:
    def __init__(self):
        paket = joblib.load(
            KLASOR / "modeller" / "guc_anomali_modeli.joblib"
        )

        self.modeller = paket["modeller"]
        self.ozellikler = paket["ozellikler"]

        # Her simülasyonun sayaçları ve uyarıları ayrı tutulur.
        self.oturumlar = {}

    def aktif_uyarilar(self, simulation_id=None):
        sonuc = []

        for sim_id, oturum in self.oturumlar.items():
            if simulation_id is not None and sim_id != simulation_id:
                continue

            sonuc.extend(
                dict(uyari)
                for uyari in oturum["aktif"].values()
            )

        return sonuc

    def degerlendir(self, olcum):
        olcum = dict(olcum)

        sim_id = str(olcum["simulation_id"])
        makine = str(olcum["makine_id"])
        sira = int(olcum["sequence_no"])

        durum = str(olcum["durum"]).strip()
        durum = "working" if durum == "wking" else durum
        olcum["durum"] = durum

        zaman = float(olcum["bitis_saniye"])
        guc = float(olcum["guc_kw"])

        if durum not in {"idle", "working", "stopped"}:
            raise ValueError(f"Bilinmeyen durum: {durum}")

        if not np.isfinite(guc) or guc < 0:
            raise ValueError("Geçersiz güç değeri.")

        if not np.isfinite(zaman) or sira < 1:
            raise ValueError("Geçersiz zaman veya sıra numarası.")

        anahtar = (makine, durum)

        if durum != "stopped" and anahtar not in self.modeller:
            raise ValueError(
                f"{makine} / {durum} için güç modeli yok."
            )

        if sim_id not in self.oturumlar:
            self.oturumlar[sim_id] = {
                "sure_kontrol": SureKontrol(),
                "aktif": {},
                "son_sira": {},
            }

        oturum = self.oturumlar[sim_id]
        son_sira = oturum["son_sira"].get(makine)

        # MQTT aynı mesajı yeniden gönderirse tekrar işleme.
        if son_sira is not None and sira <= son_sira:
            return {
                "simulation_id": sim_id,
                "makine_id": makine,
                "sequence_no": sira,
                "atlandi": True,
                "neden": "tekrar_veya_eski_olcum",
                "acilan_uyarilar": [],
                "kapanan_uyarilar": [],
                "aktif_uyarilar": [
                    dict(uyari)
                    for (kod, _), uyari in oturum["aktif"].items()
                    if kod == makine
                ],
            }

        # Eksik ölçüm varsa süre hesabını sessizce sürdürme.
        if son_sira is not None and sira != son_sira + 1:
            raise ValueError(
                f"{makine}: Ölçüm sırası eksik. "
                f"Beklenen: {son_sira + 1}, gelen: {sira}"
            )

        guc_anomalisi = None
        anomali_skoru = None

        if durum != "stopped":
            kayit = self.modeller[anahtar]

            girdiler = pd.DataFrame(
                [{"guc_kw": guc}],
                columns=self.ozellikler,
            )

            skor = float(
                kayit["model"].score_samples(girdiler)[0]
            )

            guc_anomalisi = bool(skor < kayit["esik"])
            anomali_skoru = float(kayit["esik"] - skor)

        sure_kontrol = oturum["sure_kontrol"]
        sure_bildirimleri = sure_kontrol.degerlendir(olcum)
        takip = sure_kontrol.makineler[makine]

        mevcut_sorunlar = set()
        anlik_sure_sorunlari = set()

        if durum != "stopped":
            if guc_anomalisi:
                mevcut_sorunlar.add("guc_anomalisi")

            if takip["bosta_uyarildi"]:
                mevcut_sorunlar.add("uzun_bosta")

            if takip["uretim_uyarildi"]:
                mevcut_sorunlar.add("yavas_uretim")

            # Parça tamamlandığı anda oluşan gecikmeyi de bildir.
            anlik_sure_sorunlari = {
                bildirim["uyari_turu"]
                for bildirim in sure_bildirimleri
            }

        acilanlar = []
        kapananlar = []
        aktif = oturum["aktif"]

        for tur in sorted(mevcut_sorunlar | anlik_sure_sorunlari):
            uyari_anahtari = (makine, tur)

            if uyari_anahtari in aktif:
                continue

            uyari = {
                "uyari_id": str(uuid4()),
                "simulation_id": sim_id,
                "makine_id": makine,
                "uyari_turu": tur,
                "seviye": "warning",
                "durum": "aktif",
                "baslangic_saniye": zaman,
                "bitis_saniye": None,
                "baslangic_timestamp": olcum.get("timestamp"),
                "bitis_timestamp": None,
                "kapanma_nedeni": None,
            }

            aktif[uyari_anahtari] = uyari
            acilanlar.append(dict(uyari))

        for uyari_anahtari in list(aktif):
            kod, tur = uyari_anahtari

            if kod != makine or tur in mevcut_sorunlar:
                continue

            uyari = aktif.pop(uyari_anahtari)

            uyari["durum"] = "kapandi"
            uyari["bitis_saniye"] = zaman
            uyari["bitis_timestamp"] = olcum.get("timestamp")

            if durum == "stopped":
                neden = "kullanici_durdurdu"
            elif tur == "yavas_uretim":
                neden = "parca_tamamlandi"
            elif tur == "uzun_bosta":
                neden = "bosta_donemi_bitti"
            else:
                neden = "guc_normal_araliga_dondu"

            uyari["kapanma_nedeni"] = neden
            kapananlar.append(dict(uyari))

        oturum["son_sira"][makine] = sira

        return {
            "simulation_id": sim_id,
            "makine_id": makine,
            "sequence_no": sira,
            "zaman_saniye": zaman,
            "durum": durum,
            "atlandi": False,
            "guc_kw": guc,
            "guc_degerlendirildi": durum != "stopped",
            "guc_anomalisi": guc_anomalisi,
            "anomali_skoru": anomali_skoru,
            "acilan_uyarilar": acilanlar,
            "kapanan_uyarilar": kapananlar,
            "aktif_uyarilar": [
                dict(uyari)
                for (kod, _), uyari in aktif.items()
                if kod == makine
            ],
        }


if __name__ == "__main__":
    tespit = AnomaliTespit()
    print("Güç modeli, süre kontrolü ve aktif uyarı yönetimi hazır.")