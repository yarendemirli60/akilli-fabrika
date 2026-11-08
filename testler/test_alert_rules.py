"""
Uyarı kuralı birim testleri: her kural için "uyarı vermeli" ve
"uyarı vermemeli" durumları ayrı ayrı denenir.
Çalıştırma (proje kök klasöründen):  python -m pytest testler -v
"""
from datetime import datetime, timedelta

from backend import config
from backend.alerts import rules
from backend.schemas import Machine, Measurement

M1 = Machine(id=1, machine_code="M1", name="15 Yıllık Torna", p_idle_kw=3.2, efficiency=0.72)
T0 = datetime(2026, 11, 7, 10, 0, 0)


def make(powers, status="working"):
    """Verilen güç değerlerinden 10 Hz ölçüm listesi üretir."""
    return [
        Measurement(id=i, simulation_id=1, machine_id=1, seq=i,
                    ts=T0 + timedelta(seconds=i * 0.1), duration_s=0.1,
                    status=status, power_kw=p)
        for i, p in enumerate(powers, start=1)
    ]


def test_threshold_formula():
    # 3.2 + 11.52/0.72 + 3*0.60 = 21.0 kW
    assert abs(config.high_power_threshold_kw("M1") - 21.0) < 1e-9


# --- makine_durdu ---
def test_stopped_detected():
    alert = rules.check_machine_stopped(M1, make([0.1, 0.0, 0.2]))
    assert alert is not None and alert.alert_type == "makine_durdu"


def test_stopped_not_triggered_when_idle_power_normal():
    assert rules.check_machine_stopped(M1, make([3.2, 3.1, 3.3], status="idle")) is None


def test_stopped_needs_consecutive_readings():
    assert rules.check_machine_stopped(M1, make([0.0, 3.2, 0.0])) is None


# --- veri_yok ---
def test_no_data_when_gap_too_long():
    last = make([19.2])[-1]
    now = last.ts + timedelta(seconds=config.NO_DATA_TIMEOUT_S + 1)
    assert rules.check_no_data(M1, last, now).alert_type == "veri_yok"


def test_no_data_ok_when_recent():
    last = make([19.2])[-1]
    assert rules.check_no_data(M1, last, last.ts + timedelta(seconds=1)) is None


def test_no_alert_before_any_run():
    # Hiç ölçüm yoksa çalışma başlatılmamıştır; veri_yok uyarısı açılmaz
    assert rules.check_no_data(M1, None, T0) is None


# --- yuksek_guc ---
def test_high_power_on_faulty_cutting():
    # Arızalı kesme M1: 3.2 + 16.13/0.72 ≈ 25.6 kW > 21.0 eşik
    alert = rules.check_high_power(M1, make([25.6] * 10))
    assert alert is not None and alert.alert_type == "yuksek_guc"


def test_high_power_not_on_normal_cutting():
    assert rules.check_high_power(M1, make([19.2] * 10)) is None


def test_single_spike_does_not_trigger():
    # 9 normal + 1 sıçrama: ortalama eşiği aşmaz -> yanlış alarm yok
    assert rules.check_high_power(M1, make([19.2] * 9 + [26.0])) is None


# --- uzun_bosta ---
def test_long_idle_detected():
    n = int(config.LONG_IDLE_S / 0.1) + 10
    alert = rules.check_long_idle(M1, make([3.2] * n, status="idle"))
    assert alert is not None and alert.alert_type == "uzun_bosta"


def test_short_idle_ok():
    assert rules.check_long_idle(M1, make([3.2] * 50, status="idle")) is None


# --- yuksek_enerji_parca ---
def test_energy_per_part():
    assert rules.check_energy_per_part(M1, 1.5) is not None
    assert rules.check_energy_per_part(M1, 1.0) is None
    assert rules.check_energy_per_part(M1, None) is None
