"""
FastAPI endpoint testleri.
Çalıştırma (proje kök klasöründen):  python -m pytest testler -v
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.repository import SampleRepository, get_repository

client = TestClient(app)


@pytest.fixture(autouse=True, scope="module")
def use_sample_data():
    # Bu dosyadaki testler veritabanından bağımsız: örnek veriyle çalışıyor
    app.dependency_overrides[get_repository] = lambda: SampleRepository()
    yield
    app.dependency_overrides.clear()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_machines_returns_three():
    r = client.get("/machines")
    assert r.status_code == 200
    codes = [m["machine_code"] for m in r.json()]
    assert codes == ["M1", "M2", "M3"]


def test_get_machine_fields_match_schema():
    r = client.get("/machines/1")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "machine_code", "name", "p_idle_kw", "efficiency"}
    assert body["p_idle_kw"] == 3.2


def test_unknown_machine_returns_404():
    assert client.get("/machines/99").status_code == 404
    assert client.get("/machines/99/latest").status_code == 404
    assert client.get("/measurements?machine_id=99").status_code == 404


def test_measurements_filter_and_limit():
    r = client.get("/measurements?machine_id=2&limit=5")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5
    assert all(row["machine_id"] == 2 for row in rows)
    seqs = [row["seq"] for row in rows]
    assert seqs == sorted(seqs)


def test_measurement_limit_validation():
    assert client.get("/measurements?limit=0").status_code == 422


def test_latest_measurement():
    r = client.get("/machines/3/latest")
    assert r.status_code == 200
    assert r.json()["machine_id"] == 3


def test_measurement_power_matches_formula():
    # Normal kesmede M1: 3.2 + 11.52/0.72 = 19.2 kW (küçük sapma payıyla)
    rows = client.get("/measurements?machine_id=1&limit=5000").json()
    normal = [r["power_kw"] for r in rows if r["phase"] == "normal_kesme"]
    assert all(abs(p - 19.2) < 0.1 for p in normal)


def test_alert_rules_listed():
    r = client.get("/alerts/rules")
    assert r.status_code == 200
    types = {rule["alert_type"] for rule in r.json()}
    assert {"makine_durdu", "veri_yok", "yuksek_guc", "uzun_bosta"} <= types


def test_alert_preview_runs():
    r = client.get("/alerts/preview/1")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_alert_list_and_check_with_sample_data():
    assert client.get("/alerts").status_code == 200
    assert client.get("/alerts?machine_id=99").status_code == 404
    r = client.post("/alerts/check")
    assert r.status_code == 200
    assert [x["machine_id"] for x in r.json()] == [1, 2, 3]


def test_measurements_simulation_filter():
    rows = client.get("/measurements?simulation_id=1&limit=5").json()
    assert len(rows) == 5 and all(r["simulation_id"] == 1 for r in rows)
    assert client.get("/measurements?simulation_id=999").json() == []
