import QtQuick

// Mesh lines over a lit zone: reads as a microphone grille and stops the fill
// from looking like a flat swatch.
Item {
    property int rows: 8

    Column {
        anchors.fill: parent
        anchors.margins: parent.width * 0.12
        spacing: Math.max(2, (parent.height - parent.height * 0.24) / (rows + 1))

        Repeater {
            model: rows
            Rectangle {
                width: parent.width
                height: 1
                color: Qt.rgba(0, 0, 0, 0.20)
            }
        }
    }
}
