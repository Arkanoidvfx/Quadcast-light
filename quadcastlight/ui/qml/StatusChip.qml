import QtQuick
import QtQuick.Controls

// The label says the state in words and the dot only reinforces it, so the
// chip still reads without relying on colour alone.
Rectangle {
    id: root

    property string label: ""
    property string state: "off"   // ok | busy | attention | off
    property string detail: ""

    readonly property color _tone: state === "ok" ? Theme.accent
                                 : state === "attention" ? Theme.warning
                                 : state === "bad" ? Theme.danger
                                 : state === "busy" ? Theme.textMuted
                                 : Theme.textFaint

    implicitWidth: row.implicitWidth + 20
    implicitHeight: 26
    radius: height / 2
    color: Theme.surface
    border.width: 1
    border.color: Theme.line

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 7
            height: 7
            radius: 3.5
            color: root._tone
            Behavior on color { ColorAnimation { duration: Theme.durBase } }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: root.state === "attention" ? Theme.text : Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsMicro
        }
    }

    ToolTip.visible: hover.hovered && root.detail.length > 0
    ToolTip.text: root.detail
    ToolTip.delay: 400

    HoverHandler { id: hover }
}
