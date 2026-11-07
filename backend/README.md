# Backend (FastAPI)

Makinelerin ölçüm, durum ve uyarı verilerini sunan REST API.

## Kurulum
1. MySQL'de `veritabani/schema.sql` dosyasını çalıştırın.
2. Proje kökünde `.env.example` dosyasını kopyalayıp adını `.env` yapın ve `DB_PASSWORD` satırına kendi MySQL şifrenizi yazın. API, `mqtt/subscriber.py` ile aynı `.env` ayarlarını kullanır.
3. Sanal ortam açıkken:

```
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

MySQL kurulu değilse API'yi örnek veriyle denemek için `.env` dosyasına `DATA_SOURCE=sample` satırını ekleyin.

API dokümantasyonu: http://127.0.0.1:8000/docs

## Testler
```
python -m pytest testler -v
```
`test_mysql_api.py` gerçek veritabanını kullanır; kendi test kayıtlarını ekler ve sonunda veritabanını eski haline getirir. MySQL'e bağlanılamazsa bu testler atlanır. Testleri çalıştırırken API (uvicorn) ve publisher kapalı olmalıdır.

## Endpoint'ler

| Metot | Adres | Açıklama |
|---|---|---|
| GET | `/health` | API çalışıyor mu |
| GET | `/health/db` | Veritabanı bağlantısı çalışıyor mu |
| GET | `/machines` | Makine listesi |
| GET | `/machines/{id}` | Tek makine |
| GET | `/machines/{id}/latest` | Makinenin son ölçümü |
| GET | `/measurements?machine_id=1&limit=100` | Ölçümler (zamana göre sıralı) |
| GET | `/alerts?machine_id=1&active=true&limit=100` | Kayıtlı uyarılar (en yeniden eskiye). `active=true` açık, `active=false` çözülmüş uyarılar |
| POST | `/alerts/check?machine_id=1` | Uyarı kontrolünü hemen çalıştırır, oluşan/kapanan uyarı türlerini döndürür |
| POST | `/alerts/{id}/resolve` | Uyarıyı elle kapatır |
| GET | `/alerts/rules` | Tanımlı uyarı kuralları |
| GET | `/alerts/preview/{id}` | Kuralları çalıştırır ama kaydetmez |

Yanıtlardaki alan adları `veritabani/schema.sql` ile aynıdır. Veritabanına bağlanılamazsa endpoint'ler `503` ve açıklayıcı bir mesaj döner.

## Web paneli uçları (`/api`)

`web-panel/API-SOZLESMESI.md` sözleşmesine göre yazıldı. Panelde:
`FactoryAPI.configure({baseUrl: 'http://localhost:8000/api'})`

| Metot | Adres | Açıklama |
|---|---|---|
| GET | `/api/runs/current` | Devam eden çalışma, yoksa `null` |
| GET | `/api/runs?from=&to=&scenarioId=&status=` | Çalışmalar (en yeniden eskiye) |
| GET | `/api/runs/{id}/snapshot` | Çalışma ve üç makinenin anlık durumu |
| GET | `/api/runs/{id}/machines/{machineId}/series?from=0&to=900&step=1` | Grafik noktaları (yatay eksen simülasyon saniyesi) |
| GET | `/api/runs/{id}/comparison?from=0&to=900` | Aralıkta üç makinenin özeti (sayaç farkları) |
| GET | `/api/alerts?runId=&machineId=&type=&status=&from=&to=` | Kural ve yapay zekâ uyarıları tek listede |

Notlar:
- "Çalışma" (run) = `simulations` tablosundaki bir simülasyon. Subscriber bitişi kaydetmediği için 30 saniyedir ölçüm gelmeyen çalışma `completed` sayılır.
- Uyarı türleri: `makine_durdu → unexpected_stop`, `veri_yok → no_data`, `uzun_bosta → long_idle`, `yuksek_guc → power_limit`, `yuksek_enerji_parca → energy_per_part_limit`; yapay zekâdan `guc_anomalisi` ve `yavas_uretim → ai_anomaly`, `uzun_bosta → long_idle`. `source` alanı `rule` ya da `ai`.
- Yapay zekâ uyarılarını `ai/canli_analiz.py` yazar (mesajı `AI|` ile başlar); backend uyarı motoru bunlara dokunmaz.
- Yapay zekâ skoru veritabanına yazılmadığı için `ai.score` şimdilik `null`.
- `/api/alerts` için `runId` verilirse `from`/`to` simülasyon saniyesidir, verilmezse ISO 8601 tarihtir.
- Çalışma başlatma/durdurma (`POST /api/runs`, `POST /api/runs/{id}/stop`) henüz yok.

## Uyarı kuralları

| alert_type | Önem | Koşul |
|---|---|---|
| `makine_durdu` | critical | Son 3 ölçümde durum `stopped` veya güç < boşta gücün %20'si |
| `veri_yok` | warning | 10 saniyeden uzun süre ölçüm gelmemesi |
| `yuksek_guc` | warning | Son 10 ölçümün ortalaması > P_boşta + P_c/η + 3σ |
| `uzun_bosta` | info | 60 saniyeden uzun kesintisiz boşta kalma |
| `yuksek_enerji_parca` | warning | Parça başı enerji, makineye özel sınırı aşarsa |

Yüksek güç eşikleri (şartname Tablo 1 ve 2):

| Makine | Normal kesme gücü | Uyarı eşiği |
|---|---|---|
| M1 – 15 Yıllık Torna | 19.20 kW | 21.00 kW |
| M2 – Eco CNC | 13.90 kW | 14.29 kW |
| M3 – Çift Aynalı CNC | 17.60 kW | 18.65 kW |

Eşikler ve süreler `backend/config.py` içinden değiştirilebilir.

## Uyarı motoru

API açıkken arka planda her 2 saniyede bir bütün makineler için kurallar çalıştırılır ve sonuç `alerts` tablosuna işlenir:

- Kural tetiklendi, açık kaydı yok → yeni uyarı eklenir
- Kural hâlâ tetikleniyor → aynı uyarı tekrar yazılmaz
- Kural artık tetiklenmiyor → uyarının `resolved_at` alanı doldurulur (normale dönüş)

Oluşan ve kapanan uyarılar uvicorn terminalinde `[UYARI]` satırlarıyla görünür.

`.env` ile ayarlanabilir:

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| `ALERT_ENGINE` | `on` | `off` yazılırsa motor çalışmaz |
| `ALERT_CHECK_INTERVAL_S` | `2` | Kontrol aralığı (saniye) |

