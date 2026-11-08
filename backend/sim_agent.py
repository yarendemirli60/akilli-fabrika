"""
Simülasyon kontrol programı.

Panelden gelen başlat/durdur komutlarını MQTT üzerinden alır ve
mqtt/publisher.py'yi ayrı bir süreç olarak çalıştırır. publisher.py ve
simulasyon.py dosyalarında hiçbir değişiklik gerektirmez; yalnızca
publisher'ın mevcut seçeneklerini kullanır:
  --sim-id  : simülasyon kodu (API kodu kendisi belirler)
  --csv     : kayıtlı veriyi yeniden oynatma
  "cikis"   : canlı simülasyonu düzgün kapatma komutu (standart girdiden)

Çalıştırma (proje kök klasöründen, sanal ortam açıkken):
    python -m backend.sim_agent
"""
import json
import os
import queue
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from backend import scenarios
from backend.sim_protocol import CMD_TOPIC, STATUS_TOPIC

PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
STOP_TIMEOUT_S = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class SimulationAgent:
    def __init__(self, publisher_path: Path = PROJE_KOKU / "mqtt" / "publisher.py",
                 python: str = sys.executable):
        self.publisher_path = publisher_path
        self.python = python
        self.commands: "queue.Queue[dict]" = queue.Queue()
        self.process = None
        self.current = None          # {"simulation_code", "scenario", "started_at"}
        self.pending = []            # [(çalıştırılacağı zaman, komut)]
        self.last_finished = None
        self.last_command = None
        self.client = None
        self.stopped_by_user = False

    # ---------- MQTT ----------

    def connect(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"akilli-fabrika-sim-agent-{uuid.uuid4().hex[:6]}")
        # Program beklenmedik şekilde kapanırsa broker bu mesajı yayınlar
        self.client.will_set(STATUS_TOPIC, json.dumps({"agent": "offline", "updated_at": _now()}),
                             qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(CMD_TOPIC, qos=1)
        self.publish_status()
        print(f"[KONTROL] MQTT'ye baglandi ({MQTT_HOST}:{MQTT_PORT}), komut bekleniyor.")

    def _on_message(self, client, userdata, msg):
        try:
            self.commands.put(json.loads(msg.payload.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            print("[KONTROL] Okunamayan komut yok sayildi.")

    def status(self) -> dict:
        return {
            "agent": "online",
            "state": "running" if self.is_running() else "idle",
            **({k: self.current[k] for k in ("simulation_code", "scenario", "started_at")}
               if self.is_running() else {"simulation_code": None, "scenario": None, "started_at": None}),
            "last_finished": self.last_finished,
            "last_command": self.last_command,
            "updated_at": _now(),
        }

    def publish_status(self):
        if self.client is not None:
            self.client.publish(STATUS_TOPIC, json.dumps(self.status(), ensure_ascii=False),
                                qos=1, retain=True)

    # ---------- Süreç yönetimi ----------

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, code: str, scenario_id: str):
        if self.is_running():
            raise RuntimeError(f"Zaten calisan bir simulasyon var: {self.current['simulation_code']}")
        scenario = scenarios.find(scenario_id)
        if scenario is None:
            raise ValueError(f"Bilinmeyen senaryo: {scenario_id}")

        args = [self.python, "-u", str(self.publisher_path), "--sim-id", code]
        if scenario["mode"] == "csv":
            args += ["--csv", str(PROJE_KOKU / scenario["file"]), "--hiz", "1"]
        self.process = subprocess.Popen(args, cwd=str(PROJE_KOKU), stdin=subprocess.PIPE,
                                        text=True, encoding="utf-8")
        self.stopped_by_user = False
        started = time.monotonic()
        self.pending = [(started + sec, cmd) for sec, cmd in scenario.get("commands", [])]
        self.current = {"simulation_code": code, "scenario": scenario["id"], "started_at": _now(),
                        "mode": scenario["mode"]}
        print(f"[KONTROL] Basladi: {code} | senaryo: {scenario['id']}")

    def send_to_simulation(self, command: str):
        if self.is_running() and self.current["mode"] == "live":
            try:
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
                print(f"[KONTROL] Simulasyona komut: {command}")
            except (BrokenPipeError, OSError):
                pass

    def stop(self, code: str):
        if not self.is_running() or self.current["simulation_code"] != code:
            raise RuntimeError("Bu simulasyon calismiyor.")
        self.stopped_by_user = True
        if self.current["mode"] == "live":
            self.send_to_simulation("cikis")     # düzgün kapanış
        else:
            self.process.terminate()             # CSV modunun komut girdisi yok
        try:
            self.process.wait(timeout=STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self._finished()

    def _finished(self):
        code = self.process.returncode
        if self.stopped_by_user:
            reason = "user_stopped"
        else:
            reason = "completed" if code == 0 else "error"
        self.last_finished = {"simulation_code": self.current["simulation_code"],
                              "scenario": self.current["scenario"], "reason": reason,
                              "exit_code": code, "ended_at": _now()}
        print(f"[KONTROL] Bitti: {self.current['simulation_code']} ({reason}, cikis kodu {code})")
        self.process, self.current, self.pending = None, None, []

    # ---------- Ana döngü ----------

    def handle(self, cmd: dict):
        action = cmd.get("action")
        result = {"id": cmd.get("command_id"), "action": action, "ok": True, "error": None, "kind": None}
        try:
            if action == "start":
                self.start(cmd["simulation_code"], cmd.get("scenario") or "")
            elif action == "stop":
                self.stop(cmd["simulation_code"])
            else:
                raise ValueError(f"Bilinmeyen komut: {action}")
        except RuntimeError as exc:                       # zaten çalışıyor / çalışmıyor
            result.update(ok=False, error=str(exc), kind="conflict")
        except (ValueError, KeyError) as exc:             # hatalı komut
            result.update(ok=False, error=str(exc), kind="bad_request")
        except OSError as exc:                            # publisher başlatılamadı
            result.update(ok=False, error=f"Publisher baslatilamadi: {exc}", kind="unavailable")
        if not result["ok"]:
            print(f"[KONTROL] Komut reddedildi: {result['error']}")
        self.last_command = result
        self.publish_status()

    def tick(self):
        """Bekleyen komutları işler, planlı senaryo komutlarını gönderir, süreci izler."""
        try:
            while True:
                self.handle(self.commands.get_nowait())
        except queue.Empty:
            pass

        if self.pending:
            now = time.monotonic()
            due = [c for t, c in self.pending if t <= now]
            self.pending = [(t, c) for t, c in self.pending if t > now]
            for command in due:
                self.send_to_simulation(command)

        if self.process is not None and self.process.poll() is not None:
            self._finished()             # süreç kendiliğinden bitti (CSV sonu ya da hata)
            self.publish_status()

    def run_forever(self):
        self.connect()
        try:
            while True:
                self.tick()
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n[KONTROL] Kapatiliyor...")
        finally:
            if self.is_running():
                try:
                    self.stop(self.current["simulation_code"])
                except RuntimeError:
                    pass
            self.client.publish(STATUS_TOPIC, json.dumps({"agent": "offline", "updated_at": _now()}),
                                qos=1, retain=True).wait_for_publish(timeout=2)
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    SimulationAgent().run_forever()
