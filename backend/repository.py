"""
Veri erişim katmanı.

Router'lar veriyi doğrudan veritabanından değil, buradaki repository
nesnelerinden alıyor. İki sürüm var:
  - MySQLRepository : gerçek veritabanı (varsayılan)
  - SampleRepository: sample_data.py içindeki örnek veri (testler ve
                      MySQL kurulu değilken denemek için)

Hangisinin kullanılacağı .env içindeki DATA_SOURCE ile seçiliyor:
  DATA_SOURCE=mysql   (varsayılan)
  DATA_SOURCE=sample
"""
import os
from datetime import datetime
from typing import List, Optional

from backend import sample_data
from backend.database import get_cursor
from backend.schemas import Machine, Measurement

MEASUREMENT_COLUMNS = (
    "id, simulation_id, machine_id, seq, ts, start_s, end_s, duration_s, phase, "
    "status, power_kw, energy_kwh, completed_parts, work_s, idle_s, fault_label"
)


class MySQLRepository:
    def get_machines(self) -> List[Machine]:
        with get_cursor() as cur:
            cur.execute("SELECT id, machine_code, name, p_idle_kw, efficiency "
                        "FROM machines ORDER BY id")
            return [Machine(**row) for row in cur.fetchall()]

    def get_machine(self, machine_id: int) -> Optional[Machine]:
        with get_cursor() as cur:
            cur.execute("SELECT id, machine_code, name, p_idle_kw, efficiency "
                        "FROM machines WHERE id = %s", (machine_id,))
            row = cur.fetchone()
            return Machine(**row) if row else None

    def get_measurements(self, machine_id: Optional[int] = None, limit: int = 100) -> List[Measurement]:
        # En yeni 'limit' kaydı alıp eskiden yeniye sıralı döndürüyoruz (grafikler için)
        sql = f"SELECT {MEASUREMENT_COLUMNS} FROM measurements"
        params: tuple = ()
        if machine_id is not None:
            sql += " WHERE machine_id = %s"
            params = (machine_id,)
        sql += " ORDER BY ts DESC, id DESC LIMIT %s"
        params += (limit,)
        with get_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [Measurement(**row) for row in reversed(rows)]

    def get_latest_measurement(self, machine_id: int) -> Optional[Measurement]:
        rows = self.get_measurements(machine_id=machine_id, limit=1)
        return rows[0] if rows else None

    def now(self) -> datetime:
        # "Veri yok" kuralı son ölçümü şu anki saatle karşılaştırıyor
        return datetime.now()

    def ping(self) -> bool:
        with get_cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            return cur.fetchone()["ok"] == 1


class SampleRepository:
    def get_machines(self) -> List[Machine]:
        return sample_data.get_machines()

    def get_machine(self, machine_id: int) -> Optional[Machine]:
        return sample_data.get_machine(machine_id)

    def get_measurements(self, machine_id: Optional[int] = None, limit: int = 100) -> List[Measurement]:
        return sample_data.get_measurements(machine_id=machine_id, limit=limit)

    def get_latest_measurement(self, machine_id: int) -> Optional[Measurement]:
        return sample_data.get_latest_measurement(machine_id)

    def now(self) -> datetime:
        # Örnek veri geçmiş bir tarihte; "şimdi"yi son ölçüm anı kabul ediyoruz
        return sample_data.MEASUREMENTS[-1].ts

    def ping(self) -> bool:
        return True


def get_repository():
    """FastAPI bağımlılığı: router'lar repository'yi buradan alıyor."""
    if os.getenv("DATA_SOURCE", "mysql").lower() == "sample":
        return SampleRepository()
    return MySQLRepository()
