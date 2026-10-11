
import random
import time
import threading
from queue import Queue, Empty

from makine_ayarlari import (
    MAKINELER,
    FAZLAR,
    OLCUM_ARALIGI,
    NORMAL_KESME_GUCU,
    ARIZALI_KESME_GUCU,
)

SIMULASYON_MODU = "normal"

adim_ms = round(OLCUM_ARALIGI * 1000)

if adim_ms <= 0:
    raise ValueError("Olcum araligi sifirdan buyuk olmali.")


def kullanilan_faz_adi(faz_adi, zorunlu_ariza=False):
    if zorunlu_ariza and faz_adi in (
        "normal_kesme",
        "arizali_kesme",
    ):
        return "arizali_kesme"

    if SIMULASYON_MODU == "normal" and faz_adi == "arizali_kesme":
        return "normal_kesme"

    return faz_adi


def guc_hesapla(makine, faz_adi):
    if faz_adi == "normal_kesme":
        kesme_gucu = NORMAL_KESME_GUCU
        gurultu = makine["normal_gurultu"]

    elif faz_adi == "arizali_kesme":
        kesme_gucu = ARIZALI_KESME_GUCU
        gurultu = makine["arizali_gurultu"]

    else:
        kesme_gucu = 0.0
        gurultu = makine["bosta_gurultu"]

    dalgalanma = random.gauss(0, gurultu)

    guc = (
        makine["bosta_guc"]
        + kesme_gucu / makine["verim"]
        + dalgalanma
    )

    if guc < 0:
        raise ValueError(
            f'{makine["makine_id"]}: Negatif guc uretildi.'
        )

    return guc


# Her makinenin kendi durumunu olustur.
makine_durumlari = []

for makine in MAKINELER:
    durum = {
        "ayarlar": makine,
        "makine_id": makine["makine_id"],
        "makine_adi": makine["makine_adi"],
        "toplam_enerji_kwh": 0.0,
        "anlik_guc_kw": 0.0,
        "tamamlanan_parca": 0,
        "faz_index": 0,
        "fazda_gecen_ms": 0,
        "calisma_ms": 0,
        "bosta_ms": 0,
        "durdu": False,
        "zorunlu_ariza": False,
        "sequence_no": 0,
    }

    makine_durumlari.append(durum)


def olcum_olustur(
    durum,
    baslangic_ms,
    bitis_ms,
    ilerleme_ms,
    faz_adi,
    calisma_durumu,
    guc_kw,
):
    durum["sequence_no"] += 1

    return {
        "baslangic_saniye": baslangic_ms / 1000,
        "bitis_saniye": bitis_ms / 1000,
        "olcum_suresi_saniye": ilerleme_ms / 1000,
        "makine_id": durum["makine_id"],
        "makine_adi": durum["makine_adi"],
        "faz": faz_adi,
        "durum": calisma_durumu,
        "guc_kw": guc_kw,
        "toplam_enerji_kwh": durum["toplam_enerji_kwh"],
        "tamamlanan_parca": durum["tamamlanan_parca"],
        "calisma_saniye": durum["calisma_ms"] / 1000,
        "bosta_saniye": durum["bosta_ms"] / 1000,
        "ariza_etiketi": (
            1 if faz_adi == "arizali_kesme" else 0
        ),
        "sequence_no": durum["sequence_no"],
    }


def olcumu_yayinla(olcum):
    # MQTT baglantisini arkadasimiz burada ekleyecek.
    # Simdilik olcum sozluk olarak hazirlanir.
    return olcum


def makine_adimi(durum, zaman_ms):
    # Makine durdurulduysa uretim ve enerji ilerlemez.
    if durum["durdu"]:
        durum["anlik_guc_kw"] = 0.0

        olcum = olcum_olustur(
            durum,
            zaman_ms,
            zaman_ms + adim_ms,
            adim_ms,
            "durdu",
            "stopped",
            0.0,
        )

        olcumu_yayinla(olcum)
        return

    kalan_adim_ms = adim_ms
    islenen_ms = 0

    while kalan_adim_ms > 0:
        faz = FAZLAR[durum["faz_index"]]

        if faz["sure"] is None:
            faz_suresi = durum["ayarlar"]["kesme_suresi"]
        else:
            faz_suresi = faz["sure"]

        faz_suresi_ms = round(faz_suresi * 1000)

        fazda_kalan_ms = (
            faz_suresi_ms - durum["fazda_gecen_ms"]
        )

        ilerleme_ms = min(
            kalan_adim_ms,
            fazda_kalan_ms,
        )

        if ilerleme_ms <= 0:
            raise ValueError("Gecersiz faz suresi.")

        kayit_fazi = kullanilan_faz_adi(
            faz["ad"],
            durum["zorunlu_ariza"],
        )

        guc_kw = guc_hesapla(
            durum["ayarlar"],
            kayit_fazi,
        )

        durum["anlik_guc_kw"] = guc_kw

        gecen_saniye = ilerleme_ms / 1000
        eklenen_enerji = guc_kw * gecen_saniye / 3600

        durum["toplam_enerji_kwh"] += eklenen_enerji

        durum["fazda_gecen_ms"] += ilerleme_ms

        if faz["durum"] == "working":
            durum["calisma_ms"] += ilerleme_ms
        else:
            durum["bosta_ms"] += ilerleme_ms

        kalan_adim_ms -= ilerleme_ms
        islenen_ms += ilerleme_ms

        baslangic_ms = (
            zaman_ms + islenen_ms - ilerleme_ms
        )

        bitis_ms = zaman_ms + islenen_ms

        # Faz bittiyse siradaki faza gec.
        if durum["fazda_gecen_ms"] == faz_suresi_ms:
            durum["fazda_gecen_ms"] = 0
            durum["faz_index"] += 1

            olay_zamani = bitis_ms / 1000

            if durum["faz_index"] == len(FAZLAR):
                durum["tamamlanan_parca"] += 1
                durum["faz_index"] = 0

                print(
                    f'{olay_zamani:.2f} sn | '
                    f'{durum["makine_id"]} | '
                    f'Parca tamamlandi! '
                    f'Toplam: {durum["tamamlanan_parca"]}'
                )

            yeni_faz = FAZLAR[
                durum["faz_index"]
            ]["ad"]

            yeni_faz = kullanilan_faz_adi(
                yeni_faz,
                durum["zorunlu_ariza"],
            )

            print(
                f'{olay_zamani:.2f} sn | '
                f'{durum["makine_id"]} | '
                f'{yeni_faz}'
            )

        olcum = olcum_olustur(
            durum,
            baslangic_ms,
            bitis_ms,
            ilerleme_ms,
            kayit_fazi,
            faz["durum"],
            guc_kw,
        )

        olcumu_yayinla(olcum)


def durum_goster():
    print("\n--- MAKINE DURUMLARI ---")

    for durum in makine_durumlari:
        if durum["durdu"]:
            durum_yazisi = "DURDU"
        else:
            durum_yazisi = "CALISIYOR"

        faz_adi = FAZLAR[
            durum["faz_index"]
        ]["ad"]

        faz_adi = kullanilan_faz_adi(
            faz_adi,
            durum["zorunlu_ariza"],
        )

        if durum["durdu"]:
            faz_adi = "durdu"

        print(
            f'{durum["makine_id"]} | '
            f'{durum_yazisi} | '
            f'Faz: {faz_adi} | '
            f'Guc: {durum["anlik_guc_kw"]:.2f} kW | '
            f'Parca: {durum["tamamlanan_parca"]} | '
            f'Enerji: {durum["toplam_enerji_kwh"]:.5f} kWh'
        )

    print("------------------------\n")


def komutlari_oku(kuyruk):
    while True:
        try:
            komut = input()
        except EOFError:
            break

        kuyruk.put(komut.strip())


def komut_isle(komut):
    parcalar = komut.split()

    if not parcalar:
        return True

    islem = parcalar[0].lower()

    if islem == "cikis":
        return False

    if islem == "durum":
        durum_goster()
        return True

    if islem not in ("durdur", "baslat", "ariza", "onar"):
        print("Bilinmeyen komut.")
        return True

    if len(parcalar) != 2:
        print("Ornek kullanim: durdur M2")
        return True

    makine_id = parcalar[1].upper()

    hedef = next(
        (
            durum
            for durum in makine_durumlari
            if durum["makine_id"] == makine_id
        ),
        None,
    )

    if hedef is None:
        print("Makine bulunamadi.")
        return True

    if islem == "durdur":
        hedef["durdu"] = True
        hedef["anlik_guc_kw"] = 0.0
        print(f"{makine_id} durduruldu.")

    elif islem == "baslat":
        hedef["durdu"] = False
        print(f"{makine_id} yeniden baslatildi.")

    elif islem == "ariza":
        hedef["zorunlu_ariza"] = True
        print(
            f"{makine_id} icin ariza aktif. "
            "Kesme fazinda arizali guc kullanilacak."
        )

    elif islem == "onar":
        hedef["zorunlu_ariza"] = False
        print(f"{makine_id} arizasi kaldirildi.")

    return True


def main():
    print("CANLI CNC SIMULASYONU BASLADI")
    print(f"Simulasyon modu: {SIMULASYON_MODU}")
    print(f"Olcum araligi: {OLCUM_ARALIGI} saniye")

    print("\nKullanilabilir komutlar:")
    print("durum")
    print("durdur M2")
    print("baslat M2")
    print("ariza M3")
    print("onar M3")
    print("cikis\n")

    for durum in makine_durumlari:
        print(
            f'0.00 sn | {durum["makine_id"]} | '
            f'baslangic_bosta'
        )

    komut_kuyrugu = Queue()

    komut_thread = threading.Thread(
        target=komutlari_oku,
        args=(komut_kuyrugu,),
        daemon=True,
    )

    komut_thread.start()

    zaman_ms = 0
    sonraki_adim = time.monotonic()

    try:
        while True:
            # Terminalden gelen komutlari uygula.
            try:
                while True:
                    komut = komut_kuyrugu.get_nowait()

                    if not komut_isle(komut):
                        print("Simulasyon durduruldu.")
                        durum_goster()
                        return

            except Empty:
                pass

            # Uc makineyi bir olcum adimi ilerlet.
            for durum in makine_durumlari:
                makine_adimi(durum, zaman_ms)

            # Her 10 saniyede bir gucleri goster.
            if zaman_ms % 10000 == 0:
                print(
                    f"\n{zaman_ms / 1000:.2f} sn | "
                    "Guncel olcumler:"
                )

                durum_goster()

            zaman_ms += adim_ms

            # Simulasyon gercek zamanla ilerlesin.
            sonraki_adim += OLCUM_ARALIGI

            bekleme = sonraki_adim - time.monotonic()

            if bekleme > 0:
                time.sleep(bekleme)
            else:
                # Sistem gecikirse sonsuz telafi dongusu olusmasin.
                sonraki_adim = time.monotonic()

    except KeyboardInterrupt:
        print("\nSimulasyon kullanici tarafindan durduruldu.")
        durum_goster()


if __name__ == "__main__":
    main()
