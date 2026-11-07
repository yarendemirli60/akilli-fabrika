# Backend (FastAPI)

Makinelerin ölçüm, durum ve uyarı verilerini sunan REST API.

## Çalıştırma
Proje kök klasöründe, sanal ortam açıkken:

```
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

API dokümantasyonu: http://127.0.0.1:8000/docs

## Testler
```
python -m pytest testler -v
```

## Endpoint'ler

> Not: Veritabanı bağlantısı eklenene kadar endpoint'ler `sample_data.py` içindeki örnek veriyi döndürür. Yanıt formatı değişmeyecek.

| Metot | Adres | Açıklama |
|---|---|---|
| GET | `/health` | API çalışıyor mu |
| GET | `/machines` | Makine listesi |
| GET | `/machines/{id}` | Tek makine |
| GET | `/machines/{id}/latest` | Makinenin son ölçümü |
| GET | `/measurements?machine_id=1&limit=100` | Ölçümler (zamana göre sıralı) |
| GET | `/alerts/rules` | Tanımlı uyarı kuralları |
| GET | `/alerts/preview/{id}` | Kuralları makinenin ölçümlerinde çalıştırır |

Yanıtlardaki alan adları `veritabani/schema.sql` ile aynıdır.

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
