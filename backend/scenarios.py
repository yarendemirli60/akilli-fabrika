"""
Panelden başlatılabilen senaryolar.

Senaryo listesinin tek kaynağı burası; panel GET /api/scenarios ile okur.
Yalnızca simülasyonun (simulasyon.py / publisher.py) gerçekten üretebildiği
senaryolar tanımlıdır:

  mode = "live": canlı simülasyon. "commands" listesindeki komutlar
                 (saniye, komut) çalışma başladıktan sonra o saniyede
                 simülasyona gönderilir (planlı arıza enjeksiyonu).
  mode = "csv" : kayıtlı veriyi gerçek zamanlı (hız x1) yeniden oynatır.
"""
from typing import Dict, List, Optional

SCENARIOS: List[Dict] = [
    {
        "id": "normal",
        "name": "Normal çalışma",
        "description": "Üç makine arızasız çalışır.",
        "mode": "live",
        "commands": [],
    },
    {
        "id": "yuksek_guc",
        "name": "Yüksek güç tüketimi",
        "description": "M3'te takım aşınması: kesme fazlarında güç normalin üstüne çıkar.",
        "mode": "live",
        "commands": [(0, "ariza M3")],
    },
    {
        "id": "beklenmeyen_durus",
        "name": "Beklenmeyen duruş",
        "description": "M2 60. saniyede durur, 120. saniyede yeniden çalışır.",
        "mode": "live",
        "commands": [(60, "durdur M2"), (120, "baslat M2")],
    },
    {
        "id": "kayit_normal",
        "name": "Kayıtlı veri (normal)",
        "description": "normal_veriler.csv gerçek zamanlı yeniden oynatılır.",
        "mode": "csv",
        "file": "normal_veriler.csv",
    },
    {
        "id": "kayit_arizali",
        "name": "Kayıtlı veri (arızalı)",
        "description": "test_veriler.csv (arızalı kesme fazları içerir) gerçek zamanlı yeniden oynatılır.",
        "mode": "csv",
        "file": "test_veriler.csv",
    },
]

# Panelde adı geçen ama simülasyonun henüz üretemediği senaryolar
UNSUPPORTED = {
    "Uzun boşta bekleme": "Simülasyonda makineyi uzun süre boşta bekletecek bir komut yok "
                          "(en uzun boşta faz 15 saniye; 'durdur' makineyi tamamen durdurur).",
}


def find(scenario: Optional[str]) -> Optional[Dict]:
    """Senaryoyu kimliğiyle ya da paneldeki adıyla bulur."""
    if not scenario:
        return None
    key = scenario.strip().casefold()
    return next((s for s in SCENARIOS
                 if s["id"].casefold() == key or s["name"].casefold() == key), None)


def public_list() -> List[Dict]:
    """Panele gösterilecek alanlar."""
    return [{"id": s["id"], "name": s["name"], "description": s["description"]} for s in SCENARIOS]
