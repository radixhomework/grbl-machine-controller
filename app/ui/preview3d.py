"""3D toolpath preview: software-projected G0/G1 rendering with QPainter.

No OpenGL dependency (keeps Pi/WSL packaging simple). Left-drag orbits,
wheel zooms. Rapids are thin gray, cuts are thick blue, depth-sorted.
"""

from __future__ import annotations

import math
import re

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPalette
from PySide6.QtWidgets import QComboBox, QWidget

WORD_RE = re.compile(r"([XYZ])(-?\d+\.?\d*)", re.IGNORECASE)
MODE_RE = re.compile(r"\b(G0|G1|G00|G01)\b", re.IGNORECASE)


def parse_gcode_3d(path: str):
    """Return (segments, bounds). Segment = (start, end, is_cut)."""
    x = y = z = 0.0
    cut_mode = False
    segs = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.split(";")[0].split("(")[0].strip()
            if not line:
                continue
            m = MODE_RE.search(line)
            if m:
                cut_mode = int(m.group(1)[1:]) != 0
                words = dict((a.upper(), float(v)) for a, v in WORD_RE.findall(line))
                nx, ny, nz = words.get("X", x), words.get("Y", y), words.get("Z", z)
                if (nx, ny, nz) != (x, y, z):
                    segs.append(((x, y, z), (nx, ny, nz), cut_mode))
                x, y, z = nx, ny, nz
                continue
            # G2/G3 arcs: approximate with a straight chord
            if re.search(r"\bG0?2\b", line, re.IGNORECASE) or re.search(r"\bG0?3\b", line, re.IGNORECASE):
                words = dict((a.upper(), float(v)) for a, v in WORD_RE.findall(line))
                nx, ny, nz = words.get("X", x), words.get("Y", y), words.get("Z", z)
                if (nx, ny, nz) != (x, y, z):
                    segs.append(((x, y, z), (nx, ny, nz), True))
                x, y, z = nx, ny, nz
    if not segs:
        return segs, (0, 0, 0, 100, 100, 10)
    pts = [p for s in segs for p in (s[0], s[1])]
    bounds = tuple((min(c), max(c)) for c in zip(*pts))
    return segs, bounds


class Preview3D(QWidget):
    # name -> (yaw, pitch) in degrees
    VIEWS = {
        "Iso": (-45, 55),
        "Top": (0, 0),
        "Front": (0, 90),
        "Back": (180, 90),
        "Left": (-90, 90),
        "Right": (90, 90),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        # set by the owner: called with the path whenever a file is loaded
        self.on_file_loaded = None
        self.setMinimumHeight(160)
        self.segs = []
        self.center = (0.0, 0.0, 0.0)
        self.radius = 100.0
        self.yaw = math.radians(-45)
        self.pitch = math.radians(55)
        self.zoom = 1.0
        self._drag_from = None
        self.tool_pos = None   # live (x, y, z) while a job runs
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Base)   # light theme, painted by Qt itself

        # view preset selector pinned to the top-right corner
        self.view_combo = QComboBox(self)
        self.view_combo.addItems(list(self.VIEWS))
        self.view_combo.setCurrentText("Iso")
        self.view_combo.setToolTip("Preset view")
        self.view_combo.currentTextChanged.connect(self.apply_view)
        # belt and braces: some window managers leave the popup open after selection
        self.view_combo.activated.connect(self._close_popup)
        self.view_combo.setFixedHeight(22)

    def _close_popup(self, _index=0):
        popup = self.view_combo.view().window()
        if popup.isVisible():
            popup.close()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.view_combo.adjustSize()
        self.view_combo.move(self.width() - self.view_combo.width() - 8, 8)
        self.view_combo.raise_()

    def apply_view(self, name: str) -> None:
        yaw, pitch = self.VIEWS.get(name, (-45, 55))
        self.yaw = math.radians(yaw)
        self.pitch = math.radians(pitch)
        self.update()

    def set_tool_pos(self, p) -> None:
        """Show the tool marker at (x, y, z) in G-code coordinates; None hides it."""
        if self.tool_pos != p:
            self.tool_pos = p
            self.update()

    def load_path(self, path: str) -> None:
        self.segs, bounds = parse_gcode_3d(path)
        (x0, x1), (y0, y1), (z0, z1) = bounds
        self.center = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        self.radius = max(x1 - x0, y1 - y0, z1 - z0, 1.0)
        self.zoom = 1.0
        self.update()
        if self.on_file_loaded:
            self.on_file_loaded(path)

    # ---- projection -----------------------------------------------------
    def _project(self, p, w, h):
        # translate (flip Z: CNC +Z is up, screen Y is down)
        dx, dy = p[0] - self.center[0], p[1] - self.center[1]
        dz = -(p[2] - self.center[2])
        # yaw around Z
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        dx, dy = dx * cy - dy * sy, dx * sy + dy * cy
        # pitch around X (elevation)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        dy, dz = dy * cp - dz * sp, dy * sp + dz * cp
        # weak perspective
        dist = self.radius * 3
        f = dist / max(dist + dz, dist / 6)
        scale = min(w, h) / (2.4 * self.radius) * self.zoom
        return (w / 2 + dx * scale * f, h / 2 - dy * scale * f, dz)

    # ---- interaction ------------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_from = (ev.position().x(), ev.position().y(), self.yaw, self.pitch)

    def mouseMoveEvent(self, ev):
        if self._drag_from:
            x0, y0, yaw0, pitch0 = self._drag_from
            k = math.pi / max(self.height(), 1)
            self.yaw = yaw0 + (ev.position().x() - x0) * k
            self.pitch = max(0.05, min(math.pi - 0.05, pitch0 + (ev.position().y() - y0) * k))
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drag_from = None

    def wheelEvent(self, ev):
        self.zoom = max(0.2, min(8.0, self.zoom * (1.15 if ev.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()

    # ---- painting -----------------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self.segs:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "No toolpath loaded")
            p.end()
            return

        # world-space depth sort (far first)
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)

        def depth(pt):
            dx, dy = (pt[i] - self.center[i] for i in range(2))
            dzz = -(pt[2] - self.center[2])
            return dx * sy + dy * cy + dzz * sp  # toward viewer after rotation

        order = sorted(range(len(self.segs)),
                       key=lambda i: depth(self.segs[i][0]) + depth(self.segs[i][1]))

        for i in order:
            a, b, is_cut = self.segs[i]
            pa = self._project(a, w, h)
            pb = self._project(b, w, h)
            pen = QPen(QColor("#1c81d2") if is_cut else QColor("#bbbbbb"), 2 if is_cut else 1)
            p.setPen(pen)
            p.drawLine(QPoint(int(pa[0]), int(pa[1])), QPoint(int(pb[0]), int(pb[1])))

        # live tool marker on top of everything
        if self.tool_pos:
            px, py, pz = self._project(self.tool_pos, w, h)
            cx, cy = int(px), int(py)
            # drop line to Z=0 plane for spatial reference
            zx, zy, _ = self._project((self.tool_pos[0], self.tool_pos[1], 0.0), w, h)
            p.setPen(QPen(QColor("#f55"), 1, Qt.DashLine))
            p.drawLine(cx, cy, int(zx), int(zy))
            p.setPen(QPen(QColor("#f55"), 2))
            p.setBrush(QBrush(QColor("#f55")))
            p.drawEllipse(QPoint(cx, cy), 5, 5)
            p.setBrush(Qt.NoBrush)

        # axes triad at origin
        origin = (0.0, 0.0, 0.0)
        L = self.radius * 0.25
        for tip, color in (((L, 0, 0), "#e55"), ((0, L, 0), "#5c5"), ((0, 0, L), "#59d")):
            pa = self._project(origin, w, h)
            pb = self._project(tip, w, h)
            p.setPen(QPen(QColor(color), 3))
            p.drawLine(QPoint(int(pa[0]), int(pa[1])), QPoint(int(pb[0]), int(pb[1])))
        p.end()
