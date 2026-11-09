"""
Web paneli sözleşmesindeki (web-panel/API-SOZLESMESI.md) yanıt modelleri.
Alan adları sözleşmeyle aynı olsun diye camelCase yazıldı.
Kimlikler (runId, machineId, id) sözleşmedeki örneklerdeki gibi metin olarak dönüyor.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class Run(BaseModel):
    runId: str
    simulationCode: str
    scenarioId: Optional[str] = None
    status: str                      # running / completed / user_stopped / error
    startedAt: Optional[datetime] = None
    endedAt: Optional[datetime] = None
    elapsedSeconds: Optional[float] = None
    lastDataAt: Optional[datetime] = None


class AiInfo(BaseModel):
    result: str                      # normal / anomaly / collecting
    score: Optional[float] = None    # olasılık yüzdesi değildir
    analyzedAt: Optional[datetime] = None


class MachineSnapshot(BaseModel):
    id: str
    name: str
    status: Optional[str] = None     # running / idle / stopped
    phase: Optional[str] = None
    powerKw: Optional[float] = None
    energyKwh: Optional[float] = None
    productionCount: Optional[int] = None
    energyPerPartKwh: Optional[float] = None
    runningSeconds: Optional[float] = None
    idleSeconds: Optional[float] = None
    stoppedSeconds: Optional[float] = None
    lastDataAt: Optional[datetime] = None
    ai: AiInfo


class Snapshot(Run):
    machines: List[MachineSnapshot]


class SeriesPoint(BaseModel):
    elapsedSeconds: float
    powerKw: Optional[float] = None
    energyCounterKwh: Optional[float] = None
    productionCount: Optional[int] = None
    anomaly: bool = False
    alertId: Optional[str] = None


class MachineComparison(BaseModel):
    id: str
    name: str
    energyKwh: Optional[float] = None
    productionCount: Optional[int] = None
    energyPerPartKwh: Optional[float] = None
    averagePowerKw: Optional[float] = None
    runningSeconds: Optional[float] = None
    idleSeconds: Optional[float] = None
    stoppedSeconds: Optional[float] = None


class Comparison(BaseModel):
    runId: str
    fromSeconds: float
    toSeconds: Optional[float] = None
    machines: List[MachineComparison]


class PanelAlert(BaseModel):
    id: str
    runId: Optional[str] = None
    machineId: str
    type: str                        # unexpected_stop / no_data / long_idle / power_limit / ...
    description: Optional[str] = None
    source: str                      # rule / ai
    severity: Optional[str] = None
    startedAt: datetime
    closedAt: Optional[datetime] = None
    status: str                      # active / closed
    elapsedSeconds: Optional[float] = None
