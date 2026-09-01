# PyInstaller build for the packaged release. Run: pyinstaller QuadcastLight.spec
#
# The QML lives beside the code and is found through ui/app.py's __file__, so it
# is bundled at the same relative path and needs no frozen-build special case.
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

analysis = Analysis(
    ["miclight_gui.pyw"],
    pathex=["."],
    binaries=[],
    datas=[("quadcastlight/ui/qml", "quadcastlight/ui/qml")]
    + collect_data_files("hid"),
    hiddenimports=[
        # Loaded by QML, so the analysis cannot see the import.
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQml",
    ],
    hookspath=[],
    runtime_hooks=[],
    # The window imports QtQuick, Controls, Dialogs, Effects and Layouts, and
    # the tray needs QtWidgets. Everything below is another Qt world PySide6
    # ships in the same wheel; without these the build is about three times the
    # size for modules that are never loaded.
    excludes=[
        "tkinter", "unittest", "pydoc_data",
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
        "PySide6.QtQuick3D", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
        "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
        "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    ],
    cipher=block_cipher,
    noarchive=False,
)

# PySide6 ships every Qt world in one wheel and the hook collects them as
# binaries, which `excludes` above cannot reach - that only filters Python
# imports. Qt6WebEngineCore.dll alone is 203 MB for a window that never opens a
# web view. Dropped by name here, and the packaged build is smoke-tested after
# every change to this list.
UNUSED = (
    "webengine", "qt6pdf", "qtpdf", "qt6quick3d", "qtquick3d", "qt3d", "qt63d",
    "qt6charts", "qtcharts", "qt6datavisualization", "qtdatavisualization",
    "qt6multimedia", "qtmultimedia", "qt6spatialaudio", "qt6sensors",
    "qt6serialport", "qt6bluetooth", "qt6nfc", "qt6positioning", "qt6location",
    "qt6remoteobjects", "qt6scxml", "qt6statemachine", "qt6texttospeech",
    "qt6sql", "qt6test", "qt6designer", "qt6help", "qt6uitools",
    "qt6webchannel", "qt6websockets",
)


def wanted(entry):
    name = entry[0].replace("\\", "/").lower()
    return not any(token in name for token in UNUSED)


analysis.binaries = TOC(filter(wanted, analysis.binaries))
analysis.datas = TOC(filter(wanted, analysis.datas))

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="QuadcastLight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,  # a tray app: a console window would sit behind it all session
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
