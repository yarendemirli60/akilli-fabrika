"""
Uyarı kaynakları ve web paneli için tür eşlemesi.

alerts tablosuna iki program yazıyor:
  - backend uyarı motoru (kural tabanlı)  -> mesaj normal metin
  - ai/canli_analiz.py (yapay zekâ)       -> mesaj "AI|<uyari_id>|Sim=<kod> | <açıklama>"
Kaynağı ayırt etmek için yapay zekânın kullandığı "AI|" öneki kullanılıyor.
"""
import re
from typing import Optional

AI_PREFIX = "AI|"

# Web paneli sözleşmesindeki (API-SOZLESMESI.md) uyarı türleri
RULE_TYPE_MAP = {
    "makine_durdu": "unexpected_stop",
    "veri_yok": "no_data",
    "uzun_bosta": "long_idle",
    "yuksek_guc": "power_limit",
    "yuksek_enerji_parca": "energy_per_part_limit",
}
AI_TYPE_MAP = {
    "guc_anomalisi": "ai_anomaly",
    "uzun_bosta": "long_idle",
    # Sözleşmede karşılığı yok; yapay zekânın bulduğu bir üretim anomalisi olduğu için
    "yavas_uretim": "ai_anomaly",
}

_AI_MESSAGE = re.compile(r"^AI\|[^|]*\|Sim=(?P<sim>[^|]*?) \| ?(?P<text>.*)$", re.DOTALL)


def is_ai_alert(message: Optional[str]) -> bool:
    return bool(message) and message.startswith(AI_PREFIX)


def source_of(message: Optional[str]) -> str:
    return "ai" if is_ai_alert(message) else "rule"


def panel_type(alert_type: str, message: Optional[str]) -> str:
    table = AI_TYPE_MAP if is_ai_alert(message) else RULE_TYPE_MAP
    return table.get(alert_type, alert_type)


def ai_simulation_code(message: Optional[str]) -> Optional[str]:
    """Yapay zekâ mesajındaki simülasyon kodunu çıkarır."""
    if not is_ai_alert(message):
        return None
    m = _AI_MESSAGE.match(message)
    return m.group("sim").strip() if m else None


def description(message: Optional[str]) -> Optional[str]:
    """Panelde gösterilecek açıklama (yapay zekâ önekleri olmadan)."""
    if not is_ai_alert(message):
        return message
    m = _AI_MESSAGE.match(message)
    text = m.group("text") if m else message
    # Yapay zekâ uyarıyı kapatırken sona "| Kapanma: <neden>" ekliyor;
    # kapanış bilgisi closedAt alanında olduğu için açıklamadan çıkarılır
    return text.split(" | Kapanma:")[0].strip()
