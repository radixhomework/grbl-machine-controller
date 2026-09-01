"""Home Assistant MQTT bridge (§7): discovery + state mirroring + commands."""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from ..core.state import MachineState


class MQTTBridge:
    """Publishes retained HA discovery configs, mirrors state at ~1 Hz,
    and routes `<base_topic>/cmd/<action>` messages into the command API."""

    def __init__(self, state: MachineState, config: dict,
                 command_handler: Optional[Callable[[str, str], None]] = None):
        if mqtt is None:
            raise RuntimeError("paho-mqtt is not installed")
        self.state = state
        self.config = config
        self.command_handler = command_handler or (lambda a, v: None)
        self.base = config.get("base_topic", "cnc")
        self.discovery_prefix = config.get("discovery_prefix", "homeassistant")
        self._client = mqtt.Client()
        if config.get("username"):
            self._client.username_pw_set(config["username"], config.get("password") or None)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._last_publish = 0.0
        self._lock = threading.Lock()
        state.subscribe(self._on_state_change)
        self._discovery_published = False

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._client.connect_async(self.config["host"], int(self.config.get("port", 1883)), keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(f"{self.base}/cmd/#")
        if not self._discovery_published:
            self._publish_discovery()
            self._discovery_published = True

    # ---- discovery ---------------------------------------------------------
    def _discovery(self, component: str, entity_id: str, payload: dict) -> None:
        topic = f"{self.discovery_prefix}/{component}/{self.base}/{entity_id}/config"
        payload.setdefault("unique_id", f"{self.base}_{entity_id}")
        payload.setdefault("name", entity_id.replace("_", " ").title())
        self._client.publish(topic, json.dumps(payload), retain=True)

    def _publish_discovery(self) -> None:
        st = f"{self.base}/state"
        cmd = f"{self.base}/cmd"
        d = self._discovery

        d("sensor", "machine_status", {"state_topic": st, "value_template": "{{ value_json.status }}"})
        for ax in "xyz":
            d("sensor", f"{ax}_position", {
                "state_topic": st,
                "value_template": f"{{{{ value_json.{ax} }}}}",
                "unit_of_measurement": "mm",
            })
        d("sensor", "spindle_rpm", {"state_topic": st, "value_template": "{{ value_json.spindle }}",
                                    "unit_of_measurement": "rpm"})
        d("sensor", "job_progress", {"state_topic": st, "value_template": "{{ value_json.progress }}",
                                     "unit_of_measurement": "%"})
        d("binary_sensor", "job_running", {"state_topic": st, "value_template": "{{ value_json.running }}"})
        d("binary_sensor", "alarm_active", {"state_topic": st, "value_template": "{{ value_json.alarm }}"})
        for btn in ("home", "unlock", "pause", "resume", "stop"):
            d("button", btn, {"command_topic": f"{cmd}/{btn}"})
        for num, lo, hi in (("feed_override", 10, 200), ("spindle_override", 10, 200)):
            d("number", num, {
                "command_topic": f"{cmd}/{num}",
                "state_topic": st,
                "value_template": f"{{{{ value_json.{num} }}}}",
                "min": lo, "max": hi,
            })

    # ---- state mirroring (throttled ~1 Hz) ---------------------------------
    def _on_state_change(self, new: MachineState, old: MachineState) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_publish < 1.0:
                return
            self._last_publish = now
        self._publish_state(new)

    def _publish_state(self, s: MachineState) -> None:
        payload = {
            "status": s.grbl_state,
            "x": round(s.mpos.x, 3), "y": round(s.mpos.y, 3), "z": round(s.mpos.z, 3),
            "spindle": round(s.spindle_rpm, 0),
            "progress": round(s.job_progress * 100, 1),
            "running": s.job_running,
            "alarm": s.grbl_state == "Alarm",
            "feed_override": s.overrides.feed,
            "spindle_override": s.overrides.spindle,
        }
        self._client.publish(f"{self.base}/state", json.dumps(payload), retain=True)

    # ---- commands from HA ---------------------------------------------------
    def _on_message(self, client, userdata, msg):
        action = msg.topic.split("/")[-1]
        value = msg.payload.decode("ascii", "replace")
        try:
            self.command_handler(action, value)
        except Exception:
            import traceback
            traceback.print_exc()
