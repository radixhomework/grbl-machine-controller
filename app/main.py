"""Application entry point.

Usage:
  python -m app.main                    # real hardware from config.yaml
  python -m app.main --fake             # built-in GRBL simulator (no hardware)
  python -m app.main --port COM3        # override serial port
  python -m app.main --headless         # no UI (core + MQTT only)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys

import yaml


def load_config(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def build_core(config: dict, fake: bool, port_override: str | None):
    from .core.fake_grbl import FakeGRBL
    from .core.grbl_adapter import GRBLAdapter
    from .core.job_manager import JobManager
    from .core.serial_transport import FakeTransport, SerialTransport
    from .core.state import MachineState

    state = MachineState()
    if fake:
        fake_grbl = FakeGRBL()
        transport = fake_grbl.transport
    else:
        serial_cfg = config.get("serial", {})
        port = port_override or serial_cfg.get("port", "/dev/ttyUSB0")
        transport = SerialTransport(
            port, int(serial_cfg.get("baud", 115200)),
            on_disconnected=lambda: state.update(connected=False, grbl_state="Offline"),
        )
    adapter = GRBLAdapter(transport, state,
                          poll_interval=float(config.get("serial", {}).get("status_poll_interval", 0.15)))
    if fake:
        # route fake GRBL output into the adapter's rx queue
        transport.on_line = adapter._rx_queue.put
    # FakeTransport needs its on_line routed to the adapter: wire after construction
    if fake:
        transport.on_line = adapter._rx_queue.put
    jobs = JobManager(adapter, state)
    return state, adapter, jobs


def start_mqtt(config: dict, state, jobs, adapter):
    mqtt_cfg = config.get("mqtt", {})
    if not mqtt_cfg.get("enabled"):
        return None
    from .ha.mqtt_bridge import MQTTBridge

    def handle(action: str, value: str):
        try:
            if action == "home":
                adapter.home_all()
            elif action == "unlock":
                jobs.unlock()
            elif action == "pause":
                jobs.pause()
            elif action == "resume":
                jobs.resume()
            elif action == "stop":
                jobs.stop()
            elif action == "feed_override":
                adapter.set_feed_override(int(float(value)))
            elif action == "spindle_override":
                adapter.set_spindle_override(int(float(value)))
        except Exception:
            import traceback
            traceback.print_exc()

    bridge = MQTTBridge(state, mqtt_cfg, command_handler=handle)
    bridge.start()
    return bridge


def main() -> int:
    from . import __version__

    parser = argparse.ArgumentParser(description="GRBL machine controller")
    parser.add_argument("--version", action="version", version=f"GRBL Machine Controller {__version__}")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--port", help="override serial port")
    parser.add_argument("--fake", action="store_true", help="run against the built-in GRBL simulator")
    parser.add_argument("--headless", action="store_true", help="run core + MQTT without the Qt UI")
    args = parser.parse_args()

    config = load_config(args.config)
    fake = args.fake or "CNCCI_FAKE" in os.environ or os.environ.get("CNCPI_FAKE") == "1"
    state, adapter, jobs = build_core(config, fake, args.port)
    adapter.connect()

    mqtt_bridge = start_mqtt(config, state, jobs, adapter)

    try:
        if args.headless:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            print("Headless mode. Ctrl-C to quit.")
            signal.pause() if hasattr(signal, "pause") else _spin(state)
            return 0
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from .main_window import LOGO, MainWindow

        app = QApplication(sys.argv)
        if os.path.exists(LOGO):
            app.setWindowIcon(QIcon(LOGO))
        win = MainWindow(adapter, state, jobs, config, config_path=args.config)
        win.show()
        code = app.exec()
        return code
    finally:
        if mqtt_bridge:
            mqtt_bridge.stop()
        adapter.close()


def _spin(state):
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
