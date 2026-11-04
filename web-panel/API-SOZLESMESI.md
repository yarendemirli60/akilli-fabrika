# Backend bağlantısı — önerilen veri sözleşmesi

Bu belge frontend önerisidir; mevcut bir backend API'si olduğu anlamına gelmez.
Panel şu anda DEMO modundadır. api-client.js istekleri hazırlıdır; veri eşleme ve canlı entegrasyon backend geldiğinde tamamlanacaktır.

## Kurulum
FactoryAPI.configure({baseUrl:'http://localhost:8000/api'})
Ayrı alan adında çalışan backend frontend origin'ine CORS izni vermelidir.
API anahtarı gerekiyorsa kaynak koduna gömülmemelidir.

## Önerilen uçlar
- GET /runs/current → devam eden çalışma veya null. Sayfa yenilenirken yalnızca okunur; POST ile yeni çalışma açılmaz.
- POST /runs {scenarioId} → yeni çalışma. Devam eden çalışma varsa 409.
- POST /runs/{id}/stop → sonuçları koruyarak kullanıcı durdurması. Arıza uyarısı açmaz.
- GET /runs?from=&to=&scenarioId=&status= → geçmiş çalışmalar.
- GET /runs/{id}/snapshot → çalışma, makine ölçümleri ve bağlantı bilgileri.
- GET /runs/{id}/machines/{machineId}/series?from=0&to=900 → grafik noktaları.
- GET /runs/{id}/comparison?from=0&to=900 → aynı aralık için üç makinenin özetleri.
- GET /alerts?runId=&machineId=&type=&status=&from=&to= → uyarılar.

## Örnek snapshot
```json
{
  "runId":"024",
  "scenarioId":"normal",
  "status":"running",
  "startedAt":"2026-11-01T10:00:00Z",
  "endedAt":null,
  "elapsedSeconds":900,
  "lastDataAt":"2026-11-01T10:15:00Z",
  "machines":[{
    "id":"1",
    "name":"Makine 1",
    "status":"running",
    "phase":"processing",
    "powerKw":8,
    "energyKwh":1.8,
    "productionCount":45,
    "energyPerPartKwh":0.04,
    "runningSeconds":700,
    "idleSeconds":150,
    "stoppedSeconds":50,
    "ai":{"result":"normal","score":0.12,"analyzedAt":"2026-11-01T10:15:00Z"}
  }]
}
```
Gerçek cevap üç makineyi içermelidir. Eksik ölçüm null olmalıdır, sıfırla değiştirilmemelidir.

## Grafik noktası
```json
{"elapsedSeconds":120,"powerKw":8,"energyCounterKwh":0.26,"productionCount":6,"anomaly":false,"alertId":null}
```
Üretim noktaları basamaklı çizilir. Anomali noktasının alertId değeri ayrıntıyı açar.
Grafik yatay ekseni geçen simülasyon saniyesi; kayıt zamanları ISO 8601 gerçek zamanıdır.

## Karşılaştırma
Backend başlangıç ve bitiş sayaç farkını kullanır. Birikimli sayaçlar toplanmaz.
energyKwh=endCounter-startCounter; productionCount=endCount-startCount.
energyPerPartKwh=productionCount>0?energyKwh/productionCount:null.
Backend hesaplanmış değerleri frontend'e döndürür.

## Durumlar
Çalışma: running/completed/user_stopped/error.
Makine: running/idle/stopped.
Yapay zekâ: normal/anomaly/collecting. Skor olasılık yüzdesi değildir.
Uyarı türleri: unexpected_stop/no_data/long_idle/power_limit/energy_per_part_limit/ai_anomaly.
Uyarı: id,runId,machineId,type,description,source(rule/ai),startedAt,closedAt,status(active/closed).
Aynı sorun için tek kalıcı ID korunur; açma ve kapama backend sorumluluğundadır.

## Entegrasyon kabul kontrolleri
1. Mevcut çalışma GET ile bulunur; yenileme yeni çalışma oluşturmaz.
2. Anlık snapshot düzenli alınır; bağlantı kesilince son başarılı ölçümler korunur.
3. Geçmiş çalışmanın ID'si tüm veri isteklerine aktarılır; canlı snapshot geçmişi değiştirmez.
4. Başlat/durdur hatasında durum başarı gibi değiştirilmez, açıklayıcı hata gösterilir.
5. Filtreler grafik ve tabloya aynı runId/from/to değerlerini gönderir.
6. Gerçek model sonuçları ve uyarı ID'leri ile entegrasyon testi yapılır.
