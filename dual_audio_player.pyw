import sys, os, json, functools
from pathlib import Path
from typing import List

# paths / prefs
BASE_DIR   = Path(sys.executable if getattr(sys, "frozen", False)
                  else __file__).resolve().parent
PREFS_FILE = BASE_DIR / "dual_audio_prefs.json"
os.add_dll_directory(BASE_DIR)

def load_prefs() -> dict:
    try:
        return json.loads(PREFS_FILE.read_text())
    except Exception:
        return {}

def save_prefs(d: dict):
    try:
        PREFS_FILE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass

import mpv
from PySide6.QtCore    import Qt, Signal, Slot, QEvent, QTimer, QPoint
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSlider, QLabel
)

def fmttime(sec: float | None) -> str:
    if sec is None or sec < 0:
        return "--:--"
    sec = int(sec)
    s, m, h = sec % 60, (sec // 60) % 60, sec // 3600
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"

# floating hover bar
class HoverBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(48)                         # short strip
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background:rgba(0,0,0,200);")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 10, 6)
        self.lay.setSpacing(18)
        self.hide()

# main window
class PlayerWindow(QMainWindow):
    tracklist_ready = Signal(object)
    duration_ready  = Signal(float)
    pos_ready       = Signal(float)

    def __init__(self):
        super().__init__()

        # preferences
        self.prefs = load_prefs()          # volumes + window size

        # window geometry
        w = self.prefs.get("window_width", 960)
        h = self.prefs.get("window_height", 540)
        self.resize(w, h)

        self.setWindowTitle("Dual-audio viewer")
        self.setAcceptDrops(True)

        # layout
        centre = QWidget(); self.setCentralWidget(centre)
        outer  = QVBoxLayout(centre); outer.setContentsMargins(0, 0, 0, 0)

        self.video = QWidget(); self.video.setCursor(Qt.PointingHandCursor)
        outer.addWidget(self.video, stretch=1)

        seek_row = QHBoxLayout(); outer.addLayout(seek_row)
        self.seek = QSlider(Qt.Horizontal, minimum=0, maximum=0)
        seek_row.addWidget(self.seek, 1)
        self.time_lbl = QLabel("--:-- / --:--")
        self.time_lbl.setStyleSheet("color:white; font:10px;")
        seek_row.addWidget(self.time_lbl)

        self.bar = HoverBar(self)                    # hover bar is child of window
        self.bar_timer = QTimer(self, interval=2000,
                                singleShot=True, timeout=self.bar.hide)

        # mpv
        self.m = mpv.MPV(
            wid=str(int(self.video.winId())),
            input_default_bindings=True,
            osc=True,
        )
        self._obs("track-list", self.tracklist_ready)
        self._obs("duration",   self.duration_ready)
        self._obs("time-pos",   self.pos_ready)

        # signals
        self.tracklist_ready.connect(self.on_tracks)
        self.duration_ready .connect(self.on_dur)
        self.pos_ready      .connect(self.on_pos)

        # poll keeps position updated when paused
        QTimer(self, interval=300,
               timeout=lambda: self.m.command("get_property", "time-pos")).start()

        self.sliders: List[QSlider] = []
        self.drag_seek = False

        self.video.installEventFilter(self)
        self.bar.installEventFilter(self)
        self.seek.sliderPressed .connect(lambda: setattr(self, "drag_seek", True))
        self.seek.sliderReleased.connect(self._seek_done)

    # mpv observer wrapper
    def _obs(self, prop, sig):
        try:   self.m.observe_property(prop, "native", lambda *a: sig.emit(a[-1]))
        except TypeError: self.m.observe_property(prop, lambda *a: sig.emit(a[-1]))

    # DnD
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.m.command("loadfile", e.mimeData().urls()[0].toLocalFile(), "replace")

    # hover & click
    def eventFilter(self, obj, ev):
        if obj is self.video:
            if ev.type() == QEvent.MouseButtonPress:
                self.m.command("cycle", "pause"); return True
            if ev.type() in (QEvent.Enter, QEvent.MouseMove):
                self._show_bar()
            if ev.type() == QEvent.Resize:
                self._pos_bar()
        if obj is self.bar and ev.type() in (QEvent.Enter, QEvent.MouseMove):
            self._show_bar()
        if ev.type() == QEvent.Leave and obj in (self.video, self.bar):
            self.bar_timer.start()
        return super().eventFilter(obj, ev)

    def _show_bar(self):
        self.bar_timer.stop()
        if not self.bar.isVisible():
            self.bar.show()
        self._pos_bar()

    def _pos_bar(self):
        tl = self.video.mapTo(self, QPoint(0, 0))
        self.bar.resize(self.video.width(), self.bar.height())
        self.bar.move(tl.x(), tl.y() + self.video.height() - self.bar.height())
        self.bar.raise_()

    # build sliders
    @Slot(object)
    def on_tracks(self, tracks):
        while self.bar.lay.count():
            w = self.bar.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.sliders.clear()

        for t in tracks or []:
            if t.get("type") != "audio":
                continue
            aid = t["id"]

            row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0,0,0,0); h.setSpacing(6)
            lab = QLabel(f"{aid}"); lab.setFixedWidth(24); lab.setStyleSheet("color:white; font:10px;")
            sld = QSlider(Qt.Horizontal); sld.setRange(0, 100); sld.setFixedWidth(220)
            sld.setValue(self.prefs.get(str(aid), 100)); sld.aid = aid
            sld.valueChanged.connect(functools.partial(self._vol_change, sld))
            h.addWidget(lab); h.addWidget(sld)
            self.bar.lay.addWidget(row)
            self.sliders.append(sld)

        self._mix(); self._show_bar()

    def _vol_change(self, sld, _):
        self.prefs[str(sld.aid)] = sld.value(); save_prefs(self.prefs)
        self._mix()

    def _mix(self):
        if not self.sliders:
            self.m.command("set", "lavfi-complex", ""); return
        parts = [f"[aid{s.aid}]volume={s.value()/100}[a{i}]"
                 for i, s in enumerate(self.sliders)]
        outs  = [f"[a{i}]" for i in range(len(self.sliders))]
        self.m.command("set", "lavfi-complex",
                       ";".join(parts) + ";" + "".join(outs) +
                       f"amix=inputs={len(self.sliders)}[ao]")

    # seek / time
    @Slot(float)
    def on_dur(self, d):
        if d and d > 0:
            self.seek.setMaximum(int(d))
        self._update_lbl()

    @Slot(float)
    def on_pos(self, p):
        if not self.drag_seek and p is not None:
            self.seek.blockSignals(True)
            self.seek.setValue(int(p))
            self.seek.blockSignals(False)
        self._update_lbl(p)

    def _update_lbl(self, pos=None):
        if pos is None:
            pos = self.seek.value()
        self.time_lbl.setText(f"{fmttime(pos)} / {fmttime(self.seek.maximum())}")

    def _seek_done(self):
        self.drag_seek = False
        self.m.command("set", "time-pos", self.seek.value())

    # remember window size on close
    def closeEvent(self, ev):
        self.prefs["window_width"]  = self.width()
        self.prefs["window_height"] = self.height()
        save_prefs(self.prefs)
        super().closeEvent(ev)

# run
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    win = PlayerWindow(); win.show()
    sys.exit(app.exec())
