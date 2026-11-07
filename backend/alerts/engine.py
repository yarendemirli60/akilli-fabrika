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
"""
import logging
import os
import threading
from typing import Dict, List, Optional

from backend.alerts import rules

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
        return bool(measurements) and measurements[-1].status == "working"
    return True


def sync_machine(repo, machine) -> Dict:
    """Tek bir makine için kuralları çalıştırır ve alerts tablosunu günceller."""
    measurements = repo.get_measurements(machine_id=machine.id, limit=RULE_WINDOW)
    current = {a.alert_type: a for a in rules.evaluate_all(machine, measurements, repo.now())}
    open_alerts = {a.alert_type: a for a in repo.get_open_alerts(machine.id)}

    created, resolved = [], []
    for alert_type, alert in current.items():
        if alert_type not in open_alerts:
            repo.insert_alert(alert)
            created.append(alert_type)

    for alert_type, record in open_alerts.items():
        if (alert_type in ENGINE_ALERT_TYPES and alert_type not in current
                and _can_resolve(alert_type, measurements)):
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
