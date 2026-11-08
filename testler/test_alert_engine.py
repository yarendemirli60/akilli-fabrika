"""
Uyarı motoru birim testleri.
Veritabanı yerine bellekte çalışan küçük bir sahte repository kullanılıyor;
böylece "uyarı oluştu -> tekrar yazılmadı -> normale döndü" akışı
adım adım kontrol edilebiliyor.
"""
from datetime import datetime, timedelta

from backend.alerts import engine
from backend.schemas import AlertRecord, Machine, Measurement

T0 = datetime(2026, 11, 7, 10, 0, 0)
M1 = Machine(id=1, machine_code="M1", name="15 Yıllık Torna", p_idle_kw=3.2, efficiency=0.72)


class FakeRepo:
    def __init__(self):
        self.measurements = []
        self.alerts = []

    # Ölçümleri verilen güç değerleriyle değiştir (10 Hz)
    def set_power(self, powers, status="working"):
        self.set_readings([(p, status) for p in powers])

    def set_readings(self, readings, simulation_id=1, start=T0):
        """readings: [(güç, durum), ...] (10 Hz)"""
        self.measurements = [
            Measurement(id=i, simulation_id=simulation_id, machine_id=1, seq=i,
                        ts=start + timedelta(seconds=i * 0.1), duration_s=0.1,
                        status=status, power_kw=p)
            for i, (p, status) in enumerate(readings, start=1)
        ]

    def get_machines(self):
        return [M1]

    def get_measurements(self, machine_id=None, limit=100):
        return self.measurements[-limit:]

    def now(self):
        return self.measurements[-1].ts if self.measurements else T0

    def get_open_alerts(self, machine_id):
        return [a for a in self.alerts if a.machine_id == machine_id and a.resolved_at is None]

    def insert_alert(self, alert):
        self.alerts.append(AlertRecord(id=len(self.alerts) + 1,
                                       **alert.model_dump(exclude={"created_at"}),
                                       created_at=self.now()))

    def resolve_alert(self, alert_id):
        self.alerts[alert_id - 1].resolved_at = self.now()


def test_alert_created_once_then_resolved():
    repo = FakeRepo()

    # 1) Arızalı kesme: yüksek güç uyarısı oluşur
    repo.set_power([25.6] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == ["yuksek_guc"]
    assert len(repo.alerts) == 1

    # 2) Arıza sürüyor: aynı uyarı ikinci kez yazılmaz
    result = engine.run_once(repo)
    assert result[0]["created"] == []
    assert len(repo.alerts) == 1

    # 3) Normale dönüş: açık uyarı kapatılır
    repo.set_power([19.2] * 10)
    result = engine.run_once(repo)
    assert result[0]["resolved"] == ["yuksek_guc"]
    assert repo.alerts[0].resolved_at is not None


def test_new_alert_after_problem_returns():
    repo = FakeRepo()
    repo.set_power([25.6] * 10)
    engine.run_once(repo)
    repo.set_power([19.2] * 10)
    engine.run_once(repo)

    # Sorun tekrar başlarsa yeni bir kayıt açılır (eski kayıt kapalı kalır)
    repo.set_power([25.6] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == ["yuksek_guc"]
    assert len(repo.alerts) == 2
    assert repo.alerts[0].resolved_at is not None
    assert repo.alerts[1].resolved_at is None


def test_normal_operation_creates_no_alerts():
    repo = FakeRepo()
    repo.set_power([19.2] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == [] and result[0]["resolved"] == []
    assert repo.alerts == []


def test_energy_alert_not_auto_resolved():
    # Motorun değerlendirmediği uyarı türlerine dokunulmaz
    repo = FakeRepo()
    repo.set_power([19.2] * 10)
    repo.alerts.append(AlertRecord(id=1, machine_id=1, alert_type="yuksek_enerji_parca",
                                   severity="warning", message="test", created_at=T0))
    result = engine.run_once(repo)
    assert result[0]["resolved"] == []
    assert repo.alerts[0].resolved_at is None


def test_high_power_stays_open_while_idle():
    # Arıza sırasında makine boşta fazına geçerse uyarı kapanmaz
    repo = FakeRepo()
    repo.set_power([25.6] * 10)
    engine.run_once(repo)
    repo.set_power([3.2] * 10, status="idle")
    result = engine.run_once(repo)
    assert result[0]["resolved"] == []
    assert repo.alerts[0].resolved_at is None

    # Sonraki kesim de arızalıysa yeni kayıt açılmaz (aynı uyarı sürüyor)
    repo.set_power([25.6] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == []
    assert len(repo.alerts) == 1

    # Takım değiştirilip normal kesime dönülünce kapanır
    repo.set_power([19.2] * 10)
    result = engine.run_once(repo)
    assert result[0]["resolved"] == ["yuksek_guc"]


def test_ai_alerts_are_not_touched():
    # Yapay zekânın açtığı uzun_bosta uyarısı motor tarafından kapatılmamalı
    # ve motorun kendi uyarısını açmasına engel olmamalı
    repo = FakeRepo()
    repo.alerts.append(AlertRecord(id=1, machine_id=1, alert_type="uzun_bosta", severity="warning",
                                   message="AI|abc|Sim=SIM-1 | Kesintisiz boşta kalma süresi sınırı aşıldı.",
                                   created_at=T0))
    repo.set_power([19.2] * 10)
    result = engine.run_once(repo)
    assert result[0]["resolved"] == []
    assert repo.alerts[0].resolved_at is None

    repo.alerts.append(AlertRecord(id=2, machine_id=1, alert_type="yuksek_guc", severity="warning",
                                   message="AI|xyz|Sim=SIM-1 | test", created_at=T0))
    repo.set_power([25.6] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == ["yuksek_guc"]


def test_high_power_does_not_flap_at_phase_change():
    # Arızalı takım: boşta fazından kesmeye geçişin ilk anında son 10 ölçümün
    # bir kısmı hâlâ boşta değeri; ortalama düşük çıksa da uyarı kapanmamalı
    repo = FakeRepo()
    repo.set_power([25.6] * 10)
    engine.run_once(repo)
    repo.set_readings([(4.2, "idle")] * 7 + [(25.6, "working")] * 3)
    result = engine.run_once(repo)
    assert result[0]["resolved"] == []
    repo.set_power([25.6] * 10)
    result = engine.run_once(repo)
    assert result[0]["created"] == []
    assert len(repo.alerts) == 1                      # tek kayıt, açılıp kapanma yok


def test_previous_run_does_not_count_as_idle():
    # Önceki simülasyon boşta bitti, 2 saat sonra yeni simülasyon boşta başladı:
    # aradaki süre "uzun boşta kalma" sayılmamalı
    repo = FakeRepo()
    old = [(3.2, "idle")] * 10
    new_start = T0 + timedelta(hours=2)
    repo.set_readings(old, simulation_id=1)
    previous = list(repo.measurements)
    repo.set_readings([(3.2, "idle")] * 10, simulation_id=2, start=new_start)
    repo.measurements = previous + repo.measurements
    result = engine.run_once(repo)
    assert "uzun_bosta" not in result[0]["created"]
