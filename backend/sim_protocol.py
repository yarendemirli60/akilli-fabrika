"""
API ile simülasyon kontrol programı (sim_agent.py) arasındaki MQTT protokolü.

Komut  : factory/control/simulation/cmd     (QoS 1, saklanmaz)
         {"command_id": "...", "action": "start" | "stop",
          "simulation_code": "SIM-...", "scenario": "normal"}

Durum  : factory/control/simulation/status  (QoS 1, saklanan / retained)
         {"agent": "online" | "offline",
          "state": "idle" | "running",
          "simulation_code": ..., "scenario": ..., "started_at": ...,
          "last_finished": {"simulation_code", "scenario", "reason", "exit_code", "ended_at"},
          "last_command": {"id", "action", "ok", "error"},
          "updated_at": ...}

- Durum mesajı "retained" olduğu için API sonradan bağlansa bile son durumu hemen alır.
- Program beklenmedik şekilde kapanırsa broker, önceden bırakılan "son vasiyet"
  (Last Will) mesajını yayınlar: {"agent": "offline"}.
- API her komuta benzersiz bir command_id verir; program sonucu
  last_command.id alanında aynı kimlikle bildirir (komut/onay eşleştirmesi).
- last_finished.reason: "completed" (kendiliğinden bitti), "user_stopped", "error".
"""
CMD_TOPIC = "factory/control/simulation/cmd"
STATUS_TOPIC = "factory/control/simulation/status"
