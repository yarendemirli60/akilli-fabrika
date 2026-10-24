"""
MQTT PUBLISHER - Akilli Fabrika

simulasyon.py icindeki olcumu_yayinla() fonksiyonunu MQTT'ye baglar.
simulasyon.py dosyasinda HICBIR DEGISIKLIK gerekmez.

Kullanim (proje ana klasorunden):
    python mqtt/publisher.py
        -> canli simulasyonu calistirir, 3 makinenin verisini 10 Hz yayinlar
           (simulasyon komutlari: durum, durdur M2, ariza M3, onar M3, cikis)

    python mqtt/publisher.py --csv normal_veriler.csv --hiz 10
        -> CSV dosyasini 10 kat hizla yayinlar (--hiz 0: beklemeden en hizli)

Topic: factory/cnc/<makine_id>/telemetry   (ornek: factory/cnc/M1/telemetry)
"""

import argparse
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_SABLONU = "factory/cnc/{makine_id}/telemetry"

FLOAT_ALANLAR = (
    "baslangic_saniye", "bitis_saniye", "olcum_suresi_saniye", "guc_kw",
    "toplam_enerji_kwh", "calisma_saniye", "bosta_saniye",
)
INT_ALANLAR = ("tamamlanan_parca", "ariza_etiketi", "sequence_no")


def mqtt_baglan():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"akilli-fabrika-pub-{uuid.uuid4().hex[:8]}",
    )
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_disconnect(client, userdata, flags, reason_code, properties):
        print(f"[MQTT] Baglanti koptu ({reason_code}). Yeniden baglaniliyor...")

    client.on_disconnect = on_disconnect

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except OSError as hata:
        print(f"[HATA] MQTT broker'a baglanilamadi ({MQTT_HOST}:{MQTT_PORT}): {hata}")
        print("Mosquitto calisiyor mu? Yonetici CMD: net start mosquitto")
        sys.exit(1)

    client.loop_start()
    print(f"[MQTT] Baglandi: {MQTT_HOST}:{MQTT_PORT}")
    return client


def mesaj_olustur(olcum, sim_id, baslangic):
    """Simulasyon olcumune simulation_id ve timestamp ekler."""
    mesaj = dict(olcum)
    mesaj["simulation_id"] = sim_id
    zaman = baslangic + timedelta(seconds=float(olcum["bitis_saniye"]))
    mesaj["timestamp"] = zaman.isoformat(timespec="milliseconds")
    return mesaj


def gonder(client, mesaj):
    topic = TOPIC_SABLONU.format(makine_id=mesaj["makine_id"])
    client.publish(topic, json.dumps(mesaj, ensure_ascii=False), qos=1)


# ------------------------------------------------------------
# Mod 1: canli simulasyon
# ------------------------------------------------------------
def simulasyon_klasoru_bul():
    for ad in ("simulasyon", "simülasyon"):
        klasor = PROJE_KOKU / ad
        if (klasor / "simulasyon.py").exists():
            return klasor
    raise FileNotFoundError(
        "simulasyon.py bulunamadi. Klasor adi 'simulasyon' veya 'simülasyon' olmali."
    )


def canli_mod(client, sim_id):
    sys.path.insert(0, str(simulasyon_klasoru_bul()))
    import simulasyon  # noqa: E402  (yol yukarida eklendi)

    baslangic = datetime.now()

    def yayinla(olcum):
        gonder(client, mesaj_olustur(olcum, sim_id, baslangic))
        return olcum

    # simulasyon.py icindeki bos olcumu_yayinla() yerine bizimkini koy
    simulasyon.olcumu_yayinla = yayinla

    print(f"[PUBLISHER] Canli mod basladi. simulation_id = {sim_id}")
    simulasyon.main()


# ------------------------------------------------------------
# Mod 2: CSV tekrar oynatma
# ------------------------------------------------------------
def csv_satirini_cevir(satir, sayaclar):
    olcum = dict(satir)
    for alan in FLOAT_ALANLAR:
        olcum[alan] = float(satir[alan])
    for alan in INT_ALANLAR:
        if alan in satir and satir[alan] not in (None, ""):
            olcum[alan] = int(float(satir[alan]))

    # Eski CSV'lerde sequence_no yok: makine bazli kendimiz uretelim
    if "sequence_no" not in satir or satir["sequence_no"] in (None, ""):
        makine = olcum["makine_id"]
        sayaclar[makine] = sayaclar.get(makine, 0) + 1
        olcum["sequence_no"] = sayaclar[makine]
    return olcum


def csv_modu(client, sim_id, dosya, hiz, kodlama):
    baslangic = datetime.now()
    sayaclar = {}
    onceki_bitis = None
    adet = 0

    print(f"[PUBLISHER] CSV modu: {dosya} | hiz x{hiz} | simulation_id = {sim_id}")

    with open(dosya, newline="", encoding=kodlama) as f:
        for satir in csv.DictReader(f, delimiter=";"):
            olcum = csv_satirini_cevir(satir, sayaclar)

            if hiz > 0 and onceki_bitis is not None:
                fark = olcum["bitis_saniye"] - onceki_bitis
                if fark > 0:
                    time.sleep(fark / hiz)
            onceki_bitis = olcum["bitis_saniye"]

            gonder(client, mesaj_olustur(olcum, sim_id, baslangic))
            adet += 1
            if adet % 3000 == 0:
                print(f"[PUBLISHER] {adet} mesaj gonderildi")

    print(f"[PUBLISHER] CSV bitti. Toplam {adet} mesaj gonderildi.")


def main():
    parser = argparse.ArgumentParser(description="Akilli Fabrika MQTT publisher")
    parser.add_argument("--csv", help="Canli simulasyon yerine bu CSV dosyasini yayinla")
    parser.add_argument("--hiz", type=float, default=1.0,
                        help="CSV hiz carpani (1 = gercek zaman, 0 = beklemeden)")
    parser.add_argument("--kodlama", default="utf-8-sig",
                        help="CSV kodlamasi (hata alirsan: cp1254)")
    parser.add_argument("--sim-id", default=None,
                        help="Simulasyon kodu (bos birakilirsa otomatik uretilir)")
    args = parser.parse_args()

    sim_id = args.sim_id or datetime.now().strftime("SIM-%Y%m%d-%H%M%S")
    client = mqtt_baglan()

    try:
        if args.csv:
            csv_modu(client, sim_id, args.csv, args.hiz, args.kodlama)
        else:
            canli_mod(client, sim_id)
    except KeyboardInterrupt:
        print("\n[PUBLISHER] Durduruldu.")
    finally:
        time.sleep(0.5)  # bekleyen mesajlar gitsin
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
