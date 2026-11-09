"""
Web paneli için veri katmanı.

Sözleşmedeki "çalışma" (run) bizim veritabanımızdaki bir simülasyondur
(simulations tablosu). Çalışmanın durumu; ended_at alanı, simülasyon kontrol
programının bildirdiği durum ve son ölçüm zamanından çıkarılıyor (run_status).
"""
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from backend.alerts import mapping
from backend.database import get_cursor

# Bu süre boyunca ölçüm gelmeyen çalışma "bitmiş" sayılır
RUN_TIMEOUT_S = 30.0

# Makine durumları: veritabanı -> panel
STATUS_MAP = {"working": "running", "idle": "idle", "stopped": "stopped"}

# Grafikte nokta üzerinde işaretlenen uyarı türleri (panel türleriyle)
POINT_ALERT_TYPES = {"power_limit", "ai_anomaly"}


# ---------- Saf hesaplamalar (veritabanından bağımsız, ayrıca test ediliyor) ----------

def run_status(ended_at: Optional[datetime], last_data_at: Optional[datetime], now: datetime,
               code: Optional[str] = None, running_code: Optional[str] = None,
               last_finished: Optional[Dict] = None) -> str:
    """
    Çalışma durumu (öncelik sırasıyla):
      1. ended_at dolu          -> user_stopped (ended_at'i yalnızca kullanıcı durdurması doldurur)
      2. kontrol programı bu çalışmayı yürütüyor -> running
      3. kontrol programı bu çalışmanın bittiğini bildirdi -> completed / error
      4. panel dışından başlatılmış (terminalden publisher): son veri yeniyse running
      5. aksi halde -> completed
    """
    if ended_at is not None:
        return "user_stopped"
    if code and running_code == code:
        return "running"
    if code and last_finished and last_finished.get("simulation_code") == code:
        reason = last_finished.get("reason")
        return reason if reason in ("error", "user_stopped") else "completed"
    if last_data_at is not None and (now - last_data_at).total_seconds() <= RUN_TIMEOUT_S:
        return "running"
    return "completed"


def counter_delta(start: Optional[Dict], end: Optional[Dict]) -> Dict:
    """
    Birikimli sayaçlardan aralık değeri: bitiş - başlangıç.
    Sayaçlar toplanmaz (sözleşme: energyKwh = endCounter - startCounter).
    """
    def diff(key):
        if end is None or end.get(key) is None:
            return None
        start_value = (start or {}).get(key) or 0
        return end[key] - start_value

    energy = diff("energy_kwh")
    parts = diff("completed_parts")
    running, idle, elapsed = diff("work_s"), diff("idle_s"), diff("end_s")
    # Duruş = geçen süre - çalışma - boşta (aralıktaki farklarla)
    stopped = (round(max(0.0, elapsed - running - idle), 3)
               if None not in (running, idle, elapsed) else None)
    return {
        "energyKwh": round(energy, 6) if energy is not None else None,
        "productionCount": parts,
        "energyPerPartKwh": round(energy / parts, 6) if energy is not None and parts else None,
        "runningSeconds": running,
        "idleSeconds": idle,
        "stoppedSeconds": stopped,
    }


def marks_point(alert_type: str, bucket_working: bool) -> bool:
    """
    Grafik noktası bu uyarıyla işaretlensin mi?
    Güç sınırı (kural) uyarısı arıza boyunca açık kalır, ama yalnızca kesim
    sırasındaki noktalar işaretlenir; boşta fazındaki düşük güç noktaları anomali değildir.
    """
    return alert_type != "power_limit" or bucket_working


def stopped_seconds(row: Dict) -> Optional[float]:
    """Geçen süreden çalışma ve boşta sürelerini çıkararak durma süresini bulur."""
    if row.get("end_s") is None or row.get("work_s") is None or row.get("idle_s") is None:
        return None
    return round(max(0.0, row["end_s"] - row["work_s"] - row["idle_s"]), 3)


# ---------- Veritabanı sorguları ----------

class PanelRepository:

    def __init__(self, control=None):
        # Simülasyon kontrol istemcisi (sim_control.control); testlerde sahtesi verilebilir
        if control is None:
            from backend.sim_control import control as default_control
            control = default_control
        self.control = control

    def now(self) -> datetime:
        return datetime.now()

    # Çalışmalar

    def _run_rows(self, run_id: Optional[int] = None) -> List[Dict]:
        sql = """
            SELECT s.id, s.simulation_code, s.scenario, s.started_at, s.ended_at,
                   MIN(m.ts) AS first_ts, MAX(m.ts) AS last_data_at, MAX(m.end_s) AS elapsed_s
            FROM simulations s
            LEFT JOIN measurements m ON m.simulation_id = s.id
        """
        params: tuple = ()
        if run_id is not None:
            sql += " WHERE s.id = %s"
            params = (run_id,)
        sql += " GROUP BY s.id ORDER BY COALESCE(s.started_at, MIN(m.ts)) DESC, s.id DESC"
        with get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _to_run(self, row: Dict, now: datetime) -> Dict:
        status = run_status(row["ended_at"], row["last_data_at"], now, row["simulation_code"],
                            self.control.running_code(), self.control.last_finished())
        ended = row["ended_at"] or (row["last_data_at"] if status != "running" else None)
        return {
            "runId": str(row["id"]),
            "simulationCode": row["simulation_code"],
            "scenarioId": row["scenario"],
            "status": status,
            "startedAt": row["started_at"] or row["first_ts"],
            "endedAt": ended,
            "elapsedSeconds": row["elapsed_s"],
            "lastDataAt": row["last_data_at"],
        }

    def list_runs(self) -> List[Dict]:
        now = self.now()
        return [self._to_run(r, now) for r in self._run_rows()]

    def get_run(self, run_id: int) -> Optional[Dict]:
        rows = self._run_rows(run_id)
        return self._to_run(rows[0], self.now()) if rows else None

    def current_run(self) -> Optional[Dict]:
        for run in self.list_runs():
            if run["status"] == "running":
                return run
        return None

    # Başlat / durdur

    def wait_for_run(self, simulation_code: str, timeout: float = 15.0) -> Optional[int]:
        """
        Subscriber simülasyon kaydını ilk ölçüm geldiğinde oluşturuyor;
        kayıt görünene kadar kısa aralıklarla bekler.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with get_cursor() as cur:
                cur.execute("SELECT id FROM simulations WHERE simulation_code = %s", (simulation_code,))
                row = cur.fetchone()
            if row:
                return row["id"]
            time.sleep(0.2)
        return None

    def set_scenario(self, run_id: int, scenario_id: str) -> None:
        with get_cursor() as cur:
            cur.execute("UPDATE simulations SET scenario = %s WHERE id = %s", (scenario_id, run_id))

    def mark_user_stopped(self, run_id: int) -> None:
        with get_cursor() as cur:
            cur.execute("UPDATE simulations SET ended_at = NOW(3) WHERE id = %s AND ended_at IS NULL",
                        (run_id,))

    # Makineler ve ölçümler

    def machines(self) -> List[Dict]:
        with get_cursor() as cur:
            cur.execute("SELECT id, machine_code, name FROM machines ORDER BY id")
            return cur.fetchall()

    def latest_in_run(self, run_id: int, machine_id: int) -> Optional[Dict]:
        with get_cursor() as cur:
            cur.execute("""
                SELECT ts, phase, status, power_kw, energy_kwh, completed_parts,
                       work_s, idle_s, end_s
                FROM measurements
                WHERE simulation_id = %s AND machine_id = %s
                ORDER BY seq DESC LIMIT 1""", (run_id, machine_id))
            return cur.fetchone()

    def counters_at(self, run_id: int, machine_id: int, seconds: Optional[float]) -> Optional[Dict]:
        """Verilen simülasyon saniyesindeki (ya da hemen öncesindeki) sayaç değerleri."""
        sql = """SELECT energy_kwh, completed_parts, work_s, idle_s, end_s
                 FROM measurements WHERE simulation_id = %s AND machine_id = %s"""
        params: tuple = (run_id, machine_id)
        if seconds is not None:
            sql += " AND end_s <= %s"
            params += (seconds,)
        sql += " ORDER BY seq DESC LIMIT 1"
        with get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def average_power(self, run_id: int, machine_id: int, start: float, end: Optional[float]) -> Optional[float]:
        sql = """SELECT AVG(power_kw) AS p FROM measurements
                 WHERE simulation_id = %s AND machine_id = %s AND end_s > %s"""
        params: tuple = (run_id, machine_id, start)
        if end is not None:
            sql += " AND end_s <= %s"
            params += (end,)
        with get_cursor() as cur:
            cur.execute(sql, params)
            p = cur.fetchone()["p"]
            return round(p, 3) if p is not None else None

    def series(self, run_id: int, machine_id: int, start: float, end: Optional[float],
               step: float) -> List[Dict]:
        """
        Grafik noktaları. 10 Hz veri her 'step' saniyelik dilimde tek noktaya indirilir:
        güç ortalaması, sayaçların dilim sonundaki değeri.
        """
        sql = """
            SELECT MAX(end_s) AS elapsed, AVG(power_kw) AS power, MAX(energy_kwh) AS energy,
                   MAX(completed_parts) AS parts, MIN(ts) AS ts_start, MAX(ts) AS ts_end,
                   MAX(status = 'working') AS working
            FROM measurements
            WHERE simulation_id = %s AND machine_id = %s AND end_s IS NOT NULL AND end_s >= %s
        """
        params: tuple = (run_id, machine_id, start)
        if end is not None:
            sql += " AND end_s <= %s"
            params += (end,)
        sql += " GROUP BY FLOOR(end_s / %s) ORDER BY elapsed"
        params += (step,)
        with get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def elapsed_at(self, run_id: int, machine_id: int, when: datetime) -> Optional[float]:
        """Gerçek bir zamanın, çalışmadaki simülasyon saniyesi karşılığı."""
        with get_cursor() as cur:
            cur.execute("""SELECT end_s FROM measurements
                           WHERE simulation_id = %s AND machine_id = %s AND ts <= %s
                           ORDER BY ts DESC LIMIT 1""", (run_id, machine_id, when))
            row = cur.fetchone()
            return row["end_s"] if row else None

    # Uyarılar

    def alert_rows(self, machine_id: Optional[int] = None, limit: int = 1000) -> List[Dict]:
        sql = "SELECT id, machine_id, alert_type, severity, message, created_at, resolved_at FROM alerts"
        params: tuple = ()
        if machine_id is not None:
            sql += " WHERE machine_id = %s"
            params = (machine_id,)
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params += (limit,)
        with get_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def panel_alerts(self, machine_id: Optional[int] = None, limit: int = 1000,
                     with_elapsed: bool = True) -> List[Dict]:
        """
        alerts tablosundaki kayıtları sözleşme formatına çevirir ve çalışmalarına bağlar.
        with_elapsed=False: simülasyon saniyesi hesaplanmaz (her uyarı için bir sorgu daha gerekiyor).
        """
        runs = self._run_rows()
        by_code = {r["simulation_code"]: r for r in runs}
        result = []
        for row in self.alert_rows(machine_id=machine_id, limit=limit):
            run = self._find_run(row, runs, by_code)
            result.append({
                "id": str(row["id"]),
                "runId": str(run["id"]) if run else None,
                "machineId": str(row["machine_id"]),
                "type": mapping.panel_type(row["alert_type"], row["message"]),
                "description": mapping.description(row["message"]),
                "source": mapping.source_of(row["message"]),
                "severity": row["severity"],
                "startedAt": row["created_at"],
                "closedAt": row["resolved_at"],
                "status": "active" if row["resolved_at"] is None else "closed",
                "elapsedSeconds": (self.elapsed_at(run["id"], row["machine_id"], row["created_at"])
                                   if run and with_elapsed else None),
            })
        return result

    @staticmethod
    def _find_run(alert: Dict, runs: List[Dict], by_code: Dict) -> Optional[Dict]:
        # Yapay zekâ uyarısı simülasyon kodunu mesajında taşıyor
        code = mapping.ai_simulation_code(alert["message"])
        if code:
            return by_code.get(code)
        # Kural uyarısı: uyarının açıldığı anda veri akan çalışma
        when = alert["created_at"]
        for run in runs:  # en yeniden eskiye
            start = run["started_at"] or run["first_ts"]
            last = run["last_data_at"]
            if start and last and start <= when <= last + timedelta(seconds=RUN_TIMEOUT_S):
                return run
        return None
