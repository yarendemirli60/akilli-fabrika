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
from backend.schemas import Alert, AlertRecord, Machine, Measurement

MEASUREMENT_COLUMNS = (
    "id, simulation_id, machine_id, seq, ts, start_s, end_s, duration_s, phase, "
    "status, power_kw, energy_kwh, completed_parts, work_s, idle_s, fault_label"
)
ALERT_COLUMNS = "id, machine_id, alert_type, severity, message, created_at, resolved_at"


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

    def get_measurements(self, machine_id: Optional[int] = None, limit: int = 100,
                         simulation_id: Optional[int] = None) -> List[Measurement]:
        # En yeni 'limit' kaydı alıp eskiden yeniye sıralı döndürüyoruz (grafikler için)
        where, params = [], []
        if machine_id is not None:
            where.append("machine_id = %s")
            params.append(machine_id)
        if simulation_id is not None:
            where.append("simulation_id = %s")
            params.append(simulation_id)
        sql = f"SELECT {MEASUREMENT_COLUMNS} FROM measurements"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC, id DESC LIMIT %s"
        params.append(limit)
        with get_cursor() as cur:
            cur.execute(sql, tuple(params))
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

    def simulation_ended(self, simulation_id: int) -> bool:
        """
        Çalışma bitti mi? Kullanıcı durdurduysa ended_at doludur; kendiliğinden
        bittiyse (ya da hata ile kapandıysa) bunu simülasyon kontrol programı bildirir.
        """
        with get_cursor() as cur:
            cur.execute("SELECT simulation_code, ended_at FROM simulations WHERE id = %s",
                        (simulation_id,))
            row = cur.fetchone()
        if row is None:
            return False
        if row["ended_at"] is not None:
            return True
        from backend.sim_control import control
        finished = control.last_finished() or {}
        return (finished.get("simulation_code") == row["simulation_code"]
                and control.running_code() != row["simulation_code"])

    # ---- Uyarılar ----

    def list_alerts(self, machine_id: Optional[int] = None, active: Optional[bool] = None,
                    limit: int = 100) -> List[AlertRecord]:
        where, params = [], []
        if machine_id is not None:
            where.append("machine_id = %s")
            params.append(machine_id)
        if active is True:
            where.append("resolved_at IS NULL")
        elif active is False:
            where.append("resolved_at IS NOT NULL")
        sql = f"SELECT {ALERT_COLUMNS} FROM alerts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(limit)
        with get_cursor() as cur:
            cur.execute(sql, tuple(params))
            return [AlertRecord(**row) for row in cur.fetchall()]

    def get_alert(self, alert_id: int) -> Optional[AlertRecord]:
        with get_cursor() as cur:
            cur.execute(f"SELECT {ALERT_COLUMNS} FROM alerts WHERE id = %s", (alert_id,))
            row = cur.fetchone()
            return AlertRecord(**row) if row else None

    def get_open_alerts(self, machine_id: int) -> List[AlertRecord]:
        return self.list_alerts(machine_id=machine_id, active=True, limit=1000)

    def insert_alert(self, alert: Alert) -> int:
        # created_at'i veritabanı veriyor (DEFAULT CURRENT_TIMESTAMP(3))
        with get_cursor() as cur:
            cur.execute("INSERT INTO alerts (machine_id, alert_type, severity, message) "
                        "VALUES (%s, %s, %s, %s)",
                        (alert.machine_id, alert.alert_type, alert.severity, alert.message))
            return cur.lastrowid

    def resolve_alert(self, alert_id: int) -> bool:
        with get_cursor() as cur:
            cur.execute("UPDATE alerts SET resolved_at = NOW(3) "
                        "WHERE id = %s AND resolved_at IS NULL", (alert_id,))
            return cur.rowcount == 1


# Örnek modda uyarılar bellekte tutuluyor (program kapanınca silinir)
_SAMPLE_ALERTS: List[AlertRecord] = []


class SampleRepository:
    def get_machines(self) -> List[Machine]:
        return sample_data.get_machines()

    def get_machine(self, machine_id: int) -> Optional[Machine]:
        return sample_data.get_machine(machine_id)

    def get_measurements(self, machine_id: Optional[int] = None, limit: int = 100,
                         simulation_id: Optional[int] = None) -> List[Measurement]:
        rows = sample_data.get_measurements(machine_id=machine_id, limit=5000)
        if simulation_id is not None:
            rows = [m for m in rows if m.simulation_id == simulation_id]
        return rows[-limit:]

    def get_latest_measurement(self, machine_id: int) -> Optional[Measurement]:
        return sample_data.get_latest_measurement(machine_id)

    def now(self) -> datetime:
        # Örnek veri geçmiş bir tarihte; "şimdi"yi son ölçüm anı kabul ediyoruz
        return sample_data.MEASUREMENTS[-1].ts

    def ping(self) -> bool:
        return True

    def list_alerts(self, machine_id: Optional[int] = None, active: Optional[bool] = None,
                    limit: int = 100) -> List[AlertRecord]:
        rows = [a for a in _SAMPLE_ALERTS
                if (machine_id is None or a.machine_id == machine_id)
                and (active is None or (a.resolved_at is None) == active)]
        return sorted(rows, key=lambda a: a.id, reverse=True)[:limit]

    def get_alert(self, alert_id: int) -> Optional[AlertRecord]:
        return next((a for a in _SAMPLE_ALERTS if a.id == alert_id), None)

    def get_open_alerts(self, machine_id: int) -> List[AlertRecord]:
        return self.list_alerts(machine_id=machine_id, active=True, limit=1000)

    def insert_alert(self, alert: Alert) -> int:
        new_id = len(_SAMPLE_ALERTS) + 1
        _SAMPLE_ALERTS.append(AlertRecord(id=new_id, **alert.model_dump(exclude={"created_at"}),
                                          created_at=self.now()))
        return new_id

    def resolve_alert(self, alert_id: int) -> bool:
        alert = self.get_alert(alert_id)
        if alert is None or alert.resolved_at is not None:
            return False
        alert.resolved_at = self.now()
        return True


def get_repository():
    """FastAPI bağımlılığı: router'lar repository'yi buradan alıyor."""
    if os.getenv("DATA_SOURCE", "mysql").lower() == "sample":
        return SampleRepository()
    return MySQLRepository()
