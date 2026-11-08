"""
Simülasyon başlat/durdur testleri.

1) Uyarı motoru: bitmiş çalışma için uyarı açılmaz (duruma göre bastırma)
2) API: POST /api/runs ve /stop, sahte kontrol programıyla (MySQL gerekir)
3) Kontrol programı (sim_agent): gerçek MQTT broker ve gerçek publisher.py ile
   (Mosquitto çalışmıyorsa ya da proje klasöründe publisher.py yoksa atlanır)

Not: Testler sırasında subscriber, publisher ve API kapalı olmalı.
"""
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import mysql.connector
import pytest
from fastapi.testclient import TestClient

from backend.alerts import engine
from backend.database import DB_CONFIG, get_cursor
from backend.main import app
from backend.panel_repository import PanelRepository
from backend.routers.panel import get_control, get_panel_repository
from backend.schemas import AlertRecord, Machine, Measurement
from backend.sim_control import ControlError

T0 = datetime(2026, 11, 7, 10, 0, 0)
M1 = Machine(id=1, machine_code="M1", name="15 Yıllık Torna", p_idle_kw=3.2, efficiency=0.72)


# ---------------- 1) Duruma göre bastırma ----------------

class EndedRepo:
    """Son ölçümü bitmiş bir çalışmaya ait makine."""
    def __init__(self, ended):
        self.ended = ended
        self.alerts = [AlertRecord(id=1, machine_id=1, alert_type="yuksek_guc", severity="warning",
                                   message="acik kural uyarisi", created_at=T0)]
        self.measurements = [Measurement(id=i, simulation_id=7, machine_id=1, seq=i,
                                         ts=T0 + timedelta(seconds=i * 0.1), duration_s=0.1,
                                         status="working", power_kw=25.6) for i in range(1, 11)]

    def get_machines(self): return [M1]
    def get_measurements(self, machine_id=None, limit=100): return self.measurements[-limit:]
    def now(self): return T0 + timedelta(minutes=5)     # 5 dakikadır veri yok
    def simulation_ended(self, simulation_id): return self.ended
    def get_open_alerts(self, machine_id): return [a for a in self.alerts if a.resolved_at is None]
    def insert_alert(self, alert): self.alerts.append(alert)
    def resolve_alert(self, alert_id): self.alerts[alert_id - 1].resolved_at = self.now()


def test_ended_run_suppresses_alerts():
    repo = EndedRepo(ended=True)
    result = engine.run_once(repo)[0]
    assert result["created"] == []                    # veri_yok açılmadı
    assert result["resolved"] == ["yuksek_guc"]       # açık kural uyarısı kapandı


def test_running_run_still_alerts():
    repo = EndedRepo(ended=False)
    result = engine.run_once(repo)[0]
    assert "veri_yok" in result["created"]            # çalışma sürüyorsa veri kesintisi uyarıdır


# ---------------- 2) API başlat / durdur ----------------

def _db_available() -> bool:
    try:
        mysql.connector.connect(**DB_CONFIG).close()
        return True
    except mysql.connector.Error:
        return False


class FakeControl:
    """
    Kontrol programının yerine geçer. Başlatıldığında subscriber'ın yapacağı gibi
    simulations kaydını ve birkaç ölçümü veritabanına yazar.
    """
    def __init__(self):
        self.online = True
        self.running = None
        self.finished = None
        self.codes = []

    def agent_online(self): return self.online
    def running_code(self): return self.running
    def last_finished(self): return self.finished
    def status(self): return {"agent": "online", "state": "running" if self.running else "idle"}

    def send(self, action, simulation_code, scenario=None, timeout=15.0):
        if not self.online:
            raise ControlError("Simülasyon kontrol programı çalışmıyor.")
        if action == "start":
            if self.running:
                raise ControlError("Zaten calisan bir simulasyon var", "conflict")
            self.running = simulation_code
            self.codes.append(simulation_code)
            with get_cursor() as cur:
                cur.execute("INSERT INTO simulations (simulation_code, started_at) VALUES (%s, NOW(3))",
                            (simulation_code,))
                sim_id = cur.lastrowid
                cur.execute("SELECT id FROM machines")
                for m in cur.fetchall():
                    cur.execute("INSERT INTO measurements (simulation_id, machine_id, seq, ts, end_s, "
                                "duration_s, status, power_kw) VALUES (%s,%s,1,NOW(3),0.1,0.1,'idle',3.0)",
                                (sim_id, m["id"]))
        elif action == "stop":
            if self.running != simulation_code:
                raise ControlError("Bu simulasyon calismiyor.", "conflict")
            self.running = None
            self.finished = {"simulation_code": simulation_code, "reason": "user_stopped"}
        return self.status()


@pytest.fixture
def api():
    fake = FakeControl()
    app.dependency_overrides[get_control] = lambda: fake
    app.dependency_overrides[get_panel_repository] = lambda: PanelRepository(control=fake)
    with get_cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM alerts")
        max_alert = cur.fetchone()["m"]
    yield TestClient(app), fake
    app.dependency_overrides.clear()
    with get_cursor() as cur:
        cur.execute("DELETE FROM alerts WHERE id > %s", (max_alert,))
        for code in fake.codes:
            cur.execute("SELECT id FROM simulations WHERE simulation_code = %s", (code,))
            row = cur.fetchone()
            if row:
                cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (row["id"],))
                cur.execute("DELETE FROM simulations WHERE id = %s", (row["id"],))


db = pytest.mark.skipif(not _db_available(), reason="MySQL'e bağlanılamadı")


@db
def test_start_and_stop(api):
    client, fake = api
    r = client.post("/api/runs", json={"scenarioId": "normal"})
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "running" and run["scenarioId"] == "normal"
    assert client.get("/api/runs/current").json()["runId"] == run["runId"]

    # İkinci başlatma: 409
    assert client.post("/api/runs", json={"scenarioId": "normal"}).status_code == 409

    r = client.post(f"/api/runs/{run['runId']}/stop")
    assert r.status_code == 200
    stopped = r.json()
    assert stopped["status"] == "user_stopped" and stopped["endedAt"] is not None
    assert client.get("/api/runs/current").json() is None

    # Bitmiş çalışmayı tekrar durdurmak: 409
    assert client.post(f"/api/runs/{run['runId']}/stop").status_code == 409


@db
def test_stop_does_not_open_alerts(api):
    client, fake = api
    run = client.post("/api/runs", json={"scenarioId": "normal"}).json()
    client.post(f"/api/runs/{run['runId']}/stop")
    # Durdurulan çalışmanın verisi kesildi; bu bir arıza değildir
    result = client.post("/alerts/check").json()
    assert all("veri_yok" not in m["created"] for m in result)


@db
def test_start_with_panel_name(api):
    client, fake = api
    r = client.post("/api/runs", json={"scenarioId": "Yüksek güç tüketimi"})
    assert r.status_code == 201 and r.json()["scenarioId"] == "yuksek_guc"


@db
def test_start_errors(api):
    client, fake = api
    r = client.post("/api/runs", json={"scenarioId": "Uzun boşta bekleme"})
    assert r.status_code == 422 and "desteklenmiyor" in r.json()["detail"]
    assert client.post("/api/runs", json={}).status_code == 422
    fake.online = False
    r = client.post("/api/runs", json={"scenarioId": "normal"})
    assert r.status_code == 503


def test_scenarios_list():
    ids = [s["id"] for s in TestClient(app).get("/api/scenarios").json()]
    assert ids[:3] == ["normal", "yuksek_guc", "beklenmeyen_durus"]


# ---------------- 3) Kontrol programı + gerçek publisher ----------------

PROJE_KOKU = Path(__file__).resolve().parent.parent


def _broker_available() -> bool:
    import socket
    try:
        socket.create_connection(("localhost", 1883), timeout=1).close()
        return True
    except OSError:
        return False


agent_test = pytest.mark.skipif(
    not _broker_available() or not (PROJE_KOKU / "mqtt" / "publisher.py").exists(),
    reason="Mosquitto çalışmıyor ya da mqtt/publisher.py bulunamadı")


@agent_test
def test_agent_with_real_publisher():
    import threading
    from backend.sim_agent import SimulationAgent
    from backend.sim_control import SimulationControl

    agent = SimulationAgent()
    agent.connect()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            agent.tick()
            time.sleep(0.1)

    threading.Thread(target=loop, daemon=True).start()
    ctl = SimulationControl()
    ctl.start()
    code = f"PYTEST-AGENT-{uuid.uuid4().hex[:6]}"
    max_alert = None
    if _db_available():
        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM alerts")
            max_alert = cur.fetchone()["m"]
    try:
        deadline = time.time() + 10
        while not ctl.agent_online() and time.time() < deadline:
            time.sleep(0.1)
        assert ctl.agent_online()

        # Bilinmeyen senaryo reddedilir
        with pytest.raises(ControlError) as exc:
            ctl.send("start", code, "yok_boyle_senaryo")
        assert exc.value.kind == "bad_request"

        ctl.send("start", code, "yuksek_guc")
        assert ctl.running_code() == code
        assert agent.process.poll() is None            # publisher gerçekten çalışıyor

        # Aynı anda ikinci çalışma reddedilir
        with pytest.raises(ControlError) as exc:
            ctl.send("start", code + "-2", "normal")
        assert exc.value.kind == "conflict"

        time.sleep(2)
        ctl.send("stop", code)
        finished = ctl.last_finished()
        assert finished["simulation_code"] == code
        assert finished["reason"] == "user_stopped"
        assert finished["exit_code"] == 0              # "cikis" ile düzgün kapandı
        assert ctl.running_code() is None
    finally:
        ctl.stop()
        stop.set()
        if agent.is_running():
            agent.process.kill()
        agent.client.loop_stop()
        agent.client.disconnect()
        # Subscriber açıksa publisher'ın gönderdiği deneme verisi veritabanına yazılmış olabilir
        if max_alert is not None:
            time.sleep(2)                                # kuyruktaki kayıtlar yazılsın
            with get_cursor() as cur:
                cur.execute("DELETE FROM alerts WHERE id > %s", (max_alert,))
                cur.execute("SELECT id FROM simulations WHERE simulation_code LIKE %s",
                            (code + "%",))
                for row in cur.fetchall():
                    cur.execute("DELETE FROM measurements WHERE simulation_id = %s", (row["id"],))
                    cur.execute("DELETE FROM simulations WHERE id = %s", (row["id"],))
