"""
Web paneli uçları (/api) testleri.

1) Saf hesaplamalar: çalışma durumu, sayaç farkları, durma süresi
2) MySQL entegrasyonu: 2 saat önceye tarihli küçük bir çalışma eklenir
   (3 makine, 20 saniye, saniyede 1 ölçüm), bir kural ve bir yapay zekâ
   uyarısı yazılır; uçların sözleşme formatında doğru değerleri döndürdüğü
   kontrol edilir. Test sonunda eklenen her şey silinir.
"""
from datetime import datetime, timedelta

import mysql.connector
import pytest
from fastapi.testclient import TestClient

from backend.database import DB_CONFIG, get_cursor
from backend.main import app
from backend.panel_repository import counter_delta, marks_point, run_status, stopped_seconds

T = datetime(2026, 11, 7, 12, 0, 0)


# ---------------- 1) Saf hesaplamalar ----------------

def test_run_status():
    # Terminalden başlatılan çalışma: son veri zamanına bakılır
    assert run_status(None, T, T + timedelta(seconds=5)) == "running"
    assert run_status(None, T, T + timedelta(seconds=60)) == "completed"
    assert run_status(None, None, T) == "completed"
    # ended_at yalnızca kullanıcı durdurmasında dolar
    assert run_status(T, T, T) == "user_stopped"


def test_run_status_from_control_program():
    later = T + timedelta(minutes=5)          # veri eski olsa bile
    assert run_status(None, T, later, "SIM-1", running_code="SIM-1") == "running"
    done = {"simulation_code": "SIM-1", "reason": "completed"}
    assert run_status(None, T, T, "SIM-1", None, done) == "completed"   # veri yeni olsa bile
    crashed = {"simulation_code": "SIM-1", "reason": "error"}
    assert run_status(None, T, T, "SIM-1", None, crashed) == "error"
    other = {"simulation_code": "SIM-2", "reason": "error"}
    assert run_status(None, T, later, "SIM-1", None, other) == "completed"


def test_counter_delta_uses_differences():
    start = {"energy_kwh": 1.0, "completed_parts": 2, "work_s": 100.0, "idle_s": 20.0, "end_s": 120.0}
    end = {"energy_kwh": 3.0, "completed_parts": 6, "work_s": 400.0, "idle_s": 50.0, "end_s": 470.0}
    d = counter_delta(start, end)
    assert d["energyKwh"] == 2.0
    assert d["productionCount"] == 4
    assert d["energyPerPartKwh"] == 0.5
    assert d["runningSeconds"] == 300.0
    assert d["idleSeconds"] == 30.0
    assert d["stoppedSeconds"] == 20.0      # 350 sn geçti, 300 çalışma + 30 boşta


def test_power_limit_marks_only_cutting_points():
    assert marks_point("power_limit", bucket_working=True) is True
    assert marks_point("power_limit", bucket_working=False) is False   # boşta noktası
    assert marks_point("ai_anomaly", bucket_working=False) is True     # yapay zekâ kararı olduğu gibi


def test_counter_delta_edge_cases():
    # Hiç parça yoksa parça başı enerji null (sıfıra bölme yok)
    d = counter_delta(None, {"energy_kwh": 1.0, "completed_parts": 0, "work_s": 5, "idle_s": 1})
    assert d["energyPerPartKwh"] is None
    # Ölçüm yoksa her şey null (sıfırla değiştirilmez)
    assert all(v is None for v in counter_delta(None, None).values())


def test_stopped_seconds():
    assert stopped_seconds({"end_s": 100.0, "work_s": 70.0, "idle_s": 20.0}) == 10.0
    assert stopped_seconds({"end_s": 100.0, "work_s": None, "idle_s": 20.0}) is None


# ---------------- 2) MySQL entegrasyonu ----------------

def _db_available() -> bool:
    try:
        mysql.connector.connect(**DB_CONFIG).close()
        return True
    except mysql.connector.Error:
        return False


db = pytest.mark.skipif(not _db_available(), reason="MySQL'e bağlanılamadı")
client = TestClient(app)
SIM_CODE = "PYTEST-PANEL"


def _cleanup(cur, alert_ids=()):
    for alert_id in alert_ids:
        cur.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
    cur.execute("SELECT id FROM simulations WHERE simulation_code = %s", (SIM_CODE,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (row["id"],))
        cur.execute("DELETE FROM simulations WHERE id = %s", (row["id"],))


@pytest.fixture(scope="module")
def run():
    """
    Her makine için 20 ölçüm (1 sn aralıkla):
      - güç: M1 10 kW, M2 20 kW, M3 30 kW (sabit)
      - enerji sayacı her saniye güç/3600 kadar artar
      - 10. saniyede 1 parça tamamlanır
    M1 için 5-7. saniyelerde açık kalmış bir yapay zekâ anomalisi,
    M2 için 12. saniyede açılıp kapanmış bir kural uyarısı (yuksek_guc).
    """
    alert_ids = []
    with get_cursor() as cur:
        _cleanup(cur)
        cur.execute("SELECT id, machine_code FROM machines ORDER BY id")
        machines = cur.fetchall()
        start = datetime.now().replace(microsecond=0) - timedelta(hours=2)
        cur.execute("INSERT INTO simulations (simulation_code, started_at) VALUES (%s, %s)",
                    (SIM_CODE, start))
        sim_id = cur.lastrowid
        rows = []
        for idx, m in enumerate(machines, start=1):
            power = 10.0 * idx
            for sec in range(1, 21):
                rows.append((sim_id, m["id"], sec, start + timedelta(seconds=sec),
                             sec - 1.0, float(sec), 1.0, "normal_kesme", "working", power,
                             power * sec / 3600, 1 if sec >= 10 else 0, float(sec), 0.0, 0))
        cur.executemany(
            "INSERT INTO measurements (simulation_id, machine_id, seq, ts, start_s, end_s, "
            "duration_s, phase, status, power_kw, energy_kwh, completed_parts, work_s, idle_s, "
            "fault_label) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        m1, m2 = machines[0]["id"], machines[1]["id"]
        cur.execute("INSERT INTO alerts (machine_id, alert_type, severity, message, created_at) "
                    "VALUES (%s, 'guc_anomalisi', 'warning', %s, %s)",
                    (m1, f"AI|test-1|Sim={SIM_CODE} | Güç tüketimi normal aralığın dışında.",
                     start + timedelta(seconds=5)))
        alert_ids.append(cur.lastrowid)
        cur.execute("INSERT INTO alerts (machine_id, alert_type, severity, message, created_at, "
                    "resolved_at) VALUES (%s, 'yuksek_guc', 'warning', 'pytest kural uyarisi', %s, %s)",
                    (m2, start + timedelta(seconds=12), start + timedelta(seconds=13)))
        alert_ids.append(cur.lastrowid)
    yield {"id": str(sim_id), "m1": str(m1), "m2": str(m2), "ai_alert": str(alert_ids[0]),
           "rule_alert": str(alert_ids[1])}
    with get_cursor() as cur:
        _cleanup(cur, alert_ids)


@db
def test_runs_list(run):
    runs = client.get("/api/runs").json()
    ours = next(r for r in runs if r["runId"] == run["id"])
    assert ours["status"] == "completed"          # 2 saat önce bitti
    assert ours["elapsedSeconds"] == 20.0
    assert ours["endedAt"] is not None
    assert client.get("/api/runs?status=running").status_code == 200


@db
def test_snapshot(run):
    r = client.get(f"/api/runs/{run['id']}/snapshot")
    assert r.status_code == 200
    snap = r.json()
    assert len(snap["machines"]) == 3
    m1 = next(m for m in snap["machines"] if m["id"] == run["m1"])
    assert m1["status"] == "running"              # working -> running
    assert m1["powerKw"] == 10.0
    assert m1["productionCount"] == 1
    assert m1["energyKwh"] == pytest.approx(10 * 20 / 3600, abs=1e-6)
    assert m1["stoppedSeconds"] == 0.0
    assert m1["ai"]["result"] == "anomaly"        # açık yapay zekâ uyarısı var
    m2 = next(m for m in snap["machines"] if m["id"] == run["m2"])
    assert m2["ai"]["result"] == "normal"


@db
def test_series(run):
    pts = client.get(f"/api/runs/{run['id']}/machines/{run['m1']}/series?from=0&to=10").json()
    assert [p["elapsedSeconds"] for p in pts] == [float(s) for s in range(1, 11)]
    assert all(p["powerKw"] == 10.0 for p in pts)
    assert pts[-1]["productionCount"] == 1
    # Yapay zekâ uyarısı 5. saniyede açıldı ve hâlâ açık
    assert [p["anomaly"] for p in pts] == [False] * 4 + [True] * 6
    assert pts[4]["alertId"] == run["ai_alert"]


@db
def test_series_step(run):
    pts = client.get(f"/api/runs/{run['id']}/machines/{run['m1']}/series?from=0&to=20&step=5").json()
    assert len(pts) == 5                          # 1-4, 5-9, 10-14, 15-19, 20


@db
def test_comparison(run):
    c = client.get(f"/api/runs/{run['id']}/comparison?from=5&to=15").json()
    m2 = next(m for m in c["machines"] if m["id"] == run["m2"])
    # Sayaç farkı: 20 kW x 10 sn = 0.0556 kWh, bu aralıkta 1 parça
    assert m2["energyKwh"] == pytest.approx(20 * 10 / 3600, abs=1e-6)
    assert m2["productionCount"] == 1
    assert m2["energyPerPartKwh"] == pytest.approx(20 * 10 / 3600, abs=1e-6)
    assert m2["runningSeconds"] == 10.0
    assert m2["stoppedSeconds"] == 0.0
    assert m2["averagePowerKw"] == 20.0


@db
def test_alerts_mapping(run):
    alerts = client.get(f"/api/alerts?runId={run['id']}").json()
    by_id = {a["id"]: a for a in alerts}
    ai = by_id[run["ai_alert"]]
    assert ai["type"] == "ai_anomaly" and ai["source"] == "ai" and ai["status"] == "active"
    assert ai["description"] == "Güç tüketimi normal aralığın dışında."
    assert ai["elapsedSeconds"] == 5.0
    rule = by_id[run["rule_alert"]]
    assert rule["type"] == "power_limit" and rule["source"] == "rule" and rule["status"] == "closed"
    assert rule["runId"] == run["id"]             # zaman aralığından çalışmaya bağlandı


@db
def test_alerts_filters(run):
    base = f"/api/alerts?runId={run['id']}"
    assert [a["id"] for a in client.get(base + "&source=x&type=power_limit").json()] == [run["rule_alert"]]
    assert [a["id"] for a in client.get(base + "&status=active").json()] == [run["ai_alert"]]
    assert [a["id"] for a in client.get(base + "&from=10&to=20").json()] == [run["rule_alert"]]
    assert client.get(base + "&from=abc").status_code == 422


@db
def test_not_found(run):
    assert client.get("/api/runs/999999/snapshot").status_code == 404
    assert client.get("/api/runs/abc/snapshot").status_code == 404
    assert client.get(f"/api/runs/{run['id']}/machines/99/series").status_code == 404
