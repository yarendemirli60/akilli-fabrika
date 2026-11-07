from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException

from backend import sample_data
from backend.alerts import rules
from backend.schemas import Alert

router = APIRouter(prefix="/alerts", tags=["Uyarılar"])


@router.get("/rules")
def list_rules():
    """Tanımlı uyarı kuralları ve koşulları."""
    return rules.RULE_DEFINITIONS


@router.get("/preview/{machine_id}", response_model=List[Alert])
def preview_alerts(machine_id: int):
    """
    Kuralları seçilen makinenin ölçümleri üzerinde çalıştırır.
    Sonuçları sadece döndürür, alerts tablosuna yazmaz.
    """
    machine = sample_data.get_machine(machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    measurements = sample_data.get_measurements(machine_id=machine_id, limit=5000)
    # Örnek veri geçmiş bir zamana ait; 'şimdi'yi son ölçüm anı kabul ediyoruz
    now = measurements[-1].ts if measurements else datetime.now()
    alerts = rules.evaluate_all(machine, measurements, now)
    for a in alerts:
        a.created_at = now
    return alerts
