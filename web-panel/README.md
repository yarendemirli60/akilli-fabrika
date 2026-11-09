# Canlı Web Paneli

Panel artık demo ölçüm üretmez; verileri backend /api uçlarından alır.

## Çalıştırma
1. backend/README.md içindeki MySQL, MQTT subscriber ve sim_agent kurulumunu tamamlayın.
2. Proje kökünde: uvicorn backend.main:app --reload
3. web-panel/index.html dosyasını Chrome/Edge ile açın veya bu klasörü yerel HTTP sunucusuyla sunun.
4. Varsayılan API: http://127.0.0.1:8000/api. Sayfa altındaki Backend bağlantısı bölümünden değiştirilebilir.

Panel üç saniyede bir API verilerini yeniler. Açılışta GET /runs/current ile devam eden çalışmaya bağlanır; otomatik başlatma POST'u göndermez. Başlat/durdur yalnızca düğmeyle backend'e iletilir. Bağlantı hatasında son başarılı değerler tutulur. Geçmiş seçiminde istekler seçilen runId'ye gider.

Chart.js yerel vendor klasöründedir. api-client.js önceki istemci yardımcı dosyasıdır; canlı ekran akışını live-panel.js yönetir.

## Backend sınırları ve doğrulama
- ai.score null geliyor; panel bunu — gösterir.
- Analiz zamanı olmayan normal sonuçta Analiz sonucu bekleniyor gösterilir; collecting sonucunda Veri birikiyor gösterilir. Backend analiz zamanı/skoru sağlamadıkça bunlar üretilmez.
- Karşılaştırmadaki stoppedSeconds alanı dakika olarak duruş grafiğine ve tabloya aktarılır. Eksik alan sıfır kabul edilmez.
- Gerçek MySQL/MQTT/AI zinciri bu bilgisayarda çalıştırılmadı. Gerçek veriyle uçtan uca deneme ve rapor ekran görüntüsü ekip ortamında alınmalıdır.
- Otomatik frontend kontrolü: API ile açılış, otomatik POST olmaması, bağlantı hatasında ölçüm koruma ve geçmiş çalışma kimliği.

Yapay zekâ yanlış alarmlarını panel düzeltmez veya gizlemez. Uyarı açma/kapama ve eşik düzenlemesi AI tarafındadır.
