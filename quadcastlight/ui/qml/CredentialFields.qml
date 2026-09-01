import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Client ID and secret for one integration.
//
// The secret is write-only from here: the bridge never hands it back, so the
// field shows whether one is stored and an empty box on save means "keep it".
// Nothing is echoed to the screen either, since this sits in a window people
// open while streaming.
ColumnLayout {
    id: root

    property string clientId: ""
    property bool hasSecret: false
    signal save(string clientId, string secret)

    spacing: Theme.gap
    Layout.fillWidth: true

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Text {
            text: "Client ID"
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsSmall
            Layout.preferredWidth: 62
        }

        TextField {
            id: idField
            text: root.clientId
            placeholderText: "from the developer portal"
            Layout.fillWidth: true
            color: Theme.text
            placeholderTextColor: Theme.textFaint
            font.family: Theme.monoFamily
            font.pixelSize: Theme.fsSmall
            selectByMouse: true
            background: Rectangle {
                radius: Theme.radiusSm
                color: Theme.surfaceHigh
                border.width: 1
                border.color: idField.activeFocus ? Theme.accent : Theme.line
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.gap

        Text {
            text: "Secret"
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsSmall
            Layout.preferredWidth: 62
        }

        TextField {
            id: secretField
            placeholderText: root.hasSecret ? "stored, type to replace" : "from the developer portal"
            echoMode: TextInput.Password
            Layout.fillWidth: true
            color: Theme.text
            placeholderTextColor: Theme.textFaint
            font.family: Theme.monoFamily
            font.pixelSize: Theme.fsSmall
            selectByMouse: true
            background: Rectangle {
                radius: Theme.radiusSm
                color: Theme.surfaceHigh
                border.width: 1
                border.color: secretField.activeFocus ? Theme.accent : Theme.line
            }
        }

        ActionButton {
            text: "Save"
            Layout.fillWidth: false
            Layout.preferredWidth: 84
            enabled: idField.text.trim().length > 0
            onClicked: {
                root.save(idField.text, secretField.text)
                secretField.text = ""
            }
        }
    }
}
