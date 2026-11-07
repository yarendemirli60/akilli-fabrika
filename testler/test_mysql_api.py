"""
MySQL entegrasyon testleri.

Gerçek veritabanına (.env ayarlarıyla) bağlanır, kendine ait bir test
simülasyonu ekler, API'yi dener ve sonunda eklediği her şeyi siler.
MySQL'e bağlanılamazsa bu testler atlanır (skip), diğerleri etkilenmez.

Çalıştırma:  python -m pytest testler -v
"""
from datetime import datetime, timedelta

import mysql.connector
import pytest
from fastapi.testclient import TestClient

from backend.database import DB_CONFIG, get_cursor
from backend.main import app

TEST_SIM_CODE = "PYTEST-BACKEND"


def _db_available() -> bool:
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        conn.close()
        return True
    except mysql.connector.Error:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="MySQL'e bağlanılamadı")

client = TestClient(app)


def _cleanup(cur):
    cur.execute("SELECT id FROM simulations WHERE simulation_code = %s", (TEST_SIM_CODE,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (row["id"],))
        cur.execute("DELETE FROM simulations WHERE id = %s", (row["id"],))


@pytest.fixture(scope="module")
def seeded():
    """
    M2 için iki kısa senaryo ekler:
      - seq 1-5  : 10 dakika önce normal kesme (eski veri)
      - seq 6-10 : 10 dakika önce durmuş makine (güç ~0)
    Son ölçüm 10 dk önce olduğu için 'veri_yok' uyarısı da beklenir.
    """
    with get_cursor() as cur:
        _cleanup(cur)
        cur.execute("SELECT id FROM machines WHERE machine_code = 'M2'")
        machine_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO simulations (simulation_code, scenario, started_at) "
                    "VALUES (%s, 'test', NOW(3))", (TEST_SIM_CODE,))
        sim_id = cur.lastrowid
        t0 = datetime.now() - timedelta(minutes=10)
        rows = []
        for seq in range(1, 11):
            stopped = seq > 5
            rows.append((sim_id, machine_id, seq, t0 + timedelta(seconds=seq * 0.1), 0.1,
                         "normal_kesme" if not stopped else "bitis_bosta",
                         "stopped" if stopped else "working",
                         0.0 if stopped else 13.9, 0))
        cur.executemany(
            "INSERT INTO measurements (simulation_id, machine_id, seq, ts, duration_s, phase, "
            "status, power_kw, fault_label) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    yield {"machine_id": machine_id}
    with get_cursor() as cur:
        _cleanup(cur)


def test_db_health():
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json() == {"database": "ok"}


def test_machines_from_db():
    r = client.get("/machines")
    assert r.status_code == 200
    codes = [m["machine_code"] for m in r.json()]
    assert {"M1", "M2", "M3"} <= set(codes)


def test_measurements_from_db(seeded):
    r = client.get(f"/measurements?machine_id={seeded['machine_id']}&limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 10
    assert [row["seq"] for row in rows] == list(range(1, 11))   # eskiden yeniye sıralı


def test_latest_from_db(seeded):
    r = client.get(f"/machines/{seeded['machine_id']}/latest")
    assert r.status_code == 200
    assert r.json()["seq"] == 10
    assert r.json()["status"] == "stopped"


def test_stopped_and_no_data_alerts_from_db(seeded):
    r = client.get(f"/alerts/preview/{seeded['machine_id']}")
    assert r.status_code == 200
    types = {a["alert_type"] for a in r.json()}
    assert "makine_durdu" in types
    assert "veri_yok" in types
