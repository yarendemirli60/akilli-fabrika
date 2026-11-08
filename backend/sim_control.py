"""
API tarafındaki simülasyon kontrol istemcisi.

Kontrol programının (sim_agent.py) durum mesajını dinler ve komut gönderir.
API açılırken bir kez bağlanır (main.py içindeki lifespan). Broker'a
bağlanılamazsa API yine çalışır; yalnızca başlat/durdur istekleri 503 döner.
"""
import json
import os
import threading
import uuid
from typing import Optional

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from backend.sim_protocol import CMD_TOPIC, STATUS_TOPIC

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))


class ControlError(Exception):
    """
    Komut kontrol programı tarafından reddedildi ya da cevap gelmedi.
    kind: "conflict" (zaten çalışıyor / çalışmıyor), "bad_request", "unavailable"
    """
    def __init__(self, message: str, kind: str = "unavailable"):
        super().__init__(message)
        self.kind = kind


class SimulationControl:
    def __init__(self):
        self._status: Optional[dict] = None
        self._cond = threading.Condition()
        self._client = None

    # ---------- Bağlantı ----------

    def start(self):
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=f"akilli-fabrika-api-{uuid.uuid4().hex[:6]}")
        self._client.on_connect = lambda c, u, f, rc, p: c.subscribe(STATUS_TOPIC, qos=1)
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)   # API açılışını bekletmez
        self._client.loop_start()

    def stop(self):
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_message(self, client, userdata, msg):
        try:
            status = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        with self._cond:
            self._status = status
            self._cond.notify_all()

    # ---------- Durum ----------

    def status(self) -> Optional[dict]:
        with self._cond:
            return dict(self._status) if self._status else None

    def agent_online(self) -> bool:
        s = self.status()
        return bool(s) and s.get("agent") == "online"

    def running_code(self) -> Optional[str]:
        s = self.status()
        if s and s.get("agent") == "online" and s.get("state") == "running":
            return s.get("simulation_code")
        return None

    def last_finished(self) -> Optional[dict]:
        s = self.status()
        return (s or {}).get("last_finished")

    # ---------- Komut ----------

    def send(self, action: str, simulation_code: str, scenario: Optional[str] = None,
             timeout: float = 15.0) -> dict:
        """Komutu gönderir ve aynı command_id ile gelen cevabı bekler."""
        if self._client is None or not self._client.is_connected():
            raise ControlError("MQTT broker'a bağlı değil. Mosquitto çalışıyor mu?")
        if not self.agent_online():
            raise ControlError("Simülasyon kontrol programı çalışmıyor "
                               "(python -m backend.sim_agent).")
        command_id = uuid.uuid4().hex
        payload = {"command_id": command_id, "action": action,
                   "simulation_code": simulation_code, "scenario": scenario}
        with self._cond:
            self._client.publish(CMD_TOPIC, json.dumps(payload), qos=1)
            answered = self._cond.wait_for(
                lambda: ((self._status or {}).get("last_command") or {}).get("id") == command_id,
                timeout=timeout)
            if not answered:
                raise ControlError("Kontrol programı zamanında cevap vermedi.")
            result = self._status["last_command"]
        if not result.get("ok"):
            raise ControlError(result.get("error") or "Komut reddedildi.",
                               result.get("kind") or "unavailable")
        return self.status()


# API sürecinde tek örnek (main.py başlatır)
control = SimulationControl()
