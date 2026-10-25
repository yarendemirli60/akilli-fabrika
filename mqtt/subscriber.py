"""
MQTT SUBSCRIBER - Akilli Fabrika

factory/cnc/+/telemetry topic'ini dinler, gelen olcumleri dogrular
ve MySQL'deki measurements tablosuna toplu (batch) olarak yazar.

Kullanim (proje ana klasorunden):
    python mqtt/subscriber.py

Ozellikler:
  - Negatif guc (< 0 kW) sensor arizasi sayilir, reddedilir
  - Tekrar eden kayit (ayni simulasyon + makine + sira no) ikinci kez yazilmaz
  - MQTT kopunca otomatik yeniden baglanir ve tekrar abone olur
  - MySQL kopunca batch'i kaybetmeden yeniden dener
  - Kalici oturum (QoS 1): subscriber kapaliyken gelen mesajlar broker'da bekler
"""

import json
import os
import queue
import sys
import time
from datetime import datetime
from pathlib import Path

import mysql.connector
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = "factory/cnc/+/telemetry"
MQTT_CLIENT_ID = "akilli-fabrika-subscriber"

DB_AYARLARI = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "akilli_fabrika"),
    "charset": "utf8mb4",
    "autocommit": False,
}

BATCH_BOYUTU = 100       # bu kadar mesaj birikince yaz
BATCH_SURESI = 1.0       # veya en gec bu kadar saniyede bir yaz
RAPOR_ARALIGI = 10.0     # istatistik yazdirma araligi (sn)

GEREKLI_ALANLAR = ("simulation_id", "timestamp", "makine_id", "sequence_no", "guc_kw")

EKLE_SQL = """
INSERT INTO measurements
  (simulation_id, machine_id, seq, ts, start_s, end_s, duration_s,
   phase, status, power_kw, energy_kwh, completed_parts, work_s, idle_s, fault_label)
VALUES
  (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE id = id
"""

istatistik = {"kaydedilen": 0, "tekrar": 0, "reddedilen": 0}
kuyruk = queue.Queue(maxsize=200000)


# ------------------------------------------------------------
# Dogrulama
# ------------------------------------------------------------
def dogrula(veri):
    """Gelen JSON'u kontrol eder. Gecersizse ValueError firlatir."""
    for alan in GEREKLI_ALANLAR:
        if alan not in veri:
            raise ValueError(f"eksik alan: {alan}")

    guc = float(veri["guc_kw"])
    if guc < 0:
        raise ValueError(f"negatif guc ({guc} kW) - sensor arizasi")

    return {
        "simulation_code": str(veri["simulation_id"]),
        "machine_code": str(veri["makine_id"]),
        "machine_name": str(veri.get("makine_adi") or veri["makine_id"]),
        "seq": int(veri["sequence_no"]),
        "ts": datetime.fromisoformat(str(veri["timestamp"])),
        "start_s": veri.get("baslangic_saniye"),
        "end_s": veri.get("bitis_saniye"),
        "duration_s": veri.get("olcum_suresi_saniye"),
        "phase": veri.get("faz"),
        "status": veri.get("durum"),
        "power_kw": guc,
        "energy_kwh": veri.get("toplam_enerji_kwh"),
        "completed_parts": veri.get("tamamlanan_parca"),
        "work_s": veri.get("calisma_saniye"),
        "idle_s": veri.get("bosta_saniye"),
        "fault_label": veri.get("ariza_etiketi"),
    }


# ------------------------------------------------------------
# Veritabani
# ------------------------------------------------------------
class Veritabani:
    def __init__(self):
        self.baglanti = None
        self.makineler = {}      # machine_code -> id
        self.simulasyonlar = {}  # simulation_code -> id

    def hazirla(self):
        """Baglanti yoksa kurar, kopmussa yeniden baglar."""
        if self.baglanti is not None:
            try:
                self.baglanti.ping(reconnect=True, attempts=3, delay=1)
                return
            except mysql.connector.Error:
                pass
        self.baglanti = mysql.connector.connect(**DB_AYARLARI)

    def makine_id(self, kod, ad):
        if kod not in self.makineler:
            imlec = self.baglanti.cursor()
            imlec.execute(
                "INSERT IGNORE INTO machines (machine_code, name) VALUES (%s, %s)",
                (kod, ad),
            )
            imlec.execute("SELECT id FROM machines WHERE machine_code = %s", (kod,))
            self.makineler[kod] = imlec.fetchone()[0]
            self.baglanti.commit()
            imlec.close()
        return self.makineler[kod]

    def simulasyon_id(self, kod, baslangic):
        if kod not in self.simulasyonlar:
            imlec = self.baglanti.cursor()
            imlec.execute(
                "INSERT IGNORE INTO simulations (simulation_code, started_at) VALUES (%s, %s)",
                (kod, baslangic),
            )
            imlec.execute("SELECT id FROM simulations WHERE simulation_code = %s", (kod,))
            self.simulasyonlar[kod] = imlec.fetchone()[0]
            self.baglanti.commit()
            imlec.close()
        return self.simulasyonlar[kod]

    def satira_cevir(self, k):
        return (
            self.simulasyon_id(k["simulation_code"], k["ts"]),
            self.makine_id(k["machine_code"], k["machine_name"]),
            k["seq"], k["ts"], k["start_s"], k["end_s"], k["duration_s"],
            k["phase"], k["status"], k["power_kw"], k["energy_kwh"],
            k["completed_parts"], k["work_s"], k["idle_s"], k["fault_label"],
        )

    def toplu_yaz(self, paket):
        """Paketi yazar. Basarili olursa True doner. Baglanti hatasinda hata firlatir."""
        satirlar = [self.satira_cevir(k) for k in paket]
        imlec = self.baglanti.cursor()
        imlec.executemany(EKLE_SQL, satirlar)
        yeni = imlec.rowcount if imlec.rowcount is not None and imlec.rowcount >= 0 else len(satirlar)
        self.baglanti.commit()
        imlec.close()

        istatistik["kaydedilen"] += yeni
        istatistik["tekrar"] += max(0, len(satirlar) - yeni)

    def tek_tek_yaz(self, paket):
        """Toplu yazma veri hatasi verirse, bozuk satirlari ayiklamak icin."""
        for k in paket:
            try:
                self.toplu_yaz([k])
            except mysql.connector.Error as hata:
                self.baglanti.rollback()
                istatistik["reddedilen"] += 1
                print(f"[DB] Satir reddedildi (seq={k['seq']}): {hata}")


def paketi_yaz(db, paket):
    """Basarili olursa [] doner; baglanti sorunu varsa paketi geri verir (tekrar denenecek)."""
    try:
        db.hazirla()
        db.toplu_yaz(paket)
        return []
    except (mysql.connector.OperationalError, mysql.connector.InterfaceError) as hata:
        print(f"[DB] Baglanti sorunu: {hata}. 2 sn sonra tekrar denenecek...")
        time.sleep(2)
        return paket
    except mysql.connector.Error as hata:
        print(f"[DB] Toplu yazma hatasi: {hata}. Satir satir deneniyor...")
        try:
            db.baglanti.rollback()
        except mysql.connector.Error:
            pass
        db.tek_tek_yaz(paket)
        return []


# ------------------------------------------------------------
# MQTT
# ------------------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[MQTT] Baglanti reddedildi: {reason_code}")
        return
    client.subscribe(MQTT_TOPIC, qos=1)  # yeniden baglanmada da tekrar abone olur
    print(f"[MQTT] Baglandi ve abone olundu: {MQTT_TOPIC}")


def on_disconnect(client, userdata, flags, reason_code, properties):
    print(f"[MQTT] Baglanti koptu ({reason_code}). Yeniden baglaniliyor...")


def on_message(client, userdata, msg):
    try:
        veri = json.loads(msg.payload)
        kayit = dogrula(veri)
        kuyruk.put_nowait(kayit)
    except queue.Full:
        istatistik["reddedilen"] += 1
        print("[UYARI] Kuyruk dolu, mesaj atlandi.")
    except (ValueError, TypeError, KeyError) as hata:
        istatistik["reddedilen"] += 1
        print(f"[RED] {msg.topic}: {hata}")


def main():
    db = Veritabani()
    try:
        db.hazirla()
        print(f"[DB] Baglandi: {DB_AYARLARI['host']}:{DB_AYARLARI['port']}/{DB_AYARLARI['database']}")
    except mysql.connector.Error as hata:
        print(f"[HATA] MySQL'e baglanilamadi: {hata}")
        print(".env dosyasindaki DB_USER / DB_PASSWORD / DB_NAME degerlerini ve schema.sql'in calistirildigini kontrol et.")
        sys.exit(1)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        clean_session=False,  # kalici oturum: subscriber kapaliyken gelen QoS 1 mesajlar beklesin
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except OSError as hata:
        print(f"[HATA] MQTT broker'a baglanilamadi ({MQTT_HOST}:{MQTT_PORT}): {hata}")
        print("Mosquitto calisiyor mu? Yonetici CMD: net start mosquitto")
        sys.exit(1)

    client.loop_start()
    print("[SUBSCRIBER] Calisiyor. Durdurmak icin Ctrl+C.")

    paket = []
    son_yazim = time.monotonic()
    son_rapor = time.monotonic()

    try:
        while True:
            try:
                paket.append(kuyruk.get(timeout=0.2))
            except queue.Empty:
                pass

            simdi = time.monotonic()
            if paket and (len(paket) >= BATCH_BOYUTU or simdi - son_yazim >= BATCH_SURESI):
                paket = paketi_yaz(db, paket)
                son_yazim = time.monotonic()

            if simdi - son_rapor >= RAPOR_ARALIGI:
                print(
                    f"[RAPOR] Kaydedilen: {istatistik['kaydedilen']} | "
                    f"Tekrar: {istatistik['tekrar']} | "
                    f"Reddedilen: {istatistik['reddedilen']} | "
                    f"Kuyrukta: {kuyruk.qsize() + len(paket)}"
                )
                son_rapor = simdi

    except KeyboardInterrupt:
        print("\n[SUBSCRIBER] Durduruluyor, kalan kayitlar yaziliyor...")
    finally:
        client.loop_stop()
        client.disconnect()
        while not kuyruk.empty():
            paket.append(kuyruk.get_nowait())
        if paket:
            paketi_yaz(db, paket)
        print(
            f"[SUBSCRIBER] Bitti. Kaydedilen: {istatistik['kaydedilen']} | "
            f"Tekrar: {istatistik['tekrar']} | Reddedilen: {istatistik['reddedilen']}"
        )


if __name__ == "__main__":
    main()
