import json
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import mysql.connector
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from tahmin import AnomaliTespit


PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

DB_AYARLARI = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "akilli_fabrika"),
    "charset": "utf8mb4",
    "autocommit": False,
    "connection_timeout": 5,
}

ACIKLAMALAR = {
    "guc_anomalisi": "Güç tüketimi normal aralığın dışında.",
    "uzun_bosta": "Kesintisiz boşta kalma süresi sınırı aşıldı.",
    "yavas_uretim": "Parça üretimi için aktif süre sınırı aşıldı.",
}

kuyruk = queue.Queue(maxsize=200000)
hata_var = threading.Event()
tespit = None


def zaman_cevir(deger):
    if not deger:
        raise ValueError("Ölçümde timestamp bulunamadı.")

    zaman = datetime.fromisoformat(str(deger))

    # Publisher mevcut sistemde yerel, saat dilimsiz zaman gönderiyor.
    if zaman.tzinfo is not None:
        raise ValueError(
            "Timestamp saat dilimli geldi; MySQL zaman dönüşümü "
            "aynı saat dilimi düzenine uyarlanmalı."
        )

    return zaman


class UyariVeritabani:
    def __init__(self):
        self.baglanti = None

    def baglan(self):
        if self.baglanti is not None:
            try:
                if self.baglanti.is_connected():
                    return
            except mysql.connector.Error:
                pass

            try:
                self.baglanti.close()
            except mysql.connector.Error:
                pass

        self.baglanti = mysql.connector.connect(**DB_AYARLARI)

    def geri_al(self):
        if self.baglanti is not None:
            try:
                self.baglanti.rollback()
            except mysql.connector.Error:
                pass

    def onceki_izlemeyi_kapat(self):
        # Önceki programdan kalan açık AI uyarıları:
        # "düzeldi" yerine izleme kesildi açıklamasıyla kapatılır.
        self.baglan()

        with self.baglanti.cursor() as imlec:
            imlec.execute(
                """
                UPDATE alerts
                SET resolved_at = CURRENT_TIMESTAMP(3),
                    message = LEFT(
                        CONCAT(
                            message,
                            ' | Izleme yeniden baslatildi; '
                            'onceki sorunun duzeldigi dogrulanmadi.'
                        ),
                        255
                    )
                WHERE resolved_at IS NULL
                  AND LEFT(message, 3) = 'AI|'
                """
            )

        self.baglanti.commit()

    def yaz(self, sonuc):
        acilanlar = sonuc["acilan_uyarilar"]
        kapananlar = sonuc["kapanan_uyarilar"]

        if not acilanlar and not kapananlar:
            return

        self.baglan()

        try:
            with self.baglanti.cursor() as imlec:
                imlec.execute(
                    "SELECT id FROM machines WHERE machine_code = %s",
                    (sonuc["makine_id"],),
                )

                makine = imlec.fetchone()

                if makine is None:
                    raise ValueError(
                        f"machines tablosunda "
                        f"{sonuc['makine_id']} bulunamadı."
                    )

                machine_id = makine[0]

                for uyari in acilanlar:
                    # Sabit kimlik sayesinde aynı işlemi yeniden
                    # denemek ikinci bir uyarı oluşturmaz.
                    isaret = f"AI|{uyari['uyari_id']}|"

                    imlec.execute(
                        """
                        SELECT id FROM alerts
                        WHERE machine_id = %s
                          AND LEFT(message, %s) = %s
                        LIMIT 1
                        """,
                        (machine_id, len(isaret), isaret),
                    )

                    if imlec.fetchone() is not None:
                        continue

                    aciklama = ACIKLAMALAR[uyari["uyari_turu"]]
                    mesaj = (
                        f"{isaret}"
                        f"Sim={uyari['simulation_id'][:50]} | "
                        f"{aciklama}"
                    )[:255]

                    imlec.execute(
                        """
                        INSERT INTO alerts
                            (machine_id, alert_type, severity,
                             message, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            machine_id,
                            uyari["uyari_turu"],
                            uyari["seviye"],
                            mesaj,
                            zaman_cevir(
                                uyari["baslangic_timestamp"]
                            ),
                        ),
                    )

                for uyari in kapananlar:
                    isaret = f"AI|{uyari['uyari_id']}|"

                    imlec.execute(
                        """
                        UPDATE alerts
                        SET resolved_at = %s,
                            message = LEFT(
                                CONCAT(message, ' | Kapanma: ', %s),
                                255
                            )
                        WHERE machine_id = %s
                          AND LEFT(message, %s) = %s
                          AND resolved_at IS NULL
                        """,
                        (
                            zaman_cevir(uyari["bitis_timestamp"]),
                            uyari["kapanma_nedeni"],
                            machine_id,
                            len(isaret),
                            isaret,
                        ),
                    )

            self.baglanti.commit()

        except Exception:
            self.geri_al()
            raise

    def kapat(self):
        if self.baglanti is not None:
            self.baglanti.close()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[AI MQTT] Bağlantı reddedildi: {reason_code}")
        return

    client.subscribe("factory/cnc/+/telemetry", qos=1)
    print("[AI MQTT] Ölçümler dinleniyor.")


def on_message(client, userdata, msg):
    try:
        olcum = json.loads(msg.payload)

        gerekli = [
            "simulation_id",
            "sequence_no",
            "timestamp",
            "makine_id",
            "durum",
            "guc_kw",
            "baslangic_saniye",
            "bitis_saniye",
            "olcum_suresi_saniye",
            "tamamlanan_parca",
        ]

        for alan in gerekli:
            if alan not in olcum:
                raise ValueError(f"Eksik alan: {alan}")

        zaman_cevir(olcum["timestamp"])
        kuyruk.put_nowait(olcum)

    except (ValueError, TypeError, KeyError, queue.Full) as hata:
        print(f"[AI HATA] Mesaj işlenemedi: {hata}")
        # Ölçüm atlayıp süre hesaplarına devam etme.
        hata_var.set()


def veritabanina_yaz(db, sonuc):
    while True:
        try:
            db.yaz(sonuc)
            return
        except mysql.connector.Error as hata:
            db.geri_al()
            print(f"[AI DB] Kayıt bekliyor, tekrar denenecek: {hata}")
            time.sleep(2)


def main():
    global tespit

    tespit = AnomaliTespit()
    db = UyariVeritabani()

    # Başlangıçta DB erişimini kontrol et.
    try:
        db.onceki_izlemeyi_kapat()
    except Exception:
        db.kapat()
        raise

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="akilli-fabrika-ai",
        clean_session=True,
    )

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()

        print("[AI] Model ve süre kontrolleri hazır.")
        print("[AI] Uyarılar mevcut MySQL'e kaydedilecek.")
        print("[AI] Durdurmak için Ctrl+C.")

        while not hata_var.is_set():
            try:
                olcum = kuyruk.get(timeout=0.2)
            except queue.Empty:
                continue

            sonuc = tespit.degerlendir(olcum)

            if sonuc["atlandi"]:
                continue

            # DB tekrar denense bile ölçüm yeniden analiz edilmez.
            veritabanina_yaz(db, sonuc)

            for uyari in sonuc["acilan_uyarilar"]:
                print(
                    f"[UYARI AÇILDI] {uyari['makine_id']} | "
                    f"{uyari['uyari_turu']}"
                )

            for uyari in sonuc["kapanan_uyarilar"]:
                print(
                    f"[UYARI KAPANDI] {uyari['makine_id']} | "
                    f"{uyari['uyari_turu']} | "
                    f"{uyari['kapanma_nedeni']}"
                )

    except KeyboardInterrupt:
        print("\n[AI] İzleme durduruldu.")

    except Exception as hata:
        print(f"[AI HATA] İzleme durdu: {hata}")
        print("MQTT publisher ve mevcut subscriber ayrı çalışmaya devam eder.")

    finally:
        client.disconnect()
        client.loop_stop()
        db.kapat()


if __name__ == "__main__":
    main()