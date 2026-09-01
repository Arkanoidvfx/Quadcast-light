import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Three intents, one shape. The press state moves the button down a pixel so a
// click feels physical rather than instantaneous.
Button {
    id: root

    property string intent: "default"  // default | primary | danger
    property bool busy: false

    readonly property color _fill: intent === "primary" ? Theme.accent
                                 : intent === "danger" ? "transparent"
                                 : Theme.surfaceHigh
    readonly property color _label: intent === "primary" ? Theme.accentText
                                  : intent === "danger" ? Theme.danger
                                  : Theme.text
    readonly property color _edge: intent === "primary" ? Theme.accent
                                 : intent === "danger" ? Qt.rgba(0.98, 0.45, 0.52, 0.45)
                                 : Theme.lineStrong

    implicitHeight: 34
    enabled: !busy
    Layout.fillWidth: true

    background: Rectangle {
        radius: Theme.radiusMd
        color: root._fill
        opacity: root.enabled ? (root.hovered ? 0.88 : 1.0) : 0.45
        border.width: 1
        border.color: root._edge
        y: root.pressed ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
        Behavior on y { NumberAnimation { duration: 60 } }
    }

    contentItem: Text {
        text: root.busy ? "Working..." : root.text
        color: root._label
        opacity: root.enabled ? 1.0 : 0.6
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsSmall
        font.weight: root.intent === "primary" ? Font.DemiBold : Font.Normal
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        y: root.pressed ? 1 : 0
    }
}
