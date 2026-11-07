from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.alerts import rules
from backend.repository import get_repository
from backend.schemas import Alert

router = APIRouter(prefix="/alerts", tags=["Uyarılar"])

# Kuralların bakacağı en fazla ölçüm sayısı (10 Hz'de ~2 dakika)
RULE_WINDOW = 1500


@router.get("/rules")
def list_rules():
    """Tanımlı uyarı kuralları ve koşulları."""
    return rules.RULE_DEFINITIONS


@router.get("/preview/{machine_id}", response_model=List[Alert])
def preview_alerts(machine_id: int, repo=Depends(get_repository)):
    """
    Kuralları seçilen makinenin son ölçümleri üzerinde çalıştırır.
    Sonuçları sadece döndürür, alerts tablosuna yazmaz.
    """
    machine = repo.get_machine(machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    measurements = repo.get_measurements(machine_id=machine_id, limit=RULE_WINDOW)
    now = repo.now()
    alerts = rules.evaluate_all(machine, measurements, now)
    for a in alerts:
        a.created_at = now
    return alerts
