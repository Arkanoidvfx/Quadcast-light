import QtQuick
import QtQuick.Layouts

// A labelled color swatch that opens the system picker. Used wherever a color
// is one setting among several, rather than the main color.
ColumnLayout {
    id: root

    property string label: ""
    property color value: "#000000"
    signal pick()

    spacing: 4

    Text {
        text: root.label
        color: Theme.textFaint
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsMicro
    }

    Rectangle {
        width: 76
        height: 30
        radius: Theme.radiusSm
        color: root.value
        border.width: 1
        border.color: Theme.lineStrong
        scale: area.pressed ? 0.97 : 1.0
        Behavior on scale { NumberAnimation { duration: Theme.durFast } }

        MouseArea {
            id: area
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.pick()
        }
    }
}
