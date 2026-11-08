from pathlib import Path
import pandas as pd


KLASOR = Path(__file__).resolve().parent

# Normal sürelerin üzerine %20 tolerans ekledik.
SINIRLAR = {
    "M1": {"bosta": 36.0, "uretim": 314.16 * 1.20},
    "M2": {"bosta": 36.0, "uretim": 314.16 * 1.20},
    "M3": {"bosta": 36.0, "uretim": 157.08 * 1.20},
}


class SureKontrol:
    def __init__(self):
        self.makineler = {}

    def degerlendir(self, olcum):
        makine = olcum["makine_id"]
        durum = str(olcum["durum"]).strip()
        durum = "working" if durum == "wking" else durum

        baslangic = float(olcum["baslangic_saniye"])
        bitis = float(olcum["bitis_saniye"])
        sure = float(olcum["olcum_suresi_saniye"])
        parca = int(olcum["tamamlanan_parca"])

        if makine not in SINIRLAR:
            raise ValueError(f"Bilinmeyen makine: {makine}")

        if durum not in {"idle", "working", "stopped"}:
            raise ValueError(f"Bilinmeyen durum: {durum}")

        if sure <= 0 or bitis <= baslangic:
            raise ValueError("Geçersiz ölçüm süresi.")

        if makine not in self.makineler:
            self.makineler[makine] = {
                "bosta": 0.0,
                "aktif": 0.0,
                "parca": parca,
                "son_bitis": baslangic,
                "bosta_uyarildi": False,
                "uretim_uyarildi": False,
                # Veri ortadan başlıyorsa ilk tamamlanmayı bekle.
                "uretim_takibi": abs(baslangic) < 0.001,
                "bosta_takibi": abs(baslangic) < 0.001,
            }

        takip = self.makineler[makine]

        # Eksik, yinelenmiş veya sırası bozulmuş ölçümleri gizleme.
        if abs(baslangic - takip["son_bitis"]) > 0.001:
            raise ValueError(
                f"{makine}: Ölçümler kesintisiz ve sıralı olmalı. "
                f"Beklenen başlangıç: {takip['son_bitis']}, "
                f"gelen: {baslangic}"
            )

        artis = parca - takip["parca"]

        if artis < 0 or artis > 1:
            raise ValueError(
                f"{makine}: Parça sayacı sıfırlanmış veya "
                "birden fazla artmış. Koşuları ayrı değerlendirin."
            )

        uyarilar = []

        def uyari_ekle(tur, gecen, sinir):
            uyarilar.append({
                "makine_id": makine,
                "zaman_saniye": bitis,
                "uyari_turu": tur,
                "gecen_sure_saniye": round(gecen, 3),
                "sinir_saniye": round(sinir, 3),
            })

        if durum == "idle":
            takip["bosta"] += sure

            if (
                takip["bosta_takibi"]
                and takip["bosta"] > SINIRLAR[makine]["bosta"] + 1e-6
                and not takip["bosta_uyarildi"]
            ):
                uyari_ekle(
                    "uzun_bosta",
                    takip["bosta"],
                    SINIRLAR[makine]["bosta"],
                )
                takip["bosta_uyarildi"] = True

        else:
            # Çalışma veya elle durdurma, idle dönemini bitirir.
            takip["bosta"] = 0.0
            takip["bosta_uyarildi"] = False
            takip["bosta_takibi"] = True

        if durum == "working":
            takip["aktif"] += sure

        # stopped sırasında aktif süre korunur ama ilerlemez.
        if (
            takip["uretim_takibi"]
            and takip["aktif"] > SINIRLAR[makine]["uretim"] + 1e-6
            and not takip["uretim_uyarildi"]
        ):
            uyari_ekle(
                "yavas_uretim",
                takip["aktif"],
                SINIRLAR[makine]["uretim"],
            )
            takip["uretim_uyarildi"] = True

        if artis == 1:
            takip["aktif"] = 0.0
            takip["uretim_uyarildi"] = False
            takip["uretim_takibi"] = True

        takip["parca"] = parca
        takip["son_bitis"] = bitis

        return uyarilar


def main():
    veri = pd.read_csv(
        KLASOR / "veri" / "test.csv",
        sep=";",
        encoding="utf-8-sig",
    )

    gerekli = [
        "makine_id",
        "durum",
        "baslangic_saniye",
        "bitis_saniye",
        "olcum_suresi_saniye",
        "tamamlanan_parca",
    ]

    if veri[gerekli].isna().any().any():
        raise ValueError("Gerekli sütunlarda eksik değer var.")

    # Her makinenin ölçümlerini zaman sırasına koy.
    veri = veri.sort_values(
        ["makine_id", "baslangic_saniye"],
        kind="stable",
    )

    kontrol = SureKontrol()
    uyarilar = []

    for olcum in veri.to_dict("records"):
        uyarilar.extend(kontrol.degerlendir(olcum))

    sonuc = pd.DataFrame(
        uyarilar,
        columns=[
            "makine_id",
            "zaman_saniye",
            "uyari_turu",
            "gecen_sure_saniye",
            "sinir_saniye",
        ],
    )

    sonuc.to_csv(
        KLASOR / "sure_uyarilari.csv",
        sep=";",
        index=False,
        encoding="utf-8-sig",
    )

    if sonuc.empty:
        print("Belirlenen süre sınırlarını aşan kayıt bulunamadı.")
    else:
        print("\nUYARI SAYILARI")
        print(sonuc.groupby(["makine_id", "uyari_turu"]).size())

        print("\nİLK 10 UYARI")
        print(sonuc.head(10).to_string(index=False))

    print("\nKaydedildi: ai/sure_uyarilari.csv")


if __name__ == "__main__":
    main()