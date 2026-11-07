"""
API yanıt modelleri.
Alan adları veritabani/schema.sql ile aynı tutuldu, veri kaynağı
değişse de yanıt formatı değişmesin diye.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Machine(BaseModel):
    """machines tablosu"""
    id: int
    machine_code: str
    name: str
    p_idle_kw: Optional[float] = None
    efficiency: Optional[float] = None


class Measurement(BaseModel):
    """measurements tablosu"""
    id: int
    simulation_id: int
    machine_id: int
    seq: int
    ts: datetime
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    duration_s: Optional[float] = None
    phase: Optional[str] = None
    status: Optional[str] = None          # idle / working / stopped
    power_kw: float
    energy_kwh: Optional[float] = None
    completed_parts: Optional[int] = None
    work_s: Optional[float] = None
    idle_s: Optional[float] = None
    fault_label: Optional[int] = None     # 0 normal, 1 arızalı


class Alert(BaseModel):
    """alerts tablosu (id ve created_at veritabanı tarafından verilir)"""
    machine_id: int
    alert_type: str                       # makine_durdu, veri_yok, yuksek_guc, ...
    severity: str                         # info / warning / critical
    message: str
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
