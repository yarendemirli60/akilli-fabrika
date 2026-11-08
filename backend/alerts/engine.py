"""
Uyarı motoru.

Kuralları (rules.py) belirli aralıklarla her makine için çalıştırır ve
sonucu alerts tablosuyla karşılaştırır:

  - Kural şu an tetikleniyor, açık kaydı yok  -> yeni uyarı eklenir
  - Kural şu an tetikleniyor, açık kaydı var  -> hiçbir şey yapılmaz
                                                  (aynı uyarı tekrar tekrar yazılmaz)
  - Kural artık tetiklenmiyor, açık kaydı var -> resolved_at doldurulur
                                                  (normale dönüş)

"Açık kayıt" = resolved_at değeri NULL olan uyarı.
Yapay zekânın yazdığı uyarılar ("AI|" ile başlayan mesajlar) hesaba katılmaz.
"""
import logging
import os
import threading
from typing import Dict, List, Optional

from backend import config
from backend.alerts import rules
from backend.alerts.mapping import is_ai_alert

logger = logging.getLogger("uvicorn.error")

# Kuralların bakacağı en fazla ölçüm sayısı (10 Hz'de ~2.5 dakika)
RULE_WINDOW = 1500

# Bu motorun kendisi değerlendirdiği için otomatik kapatabileceği uyarı türleri.
# (yuksek_enerji_parca analiz sonuçlarına bağlı, burada değerlendirilmiyor)
ENGINE_ALERT_TYPES = {"makine_durdu", "veri_yok", "yuksek_guc", "uzun_bosta"}


def _can_resolve(alert_type: str, measurements) -> bool:
    """
    Yüksek güç uyarısı sadece makine kesim yaparken kapatılabilir.
    Makine boştayken güç zaten düşük olduğu için takımın düzelip
    düzelmediği anlaşılamaz; bu durumda uyarı açık kalır.
    """
    if alert_type == "yuksek_guc":
        # Ortalamaya giren ölçümlerin hepsi kesim sırasında olmalı; aksi halde fazlar arası
        # geçişte boşta değerleri ortalamayı düşürür ve uyarı yanlışlıkla kapanır.
        window = measurements[-config.HIGH_POWER_MIN_READINGS:]
        return (len(window) == config.HIGH_POWER_MIN_READINGS
                and all(m.status == "working" for m in window))
    return True


def _run_has_ended(repo, measurements) -> bool:
    """Makinenin son ölçümü, bitmiş ya da kullanıcının durdurduğu bir çalışmaya mı ait?"""
    check = getattr(repo, "simulation_ended", None)
    return bool(measurements) and check is not None and check(measurements[-1].simulation_id)


def sync_machine(repo, machine) -> Dict:
    """Tek bir makine için kuralları çalıştırır ve alerts tablosunu günceller."""
    measurements = repo.get_measurements(machine_id=machine.id, limit=RULE_WINDOW)
    # Kurallar yalnızca makinenin son çalışmasına bakar; önceki çalışmanın ölçümleri
    # (örneğin boşta bitmiş bir simülasyon) yeni çalışmanın sürelerine karışmasın.
    if measurements:
        current_sim = measurements[-1].simulation_id
        measurements = [m for m in measurements if m.simulation_id == current_sim]
    # Duruma göre bastırma (ISA-18.2): çalışma bittiyse veri gelmemesi beklenen bir durumdur;
    # kurallar çalıştırılmaz ve açık kural uyarıları kapatılır.
    ended = _run_has_ended(repo, measurements)
    current = {} if ended else {
        a.alert_type: a for a in rules.evaluate_all(machine, measurements, repo.now())}
    # Yapay zekânın (ai/canli_analiz.py) açtığı uyarılara dokunulmaz; onları kendisi yönetiyor
    open_alerts = {a.alert_type: a for a in repo.get_open_alerts(machine.id)
                   if not is_ai_alert(a.message)}

    created, resolved = [], []
    for alert_type, alert in current.items():
        if alert_type not in open_alerts:
            repo.insert_alert(alert)
            created.append(alert_type)

    for alert_type, record in open_alerts.items():
        if (alert_type in ENGINE_ALERT_TYPES and alert_type not in current
                and (ended or _can_resolve(alert_type, measurements))):
            repo.resolve_alert(record.id)
            resolved.append(alert_type)

    for t in created:
        logger.info("[UYARI] %s: %s olustu", machine.machine_code, t)
    for t in resolved:
        logger.info("[UYARI] %s: %s normale dondu", machine.machine_code, t)

    return {"machine_id": machine.id, "created": created, "resolved": resolved}


def run_once(repo, machine_id: Optional[int] = None) -> List[Dict]:
    """Bütün makineler (ya da yalnızca verilen makine) için bir kontrol turu."""
    machines = repo.get_machines()
    if machine_id is not None:
        machines = [m for m in machines if m.id == machine_id]
    return [sync_machine(repo, m) for m in machines]


def run_forever(stop_event: threading.Event, repo_factory) -> None:
    """API açık olduğu sürece arka planda çalışan döngü."""
    interval = float(os.getenv("ALERT_CHECK_INTERVAL_S", "2"))
    logger.info("[UYARI] Uyari motoru basladi (her %.0f saniyede bir kontrol)", interval)
    while not stop_event.is_set():
        try:
            run_once(repo_factory())
        except Exception as exc:  # MySQL kapalıysa motor durmasın, sonraki turda tekrar denesin
            logger.warning("[UYARI] Kontrol turu basarisiz: %s", exc)
        stop_event.wait(interval)
