import QtQuick

// The perforated grille the light actually comes through.
//
// The QuadCast's front is a dense field of round holes, not the flat panel a
// gradient rectangle suggests, and the holes are what carry the colour. Colour
// is bound per row rather than per dot: twenty bindings instead of three
// hundred, for a difference nobody can see.
Item {
    id: root

    property color upperColor: "#000000"
    property color lowerColor: "#000000"
    property int rows: 27
    property int columns: 13

    readonly property real cell: width / (columns + 0.5)
    readonly property real dot: cell * 0.66

    // The shell behind the holes, with the colour bleeding faintly through it.
    // Without the bleed the panel goes to near black at a low brightness, which
    // is darker than the real grille ever looks.
    Rectangle {
        anchors.fill: parent
        radius: width * 0.06
        color: "#0c0f14"

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            opacity: 0.28
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.upperColor }
                GradientStop { position: 1.0; color: root.lowerColor }
            }
        }
    }

    Column {
        anchors.fill: parent
        anchors.topMargin: root.cell * 0.35
        spacing: (root.height - root.cell * 0.7 - root.rows * root.dot) / (root.rows - 1)

        Repeater {
            model: root.rows

            Row {
                // Every other row is offset by half a cell, which is what makes
                // a hole pattern read as a mesh and not as a grid.
                readonly property bool odd: index % 2 === 1
                readonly property real t: index / (root.rows - 1)
                readonly property color tint: Qt.rgba(
                    root.upperColor.r + (root.lowerColor.r - root.upperColor.r) * t,
                    root.upperColor.g + (root.lowerColor.g - root.upperColor.g) * t,
                    root.upperColor.b + (root.lowerColor.b - root.upperColor.b) * t,
                    1.0)

                x: odd ? root.cell * 0.5 : 0
                spacing: root.cell - root.dot

                Repeater {
                    model: parent.odd ? root.columns - 1 : root.columns

                    Rectangle {
                        width: root.dot
                        height: root.dot
                        radius: root.dot / 2
                        color: parent.tint
                    }
                }
            }
        }
    }
}
