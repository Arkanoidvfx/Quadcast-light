import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Label, track, and a monospaced readout that does not reflow as digits change.
RowLayout {
    id: root

    property string label: ""
    property int from: 0
    property int to: 100
    property int value: 0
    property string suffix: "%"
    signal moved(int value)

    spacing: Theme.gap
    Layout.fillWidth: true

    Text {
        text: root.label
        color: Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fsSmall
        Layout.preferredWidth: 62
    }

    Slider {
        id: slider
        from: root.from
        to: root.to
        value: root.value
        stepSize: 1
        Layout.fillWidth: true
        onMoved: root.moved(Math.round(value))

        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth
            height: 4
            radius: 2
            color: Theme.line

            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: Theme.lineStrong
            }
        }

        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: 16
            height: 16
            radius: 8
            color: slider.pressed ? Theme.accent : Theme.text
            border.width: 0
            scale: slider.pressed ? 0.92 : 1.0
            Behavior on scale { NumberAnimation { duration: Theme.durFast } }
            Behavior on color { ColorAnimation { duration: Theme.durFast } }
        }
    }

    Text {
        text: root.value + root.suffix
        color: Theme.text
        font.family: Theme.monoFamily
        font.pixelSize: Theme.fsSmall
        horizontalAlignment: Text.AlignRight
        Layout.preferredWidth: 44
    }
}
