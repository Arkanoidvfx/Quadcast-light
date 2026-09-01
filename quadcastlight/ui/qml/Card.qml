import QtQuick
import QtQuick.Layouts

// A grouped set of controls. Elevation is carried by a hairline and a slightly
// lifted surface, not by a drop shadow: at this density shadows just add noise.
Rectangle {
    id: root

    property string title: ""
    default property alias content: body.data

    color: Theme.surface
    border.width: 1
    border.color: Theme.line
    radius: Theme.radiusLg
    implicitHeight: layout.implicitHeight + Theme.pad * 2
    Layout.fillWidth: true

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.gap

        Text {
            visible: root.title.length > 0
            text: root.title
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsSmall
            font.weight: Font.DemiBold
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: Theme.gap
        }
    }
}
