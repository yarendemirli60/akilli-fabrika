from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.alerts import engine, rules
from backend.repository import get_repository
from backend.schemas import Alert, AlertRecord

router = APIRouter(prefix="/alerts", tags=["Uyarılar"])


@router.get("", response_model=List[AlertRecord])
def list_alerts(
    machine_id: Optional[int] = Query(None, description="Sadece bu makinenin uyarıları"),
    active: Optional[bool] = Query(None, description="true: açık uyarılar, false: çözülmüş uyarılar"),
    limit: int = Query(100, ge=1, le=1000, description="En fazla kaç kayıt dönsün"),
    repo=Depends(get_repository),
):
    """Kayıtlı uyarılar, en yeniden eskiye. Web panelindeki uyarı listesi için."""
    if machine_id is not None and repo.get_machine(machine_id) is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return repo.list_alerts(machine_id=machine_id, active=active, limit=limit)


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
    measurements = repo.get_measurements(machine_id=machine_id, limit=engine.RULE_WINDOW)
    now = repo.now()
    alerts = rules.evaluate_all(machine, measurements, now)
    for a in alerts:
        a.created_at = now
    return alerts


@router.post("/check")
def check_now(
    machine_id: Optional[int] = Query(None, description="Boş bırakılırsa bütün makineler"),
    repo=Depends(get_repository),
):
    """
    Uyarı kontrolünü hemen çalıştırır (normalde arka planda otomatik çalışıyor).
    Yeni oluşan ve normale dönen uyarı türlerini döndürür.
    """
    if machine_id is not None and repo.get_machine(machine_id) is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return engine.run_once(repo, machine_id=machine_id)


@router.post("/{alert_id}/resolve", response_model=AlertRecord)
def resolve_alert(alert_id: int, repo=Depends(get_repository)):
    """
    Uyarıyı elle kapatır (operatör "gördüm, ilgileniyorum" dediğinde).
    Sorun devam ediyorsa motor bir sonraki kontrolde yeni bir uyarı açar.
    """
    alert = repo.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Uyarı bulunamadı")
    repo.resolve_alert(alert_id)
    return repo.get_alert(alert_id)
