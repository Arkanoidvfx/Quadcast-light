"""Application entry point: window, tray, and the QML engine.

Command line, kept compatible with existing installs and the Arkanoid
supervisor that launches this app:

    --show      surface the window of the running resident, then exit
    --no-tray   run headless under a supervisor that owns the tray icon
                (QUADCAST_NO_TRAY=1 does the same)
"""
import os
import sys

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import autostart, logging_setup, singleinstance
from .bridge import Bridge

QML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")


def make_icon(color="#4ade80"):
    """A mic silhouette drawn at load time, so there is no binary asset to ship.

    Small enough to stay legible at 16 px, which is all the tray gives us.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(22, 8, 20, 34, 10, 10)
    painter.setBrush(QColor(0, 0, 0, 0))
    pen = painter.pen()
    pen.setColor(QColor(color))
    pen.setWidth(5)
    painter.setPen(pen)
    painter.drawArc(14, 22, 36, 30, 180 * 16, 180 * 16)
    painter.drawLine(32, 50, 32, 58)
    painter.end()
    return QIcon(pixmap)


class ShowRelay(QObject):
    """Hops the named-event callback from its worker thread onto the UI thread."""

    requested = Signal()

    @Slot()
    def fire(self):
        self.requested.emit()


class Application:
    def __init__(self, argv):
        self.no_tray = "--no-tray" in argv or os.environ.get("QUADCAST_NO_TRAY") == "1"
        self.log = logging_setup.setup()
        self.log.info("QuadcastLight starting (pid %s, no_tray=%s)", os.getpid(), self.no_tray)

        # The native Windows style refuses control customization outright, so
        # every styled background/contentItem below would be silently dropped.
        QQuickStyle.setStyle("Basic")
        self.app = QApplication(argv)
        self.app.setApplicationName("QuadcastLight")
        self.app.setOrganizationName("QuadcastLight")
        self.app.setWindowIcon(make_icon())
        # The resident lives in the tray; closing the window must not quit.
        self.app.setQuitOnLastWindowClosed(False)

        self.bridge = Bridge()
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(QML_DIR)
        self.engine.rootContext().setContextProperty("bridge", self.bridge)
        self.engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))
        if not self.engine.rootObjects():
            raise RuntimeError("QML failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.visibleChanged.connect(self._on_visible_changed)

        self.tray = None
        if not self.no_tray:
            self._build_tray()

        self.relay = ShowRelay()
        self.relay.requested.connect(self.show_window)
        self._show_event = singleinstance.listen_for_show(self.relay.fire)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self.app)
        self.tray.setToolTip("QuadcastLight")
        menu = QMenu()
        open_action = QAction("Open QuadcastLight", menu)
        open_action.triggered.connect(self.show_window)
        restart_action = QAction("Restart QuadcastLight", menu)
        restart_action.triggered.connect(self.restart)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(open_action)
        menu.addAction(restart_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def _on_visible_changed(self):
        # Nothing is watching the mic mirror while the window is hidden, and a
        # hidden QQuickWindow does not render, so stop feeding it.
        self.bridge.set_mirror_enabled(bool(self.window.property("visible")))

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.requestActivate()

    def restart(self):
        import subprocess

        command = autostart.launch_command()
        # Wait for this process to release the single-instance mutex, then
        # start again. PowerShell can wait on a pid, and a frozen build has no
        # interpreter to run a Python helper with: sys.executable is this app.
        quoted = [part.replace("'", "''") for part in command]
        script = (
            f"Wait-Process -Id {os.getpid()} -Timeout 30 "
            f"-ErrorAction SilentlyContinue; "
            f"Start-Process -FilePath '{quoted[0]}'"
        )
        if len(quoted) > 1:
            script += " -ArgumentList " + ",".join(f"'{part}'" for part in quoted[1:])
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=0x00000008 | 0x08000000,  # DETACHED_PROCESS | CREATE_NO_WINDOW
            close_fds=True,
        )
        self.quit()

    def quit(self):
        self.log.info("QuadcastLight exiting")
        self.bridge.shutdown()
        if self.tray:
            self.tray.hide()
        self.app.quit()

    def run(self, show_on_start=False):
        if show_on_start:
            self.show_window()
        else:
            self.bridge.set_mirror_enabled(False)
        return self.app.exec()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    if "--show" in argv:
        # Helper mode: wake the running resident, and only become the resident
        # ourselves if nobody answered.
        if singleinstance.request_show():
            return 0
        if not singleinstance.acquire():
            singleinstance.request_show(timeout_seconds=2.0)
            return 0
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        return Application(argv).run(show_on_start=True)

    if not singleinstance.acquire():
        return 0
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    return Application(argv).run()


if __name__ == "__main__":
    sys.exit(main())
