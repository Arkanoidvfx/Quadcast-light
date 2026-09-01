import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A switch with its label, because the stock check indicator does not survive
// this theme and a switch reads better for "this automation is on".
RowLayout {
    id: root

    property string label: ""
    property string hint: ""
    property bool checked: false
    signal toggled(bool value)

    spacing: Theme.gap
    Layout.fillWidth: true

    ColumnLayout {
        spacing: 1
        Layout.fillWidth: true
        Text {
            text: root.label
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsSmall
        }
        Text {
            visible: root.hint.length > 0
            text: root.hint
            color: Theme.textFaint
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsMicro
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    Rectangle {
        id: track
        width: 40
        height: 22
        radius: height / 2
        color: root.checked ? Theme.accent : Theme.surfaceHigh
        border.width: 1
        border.color: root.checked ? Theme.accent : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: Theme.durFast } }

        Rectangle {
            width: 16
            height: 16
            radius: 8
            y: 3
            x: root.checked ? track.width - width - 3 : 3
            color: root.checked ? Theme.accentText : Theme.textMuted
            Behavior on x { NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggled(!root.checked)
        }
    }
}
