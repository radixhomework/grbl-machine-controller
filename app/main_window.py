"""Main window: menu bar + all-in-one dashboard."""

from __future__ import annotations

import os

from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QStatusBar, QLabel

from .core.job_manager import JobManager
from .core.state import MachineState
from .resources import LOGO
from .ui.bridge import StateBridge
from .ui.dashboard import Dashboard, _Worker
from .ui.preferences import PreferencesDialog


class MainWindow(QMainWindow):
    def __init__(self, adapter, state: MachineState, job_manager: JobManager,
                 config: dict, config_path: str | None = None):
        super().__init__()
        self._workers = set()   # keep running background workers alive until finished
        self.setWindowTitle("GRBL Machine Controller")
        if os.path.exists(LOGO):
            self.setWindowIcon(QIcon(LOGO))
        self.resize(860, 680)
        self.adapter = adapter
        self.state = state
        self.jobs = job_manager
        self.config = config
        self.config_path = config_path

        bridge = StateBridge(state)
        self.dashboard = Dashboard(adapter, state, bridge, job_manager, config)
        self.setCentralWidget(self.dashboard)
        self._build_menus(bridge)

        status = QStatusBar()
        self.status_label = QLabel("Disconnected")
        status.addWidget(self.status_label, 1)
        self.setStatusBar(status)
        bridge.stateChanged.connect(self._update_status)

        def log(s):
            bridge.logLine.emit(s)
        job_manager.on_log = log
        adapter.on_log = log

    # ---- menus ---------------------------------------------------------------
    def _build_menus(self, bridge) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        act_open = QAction("&Open G-code…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(lambda: self.dashboard._load_file())
        m_file.addAction(act_open)
        act_prefs = QAction("&Preferences…", self)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(self._open_preferences)
        m_file.addAction(act_prefs)
        m_file.addSeparator()
        act_quit = QAction("E&xit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_machine = mb.addMenu("&Machine")
        for label, fn in (
            ("&Home all ($H)", lambda: self._async(self.adapter.home_all)),
            ("&Unlock ($X)", lambda: self._async(self.jobs.unlock)),
            ("Feed &hold", self.adapter.hold),
            ("&Resume", self.adapter.resume),
            ("Soft &reset", self.adapter.reset),
        ):
            act = QAction(label, self)
            act.triggered.connect(fn)
            m_machine.addAction(act)
        m_machine.addSeparator()
        act_connect = QAction("&Reconnect", self)
        act_connect.triggered.connect(lambda: self._async(self._reconnect))
        m_machine.addAction(act_connect)

        m_help = mb.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _async(self, fn) -> None:
        """Run a blocking core command off the GUI thread (menus stay responsive)."""
        w = _Worker(fn)
        w.finished.connect(lambda worker=w: self._workers.discard(worker))
        self._workers.add(w)
        w.start()

    def _reconnect(self) -> None:
        self.adapter.close()
        self.adapter.connect()

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self.config, self.config_path, parent=self)
        if dlg.exec():
            self._apply_preferences()

    def _apply_preferences(self) -> None:
        d = self.dashboard
        d.feed.setValue(self.config.get("defaults", {}).get("jog_feed", d.feed.value()))
        d.step.setValue(self.config.get("defaults", {}).get("jog_distance", d.step.value()))
        d.rpm.setValue(self.config.get("defaults", {}).get("spindle_rpm", d.rpm.value()))
        d.set_tools(self.config.get("tools", {}))

    def _about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from . import __version__

        box = QMessageBox(self)
        box.setWindowTitle("About")
        box.setText(
            f"GRBL machine controller {__version__}\n\n"
            "G-code streaming, jogging, tool-compensated probing,\n"
            "and Home Assistant MQTT integration.\n\n"
            "GRBL is the motion controller; this app streams and supervises.")
        if os.path.exists(LOGO):
            box.setIconPixmap(QIcon(LOGO).pixmap(64, 64))
        box.exec()

    def _update_status(self, s, _old) -> None:
        title = "GRBL Machine Controller"
        if s.job_file:
            title += f" — {s.job_file}"
        self.setWindowTitle(title)
        self.status_label.setText(
            f"State: {s.grbl_state}   MPos: {s.mpos.x:.3f}, {s.mpos.y:.3f}, {s.mpos.z:.3f}   "
            f"Ov: {s.overrides.feed}%   "
            f"Job: {s.job_file.split('/')[-1].split(chr(92))[-1] or '—'} {s.job_progress * 100:.0f}%"
        )
