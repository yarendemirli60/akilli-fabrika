"""
Backend ayarları ve makine sabitleri.

Makine sabitleri, makine mühendisliği şartnamesindeki Tablo 1 ve Tablo 2'den
ve veritabani/schema.sql içindeki başlangıç verisinden alınmıştır.
Uyarı eşikleri bu sabitlerden hesaplanır; böylece "eşik neden bu değer?"
sorusunun cevabı her zaman bir formüle dayanır.
"""

# Tablo 1: 42CrMo4 şaft işlemede net kesme gücü (kW)
P_CUT_NORMAL_KW = 11.52   # keskin takım
P_CUT_FAULTY_KW = 16.13   # aşınmış takım

# Tablo 2: tezgah bazlı sabitler (machine_code -> değerler)
MACHINE_CONSTANTS = {
    "M1": {"p_idle_kw": 3.2, "efficiency": 0.72, "sigma_active_normal": 0.60},
    "M2": {"p_idle_kw": 1.1, "efficiency": 0.90, "sigma_active_normal": 0.13},
    "M3": {"p_idle_kw": 4.2, "efficiency": 0.86, "sigma_active_normal": 0.35},
}


def expected_cutting_power_kw(machine_code: str) -> float:
    """Normal kesmede şebekeden beklenen toplam güç: P_boşta + P_c / η"""
    c = MACHINE_CONSTANTS[machine_code]
    return c["p_idle_kw"] + P_CUT_NORMAL_KW / c["efficiency"]


def high_power_threshold_kw(machine_code: str) -> float:
    """
    Yüksek güç eşiği = beklenen normal kesme gücü + 3σ.
    Normal dağılımda ölçümlerin ~%99.7'si bu sınırın altında kalır,
    bu yüzden eşiği aşmak gürültüden çok gerçek bir sorunu işaret eder.
    """
    c = MACHINE_CONSTANTS[machine_code]
    return expected_cutting_power_kw(machine_code) + 3 * c["sigma_active_normal"]


# --- Uyarı kuralı parametreleri ---
NO_DATA_TIMEOUT_S = 10.0          # bu süre boyunca ölçüm gelmezse: veri_yok
STOPPED_POWER_RATIO = 0.2         # güç < boşta gücün %20'si ise makine durmuş sayılır
STOPPED_MIN_READINGS = 3          # art arda en az bu kadar ölçümde durmuş olmalı
HIGH_POWER_MIN_READINGS = 10      # yüksek güç, art arda 10 ölçümün ortalamasında aranır (10 Hz'de 1 sn)
LONG_IDLE_S = 60.0                # bu süreden uzun boşta kalırsa: uzun_bosta
ENERGY_PER_PART_LIMIT_KWH = {     # parça başı enerji sınırı (kWh)
    "M1": 1.20,
    "M2": 0.80,
    "M3": 0.90,
}
