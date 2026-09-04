"""All-in-one dashboard.

Layout: 3D preview (main area) | right panel (DRO, probe, jog, spindle, job)
with the log panel across the bottom.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QStyle

from ..core.probe import ProbeConfig, ProbeController
from .preview3d import Preview3D
from .style import MOSS, RADISH


def _mono():
    f = QFont("monospace")
    f.setStyleHint(QFont.Monospace)
    return f


def _icon(widget: QWidget, key) -> object:
    return widget.style().standardIcon(key)


class _Worker(QThread):
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.done.emit(self.fn())


class Dashboard(QWidget):
    def __init__(self, adapter, state, state_bridge, job_manager, config):
        super().__init__()
        self.adapter = adapter
        self.state = state
        self.jobs = job_manager
        dcfg = config.get("defaults", {})
        pcfg = config.get("probe", {})
        tools = config.get("tools", {})
        self.probe_cfg = pcfg
        self.probe = ProbeController(adapter, on_log=lambda s: state_bridge.logLine.emit(s))
        self._worker = None

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(8, 8, 8, 8)

        # ---- vertical splitter: main area (3D | side panel) / log ---------
        v_split = QSplitter(Qt.Vertical)
        h_split = QSplitter(Qt.Horizontal)
        for s in (v_split, h_split):
            s.setHandleWidth(3)
            s.setChildrenCollapsible(False)
            # handle colors come from the app stylesheet (chart theme)

        self.preview = Preview3D()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        h_split.addWidget(self.preview)
        h_split.addWidget(self._side_panel(dcfg, pcfg, tools))
        h_split.setStretchFactor(0, 1)
        h_split.setSizes([620, 330])

        # ---- command log table: (#, command, state, response) -------------
        self.log = QTreeWidget()
        self.log.setColumnCount(4)
        self.log.setHeaderLabels(["#", "Command", "State", "Response"])
        self.log.setRootIsDecorated(False)
        self.log.setUniformRowHeights(True)
        self.log.setAlternatingRowColors(True)
        self.log.setFont(_mono())
        self.log.header().resizeSection(0, 46)
        self.log.header().resizeSection(2, 70)
        self.log.header().setStretchLastSection(False)
        self.log.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.log.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._log_limit = 500
        v_split.addWidget(h_split)
        v_split.addWidget(self.log)
        v_split.setStretchFactor(0, 1)
        v_split.setSizes([520, 140])
        root.addWidget(v_split)
        state_bridge.logLine.connect(self._on_log_record)

        # loading through the preview's picker feeds the job too
        self.preview.on_file_loaded = self._on_preview_file
        state_bridge.stateChanged.connect(self._update_state)

    # ---- command log ----------------------------------------------------------
    def _on_log_record(self, rec) -> None:
        """Append one row to the command log table.

        `rec` is either a dict {seq, cmd, state, resp} from the core or a
        plain informational string.
        """
        if isinstance(rec, str):
            rec = {"seq": None, "cmd": rec,
                   "state": self.state.snapshot().grbl_state, "resp": ""}
        item = QTreeWidgetItem([
            "" if rec.get("seq") is None else str(rec["seq"]),
            rec.get("cmd", ""),
            rec.get("state", ""),
            rec.get("resp", ""),
        ])
        resp = rec.get("resp", "") or ""
        if resp.startswith("error") or resp.startswith("ALARM") or "timeout" in resp:
            item.setForeground(3, QBrush(QColor("#8A5E61")))
        self.log.addTopLevelItem(item)
        if self.log.topLevelItemCount() > self._log_limit:
            self.log.takeTopLevelItem(0)
        self.log.scrollToBottom()

    # ---- right side panel ----------------------------------------------------
    def _side_panel(self, dcfg, pcfg, tools) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(8)
        lay.addWidget(self._dro_group())
        lay.addWidget(self._probe_group(pcfg, tools))
        lay.addWidget(self._jog_group(dcfg))
        lay.addWidget(self._spindle_group(dcfg))
        lay.addWidget(self._job_group())
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(260)
        scroll.setFrameShape(QScrollArea.NoFrame)
        return scroll

    # ---- coordinates -----------------------------------------------------------
    def _dro_group(self) -> QWidget:
        box = QGroupBox("Coordinates")
        grid = QGridLayout(box)
        grid.setSpacing(2)

        # row 1: work position (probe zeros applied)
        grid.addWidget(QLabel("Work"), 0, 0)
        self.w_labels = {}
        for col, ax in enumerate("XYZ"):
            v = QLabel("0.000")
            v.setFont(_mono())
            v.setStyleSheet("font-size: 16px;")
            grid.addWidget(v, 0, col + 1)
            self.w_labels[ax] = v

        # row 2: machine position + reset
        grid.addWidget(QLabel("Machine"), 1, 0)
        self.m_labels = {}
        for col, ax in enumerate("XYZ"):
            v = QLabel("0.000")
            v.setFont(_mono())
            grid.addWidget(v, 1, col + 1)
            self.m_labels[ax] = v
        reset = QPushButton("Reset")
        reset.setFixedWidth(56)
        reset.setToolTip("Zero the machine coordinates (G10 L2 P0)")
        reset.clicked.connect(self.adapter.reset_machine_pos)
        grid.addWidget(reset, 1, 4)

        # row 3: status / code
        grid.addWidget(QLabel("Status"), 2, 0)
        self.state_label = QLabel("Offline")
        self.state_label.setFont(_mono())
        grid.addWidget(self.state_label, 2, 1, 1, 3)
        self.code_label = QLabel("Code: —")
        self.code_label.setFont(_mono())
        grid.addWidget(self.code_label, 2, 4)
        return box

    # ---- probe ------------------------------------------------------------------
    def _probe_group(self, pcfg, tools) -> QWidget:
        box = QGroupBox("Probe")
        lay = QVBoxLayout(box)
        form = QFormLayout()

        # tool selection from the settings tool table
        self.tool_combo = QComboBox()
        self.set_tools(tools)
        # ensure the popup never lingers after a selection
        self.tool_combo.activated.connect(self._close_tool_popup)
        form.addRow("Tool", self.tool_combo)

        self.wcs = QLineEdit("G54")
        self.wcs.setMaximumWidth(70)
        form.addRow("WCS", self.wcs)
        lay.addLayout(form)

        # zeroing rows share one grid so the buttons align column-by-column
        rows = QGridLayout()
        rows.setVerticalSpacing(4)

        zeros_lbl = QLabel("Probe:")
        rows.addWidget(zeros_lbl, 0, 0)
        for col, label in enumerate(("Zero X-", "Zero Y-", "Zero Z-")):
            b = QPushButton(label)
            b.setToolTip(f"Probe the {label.split()[1]} edge with the selected tool\n"
                         "and set that axis zero, compensating for tool diameter")
            b.clicked.connect(lambda _, d=label.split()[1]: self._probe_edge(d))
            rows.addWidget(b, 0, col + 1)

        manual_lbl = QLabel("Set 0:")
        manual_lbl.setToolTip("Define the current position as zero (no probing, no compensation)")
        rows.addWidget(manual_lbl, 1, 0)
        for col, ax in enumerate("XYZ"):
            b = QPushButton(f"{ax} = 0")
            b.setToolTip(f"Define the current {ax} position as zero in {self.wcs.text() or 'G54'}")
            b.clicked.connect(lambda _, a=ax: self._set_zero(a))
            rows.addWidget(b, 1, col + 1)
        lay.addLayout(rows)

        row = QHBoxLayout()
        corner = QPushButton("Corner X-/Y-")
        corner.setToolTip(
            "Probe two perpendicular edges (X- then Y-) in sequence and zero both axes,\n"
            "so the corner becomes the work origin (X0 Y0). Use it to set up a part\n"
            "against two reference edges without probing each axis by hand.")
        corner.clicked.connect(lambda: self._run_async(
            lambda: self.probe.run_corner(self._cfg("X-"), self._cfg("Y-"))))
        row.addWidget(corner)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.probe.cancel)
        row.addWidget(cancel)
        lay.addLayout(row)
        return box

    def _close_tool_popup(self, _index=0):
        popup = self.tool_combo.view().window()
        if popup.isVisible():
            popup.close()

    def set_tools(self, tools: dict) -> None:
        """(Re)populate the tool combo from the settings tool table."""
        self.tool_combo.blockSignals(True)
        self.tool_combo.clear()
        self._tool_diameters = {}
        for num, t in sorted((tools or {}).items()):
            dia = float(t.get("diameter", 0.0))
            note = t.get("note", "")
            label = f"T{num}: ⌀{dia:g} mm" + (f" — {note}" if note else "")
            self.tool_combo.addItem(label, dia)
            self._tool_diameters[num] = dia
        if self.tool_combo.count() == 0:
            self.tool_combo.addItem("⌀0 mm (no tools configured)", 0.0)
        self.tool_combo.blockSignals(False)

    def _current_tool_diameter(self) -> float:
        return float(self.tool_combo.currentData() or 0.0)

    def _cfg(self, direction: str) -> ProbeConfig:
        return ProbeConfig(
            direction=direction,
            tool_diameter=self._current_tool_diameter() if direction != "Z-" else 0.0,
            fast_feed=float(self.probe_cfg.get("fast_feed", 300)),
            slow_feed=float(self.probe_cfg.get("slow_feed", 30)),
            retract=float(self.probe_cfg.get("retract", 2.0)),
            travel=-abs(float(self.probe_cfg.get("target", 20))),
            wcs=self.wcs.text().strip() or "G54",
            probe_size=float(self.probe_cfg.get(f"{direction[0].lower()}_probe_size", 0.0)),
            z_ref_height=float(self.probe_cfg.get("z_probe_size", 0.0)),
        )

    def _probe_edge(self, direction):
        self._run_async(lambda: self.probe.run_edge(self._cfg(direction)))

    def _set_zero(self, axis: str) -> None:
        """Define the current position as zero for one axis in the active WCS."""
        r = self.adapter.set_work_offset(self.wcs.text().strip() or "G54", **{axis.lower(): 0.0})
        if not r.ok:
            self.log.appendPlainText(f"Set {axis}0 failed: {r.response}")

    def _run_async(self, fn):
        if self.probe.busy or (self._worker and self._worker.isRunning()):
            return
        self._worker = _Worker(fn)
        self._worker.start()

    # ---- jog --------------------------------------------------------------------
    def _jog_group(self, dcfg) -> QWidget:
        box = QGroupBox("Jog")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.step = QDoubleSpinBox()
        self.step.setRange(0.001, 500)
        self.step.setDecimals(3)
        self.step.setValue(float(dcfg.get("jog_distance", 1.0)))
        self.step.setSuffix(" mm")
        row.addWidget(self.step)
        for v in (0.1, 1, 10):
            b = QPushButton(str(v))
            b.setFixedWidth(34)
            b.clicked.connect(lambda _, val=v: self.step.setValue(val))
            row.addWidget(b)
        lay.addLayout(row)

        self.feed = QSpinBox()
        self.feed.setRange(1, 20000)
        self.feed.setValue(int(dcfg.get("jog_feed", 1000)))
        self.feed.setSuffix(" mm/min")
        lay.addWidget(self.feed)

        grid = QGridLayout()
        for (r, c), (label, fn) in {
            (0, 1): ("Y+", lambda: self.adapter.jog("Y", +self.step.value(), self.feed.value())),
            (2, 1): ("Y-", lambda: self.adapter.jog("Y", -self.step.value(), self.feed.value())),
            (1, 0): ("X-", lambda: self.adapter.jog("X", -self.step.value(), self.feed.value())),
            (1, 2): ("X+", lambda: self.adapter.jog("X", +self.step.value(), self.feed.value())),
            (0, 3): ("Z+", lambda: self.adapter.jog("Z", +self.step.value(), self.feed.value())),
            (2, 3): ("Z-", lambda: self.adapter.jog("Z", -self.step.value(), self.feed.value())),
        }.items():
            b = QPushButton(label)
            b.setMinimumSize(50, 36)
            b.clicked.connect(fn)
            grid.addWidget(b, r, c)
        lay.addLayout(grid)

        style = self.style()
        row2 = QHBoxLayout()
        stop = QPushButton("Stop")
        stop.setIcon(_icon(self, QStyle.SP_MediaStop))
        stop.clicked.connect(self.adapter.jog_cancel)
        row2.addWidget(stop)
        home = QPushButton("Home")
        home.setIcon(_icon(self, QStyle.SP_DialogResetButton))
        home.clicked.connect(lambda: self.adapter.home_all())
        row2.addWidget(home)
        lay.addLayout(row2)
        return box

    # ---- spindle ------------------------------------------------------------------
    def _spindle_group(self, dcfg) -> QWidget:
        box = QGroupBox("Spindle")
        lay = QVBoxLayout(box)

        self.rpm = QSpinBox()
        self.rpm.setRange(0, 30000)
        self.rpm.setValue(int(dcfg.get("spindle_rpm", 1000)))
        self.rpm.setSuffix(" rpm")
        self.rpm.valueChanged.connect(self._apply_rpm)
        lay.addWidget(self.rpm)

        row = QHBoxLayout()
        style = self.style()
        self.dir_cw = QPushButton("CW")
        self.dir_cw.setIcon(_icon(self, QStyle.SP_ArrowForward))
        self.dir_cw.setCheckable(True)
        self.dir_cw.setChecked(True)
        self.dir_ccw = QPushButton("CCW")
        self.dir_ccw.setIcon(_icon(self, QStyle.SP_ArrowBack))
        self.dir_ccw.setCheckable(True)
        self.dir_cw.toggled.connect(lambda on: on and self.dir_ccw.setChecked(False))
        self.dir_ccw.toggled.connect(lambda on: on and self.dir_cw.setChecked(False))
        row.addWidget(self.dir_cw)
        row.addWidget(self.dir_ccw)
        lay.addLayout(row)

        self.spindle_btn = QPushButton("ON")
        self.spindle_btn.setIcon(_icon(self, QStyle.SP_MediaPlay))
        self.spindle_btn.setCheckable(True)
        self.spindle_btn.toggled.connect(self._toggle_spindle)
        lay.addWidget(self.spindle_btn)

        self.live_rpm = QLabel("S 0 rpm")
        self.live_rpm.setFont(_mono())
        self.live_rpm.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.live_rpm)
        return box

    def _apply_rpm(self):
        if self.spindle_btn.isChecked():
            self.adapter.set_spindle_speed(self.rpm.value())

    def _toggle_spindle(self, on):
        if on:
            self.adapter.set_spindle_speed(self.rpm.value())
            r = self.adapter.spindle_on(clockwise=self.dir_cw.isChecked())
        else:
            r = self.adapter.spindle_off()
        if not r.ok:
            self.spindle_btn.blockSignals(True)
            self.spindle_btn.setChecked(not on)
            self.spindle_btn.blockSignals(False)

    # ---- job (loading happens via File menu / preview picker) -----------------------
    def _job_group(self) -> QWidget:
        box = QGroupBox("Job")
        lay = QVBoxLayout(box)
        self.file_label = QLabel("no file")
        lay.addWidget(self.file_label)

        row = QHBoxLayout()
        style = self.style()
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(_icon(self, QStyle.SP_MediaPlay))
        self.start_btn.clicked.connect(self.jobs.start)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(_icon(self, QStyle.SP_MediaPause))
        self.pause_btn.clicked.connect(self._toggle_pause)
        stop = QPushButton("Stop")
        stop.setIcon(_icon(self, QStyle.SP_MediaStop))
        stop.clicked.connect(self.jobs.stop)
        unlock = QPushButton("Unlock")
        unlock.setIcon(_icon(self, QStyle.SP_DialogApplyButton))
        unlock.clicked.connect(self.jobs.unlock)
        for b in (self.start_btn, self.pause_btn, stop, unlock):
            row.addWidget(b)
        lay.addLayout(row)

        self.progress = QProgressBar()
        lay.addWidget(self.progress)

        self.mdi = QLineEdit()
        self.mdi.setPlaceholderText("MDI: G0 X0 Y0 ⏎")
        self.mdi.setFont(_mono())
        self.mdi.returnPressed.connect(self._send_mdi)
        lay.addWidget(self.mdi)
        return box

    def _on_preview_file(self, path: str) -> None:
        self.jobs.load_file(path)
        self.file_label.setText(path.replace("\\", "/").split("/")[-1])

    def set_job_file(self, path: str) -> None:
        name = path.replace("\\", "/").split("/")[-1]
        self.file_label.setText(name)
        self.preview.load_path(path)

    def _toggle_pause(self):
        if self.jobs.job_state.value == "Paused":
            self.jobs.resume()
            self.pause_btn.setText("Pause")
        else:
            self.jobs.pause()
            self.pause_btn.setText("Resume")

    def _send_mdi(self):
        line = self.mdi.text().strip()
        if line:
            self.mdi.clear()
            self.adapter.send(line)

    # ---- state refresh -------------------------------------------------------------
    def _update_state(self, s, _old):
        for ax, v in zip("XYZ", (s.wpos.x, s.wpos.y, s.wpos.z)):
            self.w_labels[ax].setText(f"{v:8.3f}")
        for ax, v in zip("XYZ", (s.mpos.x, s.mpos.y, s.mpos.z)):
            self.m_labels[ax].setText(f"{v:8.3f}")
        alarm = s.grbl_state == "Alarm"
        self.state_label.setText(s.grbl_state)
        self.state_label.setStyleSheet(f"color:{RADISH};font-weight:bold" if alarm else
                                       (f"color:{MOSS};font-weight:bold" if s.job_running else ""))
        code = s.alarm_code if alarm else s.last_error
        self.code_label.setText(f"Code: {'—' if code is None else code}")
        self.code_label.setStyleSheet(f"color:{RADISH}" if code is not None else "")
        self.live_rpm.setText(f"S {s.spindle_rpm:.0f} rpm")
        self.spindle_btn.blockSignals(True)
        self.spindle_btn.setChecked(s.spindle_on)
        self.spindle_btn.blockSignals(False)
        self.progress.setValue(int(s.job_progress * 100))
        self.start_btn.setEnabled(not s.job_running and not alarm)
        self.pause_btn.setEnabled(s.job_running or s.job_paused)
        if s.job_paused:
            self.pause_btn.setText("Resume")
        elif not s.job_running:
            self.pause_btn.setText("Pause")
        # live tool position on the 3D preview while a job runs
        self.preview.set_tool_pos(
            (s.wpos.x, s.wpos.y, s.wpos.z) if s.job_running else None)

    # kept for the File > Open G-code menu action
    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open G-code", "", "G-code (*.nc *.gcode *.g *.ngc);;All files (*)")
        if path:
            self.jobs.load_file(path)
            self.set_job_file(path)
