"""
Web paneli için uçlar (web-panel/API-SOZLESMESI.md).
Panelde: FactoryAPI.configure({baseUrl: 'http://localhost:8000/api'})

Çalışma başlatma/durdurma (POST /runs, POST /runs/{id}/stop) publisher'ın
API'den kontrol edilmesini gerektirdiği için ayrıca eklenecek.
"""
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.panel_repository import POINT_ALERT_TYPES, PanelRepository, STATUS_MAP, counter_delta, stopped_seconds
from backend.panel_schemas import Comparison, PanelAlert, Run, SeriesPoint, Snapshot

router = APIRouter(prefix="/api", tags=["Web paneli"])


def get_panel_repository():
    if os.getenv("DATA_SOURCE", "mysql").lower() == "sample":
        raise HTTPException(status_code=503, detail="Web paneli uçları yalnızca MySQL ile çalışır.")
    return PanelRepository()


def _run_or_404(repo, run_id: str) -> dict:
    if not run_id.isdigit():
        raise HTTPException(status_code=404, detail="Çalışma bulunamadı")
    run = repo.get_run(int(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Çalışma bulunamadı")
    return run


def _machine_or_404(repo, machine_id: str) -> dict:
    machine = next((m for m in repo.machines() if str(m["id"]) == machine_id), None)
    if machine is None:
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    return machine


def _parse_time(value: Optional[str], name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} ISO 8601 tarih olmalı")


# ---------------- Çalışmalar ----------------

@router.get("/runs/current", response_model=Optional[Run])
def current_run(repo=Depends(get_panel_repository)):
    """Devam eden çalışma, yoksa null. Yalnızca okur; yeni çalışma açmaz."""
    return repo.current_run()


@router.get("/runs", response_model=List[Run])
def list_runs(
    from_: Optional[str] = Query(None, alias="from", description="Başlangıç tarihi (ISO 8601), bu tarihten sonra başlayanlar"),
    to: Optional[str] = Query(None, description="Bitiş tarihi (ISO 8601), bu tarihten önce başlayanlar"),
    scenarioId: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="running / completed"),
    repo=Depends(get_panel_repository),
):
    """Çalışmalar, en yeniden eskiye."""
    start, end = _parse_time(from_, "from"), _parse_time(to, "to")
    runs = repo.list_runs()
    return [r for r in runs
            if (start is None or (r["startedAt"] and r["startedAt"] >= start))
            and (end is None or (r["startedAt"] and r["startedAt"] <= end))
            and (scenarioId is None or r["scenarioId"] == scenarioId)
            and (status is None or r["status"] == status)]


@router.get("/runs/{run_id}/snapshot", response_model=Snapshot)
def snapshot(run_id: str, repo=Depends(get_panel_repository)):
    """Çalışmanın ve üç makinenin anlık durumu. Eksik ölçüm null döner."""
    run = _run_or_404(repo, run_id)
    open_ai = [a for a in repo.panel_alerts(with_elapsed=False)
               if a["source"] == "ai" and a["status"] == "active"
               and a["type"] == "ai_anomaly" and a["runId"] == run["runId"]]
    machines = []
    for m in repo.machines():
        row = repo.latest_in_run(int(run["runId"]), m["id"]) or {}
        delta = counter_delta(None, row) if row else {}
        anomaly = next((a for a in open_ai if a["machineId"] == str(m["id"])), None)
        machines.append({
            "id": str(m["id"]),
            "name": m["name"],
            "status": STATUS_MAP.get(row.get("status"), row.get("status")),
            "phase": row.get("phase"),
            "powerKw": row.get("power_kw"),
            "energyKwh": delta.get("energyKwh"),
            "productionCount": delta.get("productionCount"),
            "energyPerPartKwh": delta.get("energyPerPartKwh"),
            "runningSeconds": delta.get("runningSeconds"),
            "idleSeconds": delta.get("idleSeconds"),
            "stoppedSeconds": stopped_seconds(row) if row else None,
            "lastDataAt": row.get("ts"),
            "ai": {
                "result": "anomaly" if anomaly else "normal",
                "score": None,  # yapay zekâ skoru veritabanına yazmıyor
                "analyzedAt": anomaly["startedAt"] if anomaly else None,
            },
        })
    return {**run, "machines": machines}


@router.get("/runs/{run_id}/machines/{machine_id}/series", response_model=List[SeriesPoint])
def series(
    run_id: str,
    machine_id: str,
    from_: float = Query(0, alias="from", ge=0, description="Başlangıç (simülasyon saniyesi)"),
    to: Optional[float] = Query(None, ge=0, description="Bitiş (simülasyon saniyesi)"),
    step: float = Query(1.0, ge=0.1, le=60, description="Kaç saniyede bir nokta"),
    repo=Depends(get_panel_repository),
):
    """Grafik noktaları. Yatay eksen geçen simülasyon saniyesi."""
    run = _run_or_404(repo, run_id)
    _machine_or_404(repo, machine_id)
    rows = repo.series(int(run["runId"]), int(machine_id), from_, to, step)

    # Güç uyarılarının açık olduğu zaman aralıkları
    windows = [(a["startedAt"], a["closedAt"], a["id"])
               for a in repo.panel_alerts(machine_id=int(machine_id), with_elapsed=False)
               if a["runId"] == run["runId"] and a["type"] in POINT_ALERT_TYPES]

    points = []
    for r in rows:
        # Nokta, kapsadığı zaman diliminde açık olan bir güç uyarısıyla işaretlenir
        alert_id = next((wid for start, end, wid in windows
                         if start <= r["ts_end"] and (end is None or end >= r["ts_start"])), None)
        points.append({
            "elapsedSeconds": round(r["elapsed"], 3),
            "powerKw": round(r["power"], 3) if r["power"] is not None else None,
            "energyCounterKwh": r["energy"],
            "productionCount": r["parts"],
            "anomaly": alert_id is not None,
            "alertId": alert_id,
        })
    return points


@router.get("/runs/{run_id}/comparison", response_model=Comparison)
def comparison(
    run_id: str,
    from_: float = Query(0, alias="from", ge=0, description="Başlangıç (simülasyon saniyesi)"),
    to: Optional[float] = Query(None, ge=0, description="Bitiş (simülasyon saniyesi)"),
    repo=Depends(get_panel_repository),
):
    """Aynı aralıkta üç makinenin özeti (sayaç farkları; birikimli sayaçlar toplanmaz)."""
    run = _run_or_404(repo, run_id)
    rid = int(run["runId"])
    machines = []
    for m in repo.machines():
        start = repo.counters_at(rid, m["id"], from_) if from_ > 0 else None
        end = repo.counters_at(rid, m["id"], to)
        machines.append({
            "id": str(m["id"]),
            "name": m["name"],
            **counter_delta(start, end),
            "averagePowerKw": repo.average_power(rid, m["id"], from_, to),
        })
    return {"runId": run["runId"], "fromSeconds": from_, "toSeconds": to, "machines": machines}


# ---------------- Uyarılar ----------------

@router.get("/alerts", response_model=List[PanelAlert])
def panel_alerts(
    runId: Optional[str] = Query(None),
    machineId: Optional[str] = Query(None),
    type: Optional[str] = Query(None, description="unexpected_stop / no_data / long_idle / power_limit / energy_per_part_limit / ai_anomaly"),
    status: Optional[str] = Query(None, description="active / closed"),
    from_: Optional[str] = Query(None, alias="from", description="runId varsa simülasyon saniyesi, yoksa ISO 8601 tarih"),
    to: Optional[str] = Query(None, description="runId varsa simülasyon saniyesi, yoksa ISO 8601 tarih"),
    repo=Depends(get_panel_repository),
):
    """Kural ve yapay zekâ uyarıları tek listede, en yeniden eskiye. source alanı kaynağı gösterir."""
    if machineId is not None and not machineId.isdigit():
        raise HTTPException(status_code=404, detail="Makine bulunamadı")
    alerts = repo.panel_alerts(machine_id=int(machineId) if machineId else None)

    if runId is not None:
        alerts = [a for a in alerts if a["runId"] == runId]
        # Grafikle aynı from/to değerleri: simülasyon saniyesi
        try:
            lo = float(from_) if from_ else None
            hi = float(to) if to else None
        except ValueError:
            raise HTTPException(status_code=422, detail="runId verildiğinde from/to saniye olmalı")
        alerts = [a for a in alerts
                  if (lo is None or (a["elapsedSeconds"] is not None and a["elapsedSeconds"] >= lo))
                  and (hi is None or (a["elapsedSeconds"] is not None and a["elapsedSeconds"] <= hi))]
    else:
        lo, hi = _parse_time(from_, "from"), _parse_time(to, "to")
        alerts = [a for a in alerts
                  if (lo is None or a["startedAt"] >= lo) and (hi is None or a["startedAt"] <= hi)]

    return [a for a in alerts
            if (type is None or a["type"] == type) and (status is None or a["status"] == status)]
