"""
Uçtan uca test: panelden başlat/durdur akışının tamamı.

  POST /api/runs -> API -> MQTT -> sim_agent -> publisher.py -> MQTT
  -> subscriber.py -> MySQL -> GET /api/runs/{id}/snapshot -> POST /stop

Gerçek Mosquitto, MySQL ve ekibin publisher/subscriber kodlarını kullanır.
Veritabanına gerçek bir çalışma yazdığı için yalnızca istenirse çalışır:
    RUN_E2E=1 python -m pytest testler/test_e2e_panel.py -v
Test sırasında başka subscriber/publisher/API/sim_agent çalışmamalı.
Test sonunda oluşturduğu çalışmayı ve uyarıları siler.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJE_KOKU = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(os.getenv("RUN_E2E") != "1",
                                reason="Uçtan uca test yalnızca RUN_E2E=1 ile çalışır")


def test_start_snapshot_stop_end_to_end():
    from backend.database import get_cursor
    from backend.main import app
    from backend.sim_agent import SimulationAgent
    from backend.sim_control import control

    with get_cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM alerts")
        max_alert = cur.fetchone()["m"]

    subscriber = subprocess.Popen([sys.executable, "-u", str(PROJE_KOKU / "mqtt" / "subscriber.py")],
                                  cwd=str(PROJE_KOKU), stdout=subprocess.DEVNULL)
    agent = SimulationAgent()
    agent.connect()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            agent.tick()
            time.sleep(0.1)

    threading.Thread(target=loop, daemon=True).start()
    control.start()
    client = TestClient(app)
    run_id = None
    try:
        deadline = time.time() + 10
        while not control.agent_online() and time.time() < deadline:
            time.sleep(0.1)
        assert client.get("/api/control/status").json()["agentOnline"] is True

        # Başlat
        r = client.post("/api/runs", json={"scenarioId": "yuksek_guc"})
        assert r.status_code == 201, r.text
        run = r.json()
        run_id = run["runId"]
        assert run["status"] == "running" and run["scenarioId"] == "yuksek_guc"

        # Veri akıyor mu?
        time.sleep(3)
        snap = client.get(f"/api/runs/{run_id}/snapshot").json()
        assert snap["status"] == "running"
        assert len(snap["machines"]) == 3
        assert all(m["powerKw"] is not None for m in snap["machines"])
        assert snap["elapsedSeconds"] >= 2

        # İkinci başlatma reddedilir
        assert client.post("/api/runs", json={"scenarioId": "normal"}).status_code == 409

        # Durdur
        r = client.post(f"/api/runs/{run_id}/stop")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "user_stopped"
        assert client.get("/api/runs/current").json() is None
        assert client.get("/api/control/status").json()["state"] == "idle"

        # Durdurma arıza uyarısı açmaz (veri kesildi ama beklenen bir durum)
        time.sleep(11)
        for result in client.post("/alerts/check").json():
            assert "veri_yok" not in result["created"]
    finally:
        control.stop()
        stop.set()
        if agent.is_running():
            agent.process.kill()
        agent.client.loop_stop()
        agent.client.disconnect()
        subscriber.terminate()
        subscriber.wait(timeout=10)
        with get_cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE id > %s", (max_alert,))
            if run_id:
                cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (int(run_id),))
                cur.execute("DELETE FROM simulations WHERE id = %s", (int(run_id),))


def test_live_fault_scenario_alerts_end_to_end():
    """
    yuksek_guc senaryosu ~2 dakika canlı çalışır (M3 boşta -> arızalı kesme -> boşta -> arızalı kesme).
    Önceki bir çalışmanın boşta biten verisi veritabanında dururken:
      - M3 için tek bir yuksek_guc uyarısı açılmalı ve fazlar arası geçişlerde kapanıp açılmamalı
      - Başlangıçtaki 15 saniyelik boşta faz uzun_bosta uyarısı açmamalı
    """
    from datetime import datetime, timedelta
    from backend.alerts import engine
    from backend.database import get_cursor
    from backend.main import app
    from backend.repository import MySQLRepository
    from backend.sim_agent import SimulationAgent
    from backend.sim_control import control

    with get_cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM alerts")
        max_alert = cur.fetchone()["m"]
        # Önceki çalışma: 1 saat önce, boşta bitmiş ve kullanıcı tarafından durdurulmuş
        old_start = datetime.now() - timedelta(hours=1)
        cur.execute("INSERT INTO simulations (simulation_code, started_at, ended_at) "
                    "VALUES ('PYTEST-ESKI', %s, %s)", (old_start, old_start + timedelta(seconds=5)))
        old_id = cur.lastrowid
        cur.execute("SELECT id FROM machines")
        for m in cur.fetchall():
            for seq in range(1, 11):
                cur.execute("INSERT INTO measurements (simulation_id, machine_id, seq, ts, end_s, "
                            "duration_s, status, power_kw) VALUES (%s,%s,%s,%s,%s,0.1,'idle',3.0)",
                            (old_id, m["id"], seq, old_start + timedelta(seconds=seq * 0.1), seq * 0.1))

    subscriber = subprocess.Popen([sys.executable, "-u", str(PROJE_KOKU / "mqtt" / "subscriber.py")],
                                  cwd=str(PROJE_KOKU), stdout=subprocess.DEVNULL)
    agent = SimulationAgent()
    agent.connect()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            agent.tick()
            time.sleep(0.1)

    threading.Thread(target=loop, daemon=True).start()
    control.start()
    client = TestClient(app)
    run_id = None
    created = []
    try:
        deadline = time.time() + 10
        while not control.agent_online() and time.time() < deadline:
            time.sleep(0.1)
        r = client.post("/api/runs", json={"scenarioId": "yuksek_guc"})
        assert r.status_code == 201, r.text
        run_id = r.json()["runId"]

        # Uyarı motorunu API'deki gibi düzenli aralıklarla çalıştır
        repo = MySQLRepository()
        end = time.time() + 125
        while time.time() < end:
            for result in engine.run_once(repo):
                created += [(result["machine_id"], t) for t in result["created"]]
            time.sleep(1)

        client.post(f"/api/runs/{run_id}/stop")
        types = [t for _, t in created]
        assert types.count("yuksek_guc") == 1, created     # açılıp kapanma yok
        assert "uzun_bosta" not in types, created           # önceki çalışma sayılmadı
        assert "veri_yok" not in types, created
    finally:
        control.stop()
        stop.set()
        if agent.is_running():
            agent.process.kill()
        agent.client.loop_stop()
        agent.client.disconnect()
        subscriber.terminate()
        subscriber.wait(timeout=10)
        with get_cursor() as cur:
            cur.execute("DELETE FROM alerts WHERE id > %s", (max_alert,))
            for sim in [old_id] + ([int(run_id)] if run_id else []):
                cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (sim,))
                cur.execute("DELETE FROM simulations WHERE id = %s", (sim,))
