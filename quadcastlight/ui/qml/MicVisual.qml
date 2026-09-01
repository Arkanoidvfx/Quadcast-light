import QtQuick
import QtQuick.Effects

// The hero: a QuadCast S in its shock mount, lit with the exact frames the
// engine is sending to the device right now. Not a preview of what a colour
// might look like - a mirror of the hardware.
//
// Drawn from the real thing: a flat cap over a perforated grille, the gain dial
// and pattern icons under it, and an elastic shock mount rather than a plain
// yoke. The mount's diagonal bands are the feature that makes the silhouette
// recognisable, so they are worth the handful of rotated rectangles.
//
// It is also the status surface: when the device is gone the mic goes grey and
// unlit, which says more than a label would.
Item {
    id: root

    property color upperColor: "#000000"
    property color lowerColor: "#000000"
    property bool connected: true
    property bool flipped: false
    property string caption: ""

    implicitWidth: 260
    implicitHeight: 400

    readonly property real unit: Math.min(width / 5.2, height / 10.6)
    readonly property real bodyW: unit * 2.85
    readonly property real bodyH: bodyW * 2.75
    readonly property real bodyTop: unit * 0.5
    readonly property real mountW: bodyW * 1.5
    readonly property real bandAttachY: bodyTop + bodyH * 0.72
    readonly property real bandTopY: bodyTop + bodyH * 0.53
    readonly property real bandBottomY: bodyTop + bodyH * 0.99
    readonly property real rigCenterY: bodyTop + (bodyH + unit * 2.6) / 2

    // The lit zone, in rig coordinates. The glow behind the mic and the
    // bloom around it cannot anchor to the grille - it is a grandchild of
    // the rig, and QML only anchors to a parent or a sibling - so all three
    // read their geometry from here instead.
    readonly property real meshW: bodyW * 0.84
    readonly property real meshH: bodyH * 0.54
    readonly property real meshTop: bodyTop + bodyH * 0.13

    readonly property color shell: connected ? "#1b1f27" : "#181c23"
    readonly property color band: connected ? "#b9a882" : "#6d6858"
    readonly property color frame: "#2b3240"
    readonly property color blend: Qt.rgba(
        (upperColor.r + lowerColor.r) / 2,
        (upperColor.g + lowerColor.g) / 2,
        (upperColor.b + lowerColor.b) / 2, 1.0)

    Item {
        id: rig
        anchors.fill: parent

        transform: Rotation {
            id: flipRotation
            origin.x: root.width / 2
            origin.y: root.rigCenterY
            axis { x: 1; y: 0; z: 0 }
            angle: root.flipped ? 180 : 0
            Behavior on angle {
                NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
            }
        }

        transformOrigin: Item.Center
        scale: 1.0 - 0.07 * Math.sin(flipRotation.angle * Math.PI / 180)

        // Light thrown onto the surface behind the mic.
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.meshTop + root.meshH / 2 - height / 2
            width: root.bodyW * 4.2
            height: root.bodyH * 1.1
            radius: width / 2
            opacity: root.connected ? 0.5 : 0
            visible: opacity > 0
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(root.blend.r, root.blend.g, root.blend.b, 0.30) }
                GradientStop { position: 0.5; color: Qt.rgba(root.blend.r, root.blend.g, root.blend.b, 0.08) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
        }

        // Bloom of the grille alone, declared before the body so it sits
        // behind: a halo around the lit area, never a blur over it.
        MultiEffect {
            source: mesh
            x: (root.width - root.meshW) / 2
            y: root.meshTop
            width: root.meshW
            height: root.meshH
            autoPaddingEnabled: true
            blurEnabled: true
            blurMax: 40
            blur: 1.0
            brightness: 0.2
            opacity: root.connected ? 0.8 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
        }

        // --- shock mount, behind the shell ---------------------------------

        Rectangle {                      // the mount frame the shell hangs in
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.bandTopY - root.unit * 0.35
            width: root.mountW
            height: root.bandBottomY - root.bandTopY + root.unit * 0.7
            radius: root.unit * 0.5
            color: "transparent"
            border.width: Math.max(2, root.unit * 0.26)
            border.color: root.frame
        }

        // Elastic bands: each runs from the shell out to a frame corner, so it
        // is placed by its two ends rather than by a guessed length and angle,
        // which is what put the last pair outside the frame entirely.
        Repeater {
            model: [
                { side: -1, endY: root.bandTopY },
                { side: -1, endY: root.bandBottomY },
                { side: 1, endY: root.bandTopY },
                { side: 1, endY: root.bandBottomY }
            ]
            Rectangle {
                readonly property real x0: root.width / 2 + modelData.side * root.bodyW * 0.47
                readonly property real x1: root.width / 2 + modelData.side * root.mountW * 0.47
                readonly property real dx: x1 - x0
                readonly property real dy: modelData.endY - root.bandAttachY
                readonly property real span: Math.sqrt(dx * dx + dy * dy)

                width: span
                height: Math.max(2, root.unit * 0.16)
                radius: height / 2
                color: root.band
                transformOrigin: Item.Center
                x: (x0 + x1) / 2 - width / 2
                y: (root.bandAttachY + modelData.endY) / 2 - height / 2
                rotation: Math.atan2(dy, dx) * 180 / Math.PI
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
        }

        // --- stand ----------------------------------------------------------

        Rectangle {                      // column, rising into the mount
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.bandBottomY
            width: root.unit * 0.95
            height: root.unit * 1.6
            radius: root.unit * 0.12
            color: "#252c37"
        }

        Rectangle {                      // weighted base
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.bandBottomY + root.unit * 1.45
            width: root.unit * 4.0
            height: root.unit * 0.55
            radius: height / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#2b3341" }
                GradientStop { position: 1.0; color: "#1b212a" }
            }
            border.width: 1
            border.color: "#333c4b"
        }

        // --- the microphone itself -----------------------------------------

        Rectangle {
            id: body
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.bodyTop
            width: root.bodyW
            height: root.bodyH
            radius: width * 0.16      // a squared-off cylinder, not a pill
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#2b323d" }
                GradientStop { position: 0.35; color: root.shell }
                GradientStop { position: 1.0; color: "#12161c" }
            }
            border.width: 1
            border.color: "#39424f"

            // Flat cap: the tap-to-mute pad, above the grille and never lit.
            Rectangle {
                width: parent.width * 0.94
                height: parent.height * 0.085
                x: parent.width * 0.03
                y: parent.height * 0.015
                radius: parent.radius * 0.7
                color: "#1a1f27"
                border.width: 1
                border.color: "#2c343f"
            }

            // The grille. Two addressable zones, but the light diffuses through
            // the holes, so it reads as one field shading from the upper colour
            // to the lower one.
            MicMesh {
                id: mesh
                x: (parent.width - root.meshW) / 2
                y: root.meshTop - root.bodyTop
                width: root.meshW
                height: root.meshH
                upperColor: root.connected ? root.upperColor : "#151a21"
                lowerColor: root.connected ? root.lowerColor : "#131820"
            }

            // Polar pattern icons, then the gain dial.
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.715
                spacing: parent.width * 0.09
                Repeater {
                    model: 4
                    Rectangle {
                        width: body.width * 0.055
                        height: width
                        radius: width / 2
                        color: "transparent"
                        border.width: 1
                        border.color: "#4a5464"
                    }
                }
            }

            Rectangle {                  // gain dial
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.785
                width: parent.width * 0.2
                height: width
                radius: width / 2
                color: "#232a34"
                border.width: 1
                border.color: "#4a5464"

                Rectangle {              // pointer
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * 0.12
                    width: 1
                    height: parent.height * 0.34
                    color: "#8b97a8"
                }
            }
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        text: root.connected ? root.caption : "Microphone not found"
        color: root.connected ? Theme.text : Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsBody
        font.weight: Font.DemiBold
    }
}
