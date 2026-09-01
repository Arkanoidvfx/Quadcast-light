import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One channel's notification, collapsed to a single row until you open it.
//
// The list has to work for three channels and for thirty, so the row carries
// only what identifies the notification at a glance (the color, and whether it
// differs from the shared one) and the settings unfold on demand.
Rectangle {
    id: root

    property string channel: ""
    property color swatch: "#000000"
    property int times: 8
    property real onSeconds: 1.5
    property real offSeconds: 1.5
    property bool custom: false
    property bool expanded: false

    signal toggle()
    signal pickColor()
    signal timesEdited(int value)
    signal onSecondsEdited(real value)
    signal offSecondsEdited(real value)
    signal test()
    signal reset()

    Layout.fillWidth: true
    implicitHeight: content.implicitHeight + Theme.gap
    radius: Theme.radiusMd
    color: root.expanded ? Theme.surfaceHigh : "transparent"
    border.width: 1
    border.color: root.expanded ? Theme.lineStrong : Theme.line
    Behavior on color { ColorAnimation { duration: Theme.durFast } }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.gap / 2
        spacing: Theme.gap

        // Only the header toggles. The click target sits under the row so the
        // swatch keeps its own click, and the sliders below are never on it.
        Item {
            Layout.fillWidth: true
            implicitHeight: 30

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.toggle()
            }

            RowLayout {
                anchors.fill: parent
                spacing: Theme.gap

                Rectangle {
                    width: 26
                    height: 26
                    radius: Theme.radiusSm
                    color: root.swatch
                    border.width: 1
                    border.color: Theme.lineStrong
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.pickColor()
                    }
                }

                Text {
                    text: root.channel
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fsSmall
                }

                Text {
                    // Says at a glance which channels carry their own
                    // notification, without a badge on every row.
                    visible: root.custom
                    text: "custom"
                    color: Theme.textFaint
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fsMicro
                }

                Item { Layout.fillWidth: true }

                Text {
                    text: root.times + "x"
                    color: Theme.textMuted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.fsMicro
                }

                Text {
                    text: "⌄"
                    color: Theme.textMuted
                    font.pixelSize: 14
                    rotation: root.expanded ? 180 : 0
                    Behavior on rotation {
                        NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: Theme.gap / 2
            spacing: Theme.gap
            visible: root.expanded

            LabeledSlider {
                label: "Repeats"
                from: 1
                to: 30
                value: root.times
                suffix: "x"
                onMoved: root.timesEdited(value)
            }
            LabeledSlider {
                label: "Lit for"
                from: 5
                to: 300
                value: Math.round(root.onSeconds * 100)
                suffix: " ms"
                onMoved: root.onSecondsEdited(value / 100)
            }
            LabeledSlider {
                label: "Dark for"
                from: 5
                to: 300
                value: Math.round(root.offSeconds * 100)
                suffix: " ms"
                onMoved: root.offSecondsEdited(value / 100)
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                ActionButton {
                    text: "Test"
                    Layout.fillWidth: false
                    Layout.preferredWidth: 84
                    onClicked: root.test()
                }
                ActionButton {
                    text: "Use shared"
                    Layout.fillWidth: false
                    Layout.preferredWidth: 110
                    enabled: root.custom
                    onClicked: root.reset()
                }
                Item { Layout.fillWidth: true }
            }
        }
    }
}
