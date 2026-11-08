"""
Uyarı kuralları.

Her kural ölçüm listesini alıp uyarı varsa Alert, yoksa None döndürüyor.
Veritabanından ve API'den bağımsız oldukları için tek başına test edilebiliyorlar.

Kurallar: makine_durdu, veri_yok, yuksek_guc, uzun_bosta, yuksek_enerji_parca
"""
from datetime import datetime
from typing import List, Optional

from backend import config
from backend.schemas import Alert, Machine, Measurement


def check_machine_stopped(machine: Machine, measurements: List[Measurement]) -> Optional[Alert]:
    """Son N ölçümün hepsinde makine durmuşsa uyarı verir."""
    last = measurements[-config.STOPPED_MIN_READINGS:]
    if len(last) < config.STOPPED_MIN_READINGS:
        return None
    limit = (machine.p_idle_kw or 0) * config.STOPPED_POWER_RATIO
    if all(m.status == "stopped" or m.power_kw < limit for m in last):
        return Alert(
            machine_id=machine.id,
            alert_type="makine_durdu",
            severity="critical",
            message=f"{machine.name} durdu: son {len(last)} ölçümde güç {limit:.2f} kW altında.",
        )
    return None


def check_no_data(machine: Machine, last_measurement: Optional[Measurement],
                  now: datetime) -> Optional[Alert]:
    """Belirli süredir ölçüm gelmiyorsa (bağlantı kesintisi) uyarı verir."""
    if last_measurement is None:
        return Alert(machine_id=machine.id, alert_type="veri_yok", severity="warning",
                     message=f"{machine.name} için hiç ölçüm yok.")
    gap = (now - last_measurement.ts).total_seconds()
    if gap > config.NO_DATA_TIMEOUT_S:
        return Alert(
            machine_id=machine.id,
            alert_type="veri_yok",
            severity="warning",
            message=f"{machine.name}: {gap:.0f} saniyedir veri gelmiyor.",
        )
    return None


def check_high_power(machine: Machine, measurements: List[Measurement]) -> Optional[Alert]:
    """
    Son N ölçümün ortalaması makineye özel eşiği aşarsa uyarı verir.
    Tek bir ölçüme değil ortalamaya bakılır; böylece anlık gürültü
    sıçramaları yanlış alarm üretmez.
    """
    last = measurements[-config.HIGH_POWER_MIN_READINGS:]
    if len(last) < config.HIGH_POWER_MIN_READINGS:
        return None
    mean_power = sum(m.power_kw for m in last) / len(last)
    threshold = config.high_power_threshold_kw(machine.machine_code)
    if mean_power > threshold:
        return Alert(
            machine_id=machine.id,
            alert_type="yuksek_guc",
            severity="warning",
            message=(f"{machine.name}: ortalama güç {mean_power:.2f} kW, "
                     f"sınır {threshold:.2f} kW."),
        )
    return None


def check_long_idle(machine: Machine, measurements: List[Measurement]) -> Optional[Alert]:
    """Makine sondan geriye kesintisiz olarak uzun süre boşta kaldıysa uyarı verir."""
    idle_run = []
    for m in reversed(measurements):
        if m.status != "idle":
            break
        idle_run.append(m)
    if not idle_run:
        return None
    # Süreyi zaman damgalarından hesaplıyoruz; ölçüm aralığı ne olursa olsun doğru çalışır
    first, last = idle_run[-1], idle_run[0]
    idle_seconds = (last.ts - first.ts).total_seconds() + (last.duration_s or 0)
    if idle_seconds > config.LONG_IDLE_S:
        return Alert(
            machine_id=machine.id,
            alert_type="uzun_bosta",
            severity="info",
            message=f"{machine.name} {idle_seconds:.0f} saniyedir boşta.",
        )
    return None


def check_energy_per_part(machine: Machine, energy_per_part_kwh: Optional[float]) -> Optional[Alert]:
    """Parça başı enerji (analyses.energy_per_part_kwh) sınırı aşarsa uyarı verir."""
    limit = config.ENERGY_PER_PART_LIMIT_KWH.get(machine.machine_code)
    if energy_per_part_kwh is None or limit is None:
        return None
    if energy_per_part_kwh > limit:
        return Alert(
            machine_id=machine.id,
            alert_type="yuksek_enerji_parca",
            severity="warning",
            message=(f"{machine.name}: parça başı enerji {energy_per_part_kwh:.2f} kWh, "
                     f"sınır {limit:.2f} kWh."),
        )
    return None


def evaluate_all(machine: Machine, measurements: List[Measurement], now: datetime) -> List[Alert]:
    """Ölçüm tabanlı bütün kuralları çalıştırır, oluşan uyarıları döndürür."""
    last = measurements[-1] if measurements else None
    candidates = [
        check_machine_stopped(machine, measurements),
        check_no_data(machine, last, now),
        check_high_power(machine, measurements),
        check_long_idle(machine, measurements),
    ]
    return [a for a in candidates if a is not None]


# API'de /alerts/rules ile gösterilen kural tanımları
RULE_DEFINITIONS = [
    {"alert_type": "makine_durdu", "severity": "critical",
     "condition": f"Son {config.STOPPED_MIN_READINGS} ölçümde durum 'stopped' veya güç < boşta gücün %{int(config.STOPPED_POWER_RATIO * 100)}'si"},
    {"alert_type": "veri_yok", "severity": "warning",
     "condition": f"{config.NO_DATA_TIMEOUT_S:.0f} saniyeden uzun süre ölçüm gelmemesi"},
    {"alert_type": "yuksek_guc", "severity": "warning",
     "condition": f"Son {config.HIGH_POWER_MIN_READINGS} ölçümün ortalaması > P_boşta + P_c/η + 3σ"},
    {"alert_type": "uzun_bosta", "severity": "info",
     "condition": f"{config.LONG_IDLE_S:.0f} saniyeden uzun kesintisiz boşta kalma"},
    {"alert_type": "yuksek_enerji_parca", "severity": "warning",
     "condition": "Parça başı enerji makineye özel sınırı aşarsa"},
]
