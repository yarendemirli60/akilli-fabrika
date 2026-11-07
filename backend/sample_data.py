"""
Örnek veri ve veri erişim fonksiyonları.

MySQL bağlantısı eklenene kadar API bu verileri döndürür. Router'lar
veriye sadece alttaki get_* fonksiyonlarıyla eriştiği için veritabanına
geçerken yalnızca bu dosya değişecek.

Güç değerleri: P_toplam = P_boşta + P_c / η  (+ küçük sabit sapma)
Rastgele değer kullanmadım ki testler her seferinde aynı sonucu versin.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from backend.config import MACHINE_CONSTANTS, P_CUT_FAULTY_KW, P_CUT_NORMAL_KW
from backend.schemas import Machine, Measurement

# schema.sql'deki INSERT ile aynı üç makine
MACHINES: List[Machine] = [
    Machine(id=1, machine_code="M1", name="15 Yıllık Torna", p_idle_kw=3.2, efficiency=0.72),
    Machine(id=2, machine_code="M2", name="Eco CNC", p_idle_kw=1.1, efficiency=0.90),
    Machine(id=3, machine_code="M3", name="Çift Aynalı CNC", p_idle_kw=4.2, efficiency=0.86),
]

SAMPLE_SIMULATION_ID = 1
_BASE_TIME = datetime(2026, 11, 7, 10, 0, 0)
_STEP_S = 0.1  # 10 Hz

# Kısa bir örnek döngü: (faz, durum, kesme gücü, arıza etiketi, ölçüm sayısı)
_PHASES = [
    ("baslangic_bosta", "idle", 0.0, 0, 5),
    ("normal_kesme", "working", P_CUT_NORMAL_KW, 0, 10),
    ("ara_bosta", "idle", 0.0, 0, 5),
    ("arizali_kesme", "working", P_CUT_FAULTY_KW, 1, 10),
    ("bitis_bosta", "idle", 0.0, 0, 5),
]
# Gürültü yerine kullanılan sabit, tekrar eden küçük sapmalar (kW)
_WIGGLE = [0.00, 0.05, -0.04, 0.02, -0.01]


def _build_measurements() -> List[Measurement]:
    rows: List[Measurement] = []
    next_id = 1
    for machine in MACHINES:
        c = MACHINE_CONSTANTS[machine.machine_code]
        energy_kwh = 0.0
        work_s = idle_s = 0.0
        seq = 0
        for phase, status, p_cut, label, count in _PHASES:
            for _ in range(count):
                seq += 1
                power = c["p_idle_kw"] + p_cut / c["efficiency"] + _WIGGLE[seq % len(_WIGGLE)]
                energy_kwh += power * _STEP_S / 3600
                if status == "working":
                    work_s += _STEP_S
                else:
                    idle_s += _STEP_S
                start_s = (seq - 1) * _STEP_S
                rows.append(Measurement(
                    id=next_id,
                    simulation_id=SAMPLE_SIMULATION_ID,
                    machine_id=machine.id,
                    seq=seq,
                    ts=_BASE_TIME + timedelta(seconds=seq * _STEP_S),
                    start_s=round(start_s, 3),
                    end_s=round(start_s + _STEP_S, 3),
                    duration_s=_STEP_S,
                    phase=phase,
                    status=status,
                    power_kw=round(power, 3),
                    energy_kwh=round(energy_kwh, 6),
                    completed_parts=0,
                    work_s=round(work_s, 3),
                    idle_s=round(idle_s, 3),
                    fault_label=label,
                ))
                next_id += 1
    return rows


MEASUREMENTS: List[Measurement] = _build_measurements()


# ---- Router'ların kullandığı veri erişim fonksiyonları ----

def get_machines() -> List[Machine]:
    return MACHINES


def get_machine(machine_id: int) -> Optional[Machine]:
    return next((m for m in MACHINES if m.id == machine_id), None)


def get_measurements(machine_id: Optional[int] = None, limit: int = 100) -> List[Measurement]:
    rows = [m for m in MEASUREMENTS if machine_id is None or m.machine_id == machine_id]
    return rows[-limit:]  # en yeni 'limit' kayıt, zamana göre sıralı


def get_latest_measurement(machine_id: int) -> Optional[Measurement]:
    rows = get_measurements(machine_id=machine_id, limit=1)
    return rows[0] if rows else None
