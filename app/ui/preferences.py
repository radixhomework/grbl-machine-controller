"""Preferences dialog: edits config sections and saves back to config.yaml."""

from __future__ import annotations

import copy

import yaml
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox,
    QVBoxLayout,
)


class PreferencesDialog(QDialog):
    """Edits serial, defaults, MQTT, and tool-table config in one form.

    Call with (config, config_path). After accept(), config is updated in
    place and, if config_path is given, written back to the YAML file.
    """

    def __init__(self, config: dict, config_path: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(420, 520)
        self._config = config
        self._path = config_path

        lay = QVBoxLayout(self)
        serial = config.setdefault("serial", {})
        defaults = config.setdefault("defaults", {})
        mqtt = config.setdefault("mqtt", {})
        pcfg = config.setdefault("probe", {})

        gb_serial = QGroupBox("Serial")
        f = QFormLayout(gb_serial)
        self.port = QLineEdit(str(serial.get("port", "/dev/ttyUSB0")))
        self.baud = QSpinBox()
        self.baud.setRange(960, 460800)
        self.baud.setValue(int(serial.get("baud", 115200)))
        self.poll = QSpinBox()
        self.poll.setRange(10, 1000)
        self.poll.setValue(int(float(serial.get("status_poll_interval", 0.15)) * 1000))
        self.poll.setSuffix(" ms")
        f.addRow("Port", self.port)
        f.addRow("Baud", self.baud)
        f.addRow("Status poll", self.poll)
        lay.addWidget(gb_serial)

        gb_def = QGroupBox("Defaults")
        f = QFormLayout(gb_def)
        self.jog_feed = QSpinBox()
        self.jog_feed.setRange(1, 20000)
        self.jog_feed.setValue(int(defaults.get("jog_feed", 1000)))
        self.jog_feed.setSuffix(" mm/min")
        self.jog_dist = QDoubleSpinBox()
        self.jog_dist.setRange(0.001, 500)
        self.jog_dist.setDecimals(3)
        self.jog_dist.setValue(float(defaults.get("jog_distance", 1.0)))
        self.jog_dist.setSuffix(" mm")
        self.spindle_rpm = QSpinBox()
        self.spindle_rpm.setRange(0, 30000)
        self.spindle_rpm.setValue(int(defaults.get("spindle_rpm", 1000)))
        self.spindle_rpm.setSuffix(" rpm")
        f.addRow("Jog feed", self.jog_feed)
        f.addRow("Jog step", self.jog_dist)
        f.addRow("Spindle speed", self.spindle_rpm)
        lay.addWidget(gb_def)

        gb_mqtt = QGroupBox("Home Assistant / MQTT")
        f = QFormLayout(gb_mqtt)
        self.mqtt_enabled = QCheckBox("Enabled")
        self.mqtt_enabled.setChecked(bool(mqtt.get("enabled")))
        self.mqtt_host = QLineEdit(str(mqtt.get("host", "")))
        self.mqtt_port = QSpinBox()
        self.mqtt_port.setRange(1, 65535)
        self.mqtt_port.setValue(int(mqtt.get("port", 1883)))
        self.mqtt_user = QLineEdit(str(mqtt.get("username", "")))
        self.mqtt_pass = QLineEdit(str(mqtt.get("password", "")))
        self.mqtt_pass.setEchoMode(QLineEdit.Password)
        f.addRow(self.mqtt_enabled)
        f.addRow("Broker host", self.mqtt_host)
        f.addRow("Port", self.mqtt_port)
        f.addRow("Username", self.mqtt_user)
        f.addRow("Password", self.mqtt_pass)
        lay.addWidget(gb_mqtt)

        gb_probe = QGroupBox("Probe")
        f = QFormLayout(gb_probe)
        self.probe_fast = QSpinBox()
        self.probe_fast.setRange(1, 5000)
        self.probe_fast.setValue(int(float(pcfg.get("fast_feed", 300))))
        self.probe_fast.setSuffix(" mm/min")
        self.probe_slow = QSpinBox()
        self.probe_slow.setRange(1, 1000)
        self.probe_slow.setValue(int(float(pcfg.get("slow_feed", 30))))
        self.probe_slow.setSuffix(" mm/min")
        self.probe_retract = QDoubleSpinBox()
        self.probe_retract.setRange(0.1, 20)
        self.probe_retract.setDecimals(2)
        self.probe_retract.setValue(float(pcfg.get("retract", 2.0)))
        self.probe_retract.setSuffix(" mm")
        self.probe_travel = QDoubleSpinBox()
        self.probe_travel.setRange(1, 200)
        self.probe_travel.setDecimals(1)
        self.probe_travel.setValue(abs(float(pcfg.get("target", 20))))
        self.probe_travel.setSuffix(" mm")
        self.z_probe_size = QDoubleSpinBox()
        self.z_probe_size.setRange(0, 100)
        self.z_probe_size.setDecimals(3)
        self.z_probe_size.setValue(float(pcfg.get("z_probe_size", 0.0)))
        self.z_probe_size.setSuffix(" mm")
        self.z_probe_size.setToolTip("Height the Z contact point represents above the true zero,\n"
                                     "e.g. the thickness of a touch plate (0 = probed surface is Z0).")
        self.x_offset_zero = QDoubleSpinBox()
        self.x_offset_zero.setRange(-100, 100)
        self.x_offset_zero.setDecimals(3)
        self.x_offset_zero.setValue(float(pcfg.get("x_offset_zero", 0.0)))
        self.x_offset_zero.setSuffix(" mm")
        self.x_offset_zero.setToolTip("Value the probed X edge will read in the WCS.\n"
                                      "Non-zero shifts the X zero into the material after the probe.")
        self.y_offset_zero = QDoubleSpinBox()
        self.y_offset_zero.setRange(-100, 100)
        self.y_offset_zero.setDecimals(3)
        self.y_offset_zero.setValue(float(pcfg.get("y_offset_zero", 0.0)))
        self.y_offset_zero.setSuffix(" mm")
        self.y_offset_zero.setToolTip("Value the probed Y edge will read in the WCS.\n"
                                      "Non-zero shifts the Y zero into the material after the probe.")
        f.addRow("Fast feed", self.probe_fast)
        f.addRow("Slow feed", self.probe_slow)
        f.addRow("Retract", self.probe_retract)
        f.addRow("Search travel", self.probe_travel)
        f.addRow("Z probe size", self.z_probe_size)
        f.addRow("X zero offset", self.x_offset_zero)
        f.addRow("Y zero offset", self.y_offset_zero)
        lay.addWidget(gb_probe)

        gb_tools = QGroupBox("Tool table (one per line: number, diameter, note)")
        tv = QVBoxLayout(gb_tools)
        self.tools_edit = QPlainTextEdit()
        self.tools_edit.setMaximumHeight(90)
        for num, t in sorted((config.get("tools") or {}).items()):
            self.tools_edit.appendPlainText(f"{num}, {t.get('diameter', 0)}, {t.get('note', '')}")
        tv.addWidget(self.tools_edit)
        lay.addWidget(gb_tools)

        lay.addWidget(QLabel("Serial changes take effect after restart; other settings apply immediately."))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        self._config.setdefault("serial", {}).update(
            port=self.port.text().strip(), baud=self.baud.value(),
            status_poll_interval=self.poll.value() / 1000.0)
        self._config.setdefault("defaults", {}).update(
            jog_feed=self.jog_feed.value(), jog_distance=self.jog_dist.value(),
            spindle_rpm=self.spindle_rpm.value())
        self._config.setdefault("probe", {}).update(
            fast_feed=self.probe_fast.value(), slow_feed=self.probe_slow.value(),
            retract=self.probe_retract.value(), target=self.probe_travel.value(),
            z_probe_size=self.z_probe_size.value(),
            x_offset_zero=self.x_offset_zero.value(),
            y_offset_zero=self.y_offset_zero.value())
        self._config.setdefault("mqtt", {}).update(
            enabled=self.mqtt_enabled.isChecked(), host=self.mqtt_host.text().strip(),
            port=self.mqtt_port.value(), username=self.mqtt_user.text().strip(),
            password=self.mqtt_pass.text())
        tools = {}
        for line in self.tools_edit.toPlainText().splitlines():
            parts = [p.strip() for p in line.strip().split(",")]
            if not parts or not parts[0]:
                continue
            try:
                num = int(parts[0])
                dia = float(parts[1]) if len(parts) > 1 else 0.0
            except ValueError:
                continue
            tools[num] = {"diameter": dia, "note": parts[2] if len(parts) > 2 else ""}
        if tools:
            self._config["tools"] = tools

        if self._path:
            try:
                with open(self._path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self._config, f, sort_keys=False)
            except OSError as e:
                QMessageBox.warning(self, "Preferences", f"Could not save config: {e}")
        self.accept()
