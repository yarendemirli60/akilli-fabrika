"""Uyarı kaynağı ve web paneli tür eşlemesi testleri."""
from backend.alerts import mapping

AI_MSG = "AI|5f2c|Sim=SIM-20261107-162000 | Güç tüketimi normal aralığın dışında."


def test_source_detection():
    assert mapping.source_of(AI_MSG) == "ai"
    assert mapping.source_of("Eco CNC durdu") == "rule"
    assert mapping.source_of(None) == "rule"


def test_panel_types():
    assert mapping.panel_type("makine_durdu", "x") == "unexpected_stop"
    assert mapping.panel_type("veri_yok", "x") == "no_data"
    assert mapping.panel_type("yuksek_guc", "x") == "power_limit"
    assert mapping.panel_type("uzun_bosta", "x") == "long_idle"
    assert mapping.panel_type("yuksek_enerji_parca", "x") == "energy_per_part_limit"
    assert mapping.panel_type("guc_anomalisi", AI_MSG) == "ai_anomaly"
    assert mapping.panel_type("uzun_bosta", AI_MSG) == "long_idle"
    assert mapping.panel_type("yavas_uretim", AI_MSG) == "ai_anomaly"


def test_ai_message_parsing():
    assert mapping.ai_simulation_code(AI_MSG) == "SIM-20261107-162000"
    assert mapping.description(AI_MSG) == "Güç tüketimi normal aralığın dışında."
    closed = AI_MSG + " | Kapanma: normale_dondu"
    assert mapping.description(closed) == "Güç tüketimi normal aralığın dışında."
    assert mapping.ai_simulation_code(closed) == "SIM-20261107-162000"
    assert mapping.description("Eco CNC durdu") == "Eco CNC durdu"
