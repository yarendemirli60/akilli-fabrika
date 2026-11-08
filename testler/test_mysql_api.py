"""
MySQL entegrasyon testleri.

Gerçek veritabanına (.env ayarlarıyla) bağlanır, kendine ait bir test
simülasyonu ekler, API'yi dener ve sonunda veritabanını eski haline getirir.
MySQL'e bağlanılamazsa bu testler atlanır (skip), diğerleri etkilenmez.

Not: Testleri çalıştırırken API (uvicorn) ve publisher kapalı olmalı;
yoksa arka plandaki uyarı motoru testle aynı anda kayıt ekler.

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
    M2 için iki kısa senaryo ekler (15 saniye önceye tarihli):
      - seq 1-5  : normal kesme
      - seq 6-10 : durmuş makine (güç ~0)
    Son ölçüm 10 saniyeden eski olduğu için 'veri_yok' uyarısı da beklenir.
    Test verisinin M2'nin en yeni ölçümleri olması gerekiyor; bu yüzden
    publisher en az 15 saniyedir kapalı olmalı.
    """
    with get_cursor() as cur:
        _cleanup(cur)
        cur.execute("SELECT id FROM machines WHERE machine_code = 'M2'")
        machine_id = cur.fetchone()["id"]
        t0 = datetime.now() - timedelta(seconds=15)
        cur.execute("SELECT MAX(ts) AS son FROM measurements WHERE machine_id = %s", (machine_id,))
        son = cur.fetchone()["son"]
        if son is not None and son >= t0:
            pytest.fail("M2 icin cok yeni olcum var. Publisher calisiyor olabilir; "
                        "publisher'i durdurup 15 saniye bekledikten sonra testleri tekrar calistirin.")
        cur.execute("INSERT INTO simulations (simulation_code, scenario, started_at) "
                    "VALUES (%s, 'test', NOW(3))", (TEST_SIM_CODE,))
        sim_id = cur.lastrowid
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
        cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM alerts")
        max_alert_id = cur.fetchone()["max_id"]
        # Test başlamadan önce açık olan uyarılar (test bunları kapatabilir)
        cur.execute("SELECT id FROM alerts WHERE machine_id = %s AND resolved_at IS NULL",
                    (machine_id,))
        open_before = [row["id"] for row in cur.fetchall()]
    yield {"machine_id": machine_id, "sim_id": sim_id}
    with get_cursor() as cur:
        # Testin oluşturduğu uyarıları sil, testten önce açık olanları tekrar aç
        cur.execute("DELETE FROM alerts WHERE id > %s AND machine_id = %s",
                    (max_alert_id, machine_id))
        for alert_id in open_before:
            cur.execute("UPDATE alerts SET resolved_at = NULL WHERE id = %s", (alert_id,))
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
    r = client.get(f"/measurements?machine_id={seeded['machine_id']}"
                   f"&simulation_id={seeded['sim_id']}&limit=10")
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


def test_alerts_saved_without_duplicates_and_resolved(seeded):
    mid = seeded["machine_id"]

    def open_types():
        active = client.get(f"/alerts?machine_id={mid}&active=true").json()
        return [a["alert_type"] for a in active]

    # 1) Kontrol: durmuş + eski veri -> iki uyarı da açık olmalı
    r = client.post(f"/alerts/check?machine_id={mid}")
    assert r.status_code == 200
    assert {"makine_durdu", "veri_yok"} <= set(open_types())

    # 2) Tekrar kontrol: aynı uyarılar ikinci kez yazılmaz
    r = client.post(f"/alerts/check?machine_id={mid}")
    assert r.json()[0]["created"] == []
    assert open_types().count("makine_durdu") == 1
    assert open_types().count("veri_yok") == 1

    # 3) Makine şu an normal çalışıyor -> uyarılar kapanır (normale dönüş)
    now = datetime.now()
    rows = [(seeded["sim_id"], mid, seq, now - timedelta(seconds=(20 - seq) * 0.1), 0.1,
             "normal_kesme", "working", 13.9, 0) for seq in range(11, 21)]
    with get_cursor() as cur:
        cur.executemany(
            "INSERT INTO measurements (simulation_id, machine_id, seq, ts, duration_s, phase, "
            "status, power_kw, fault_label) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    r = client.post(f"/alerts/check?machine_id={mid}")
    assert {"makine_durdu", "veri_yok"} <= set(r.json()[0]["resolved"])
    assert "makine_durdu" not in open_types() and "veri_yok" not in open_types()

    resolved = client.get(f"/alerts?machine_id={mid}&active=false").json()
    assert {"makine_durdu", "veri_yok"} <= {a["alert_type"] for a in resolved}
    assert all(a["resolved_at"] is not None for a in resolved)


def test_manual_resolve(seeded):
    mid = seeded["machine_id"]
    with get_cursor() as cur:
        cur.execute("INSERT INTO alerts (machine_id, alert_type, severity, message) "
                    "VALUES (%s, 'test_uyari', 'info', 'pytest')", (mid,))
        alert_id = cur.lastrowid
    r = client.post(f"/alerts/{alert_id}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved_at"] is not None
    assert client.post("/alerts/999999999/resolve").status_code == 404
