import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: window

    width: 1000
    height: 660
    minimumWidth: 860
    minimumHeight: 600
    visible: false
    title: "QuadcastLight"
    color: Theme.bg

    // Presets worth one click. Neutral chrome, so these swatches and the mic
    // are the only color on screen.
    readonly property var swatches: [
        "#8b5cf6", "#22d3ee", "#10b981", "#f43f5e",
        "#f59e0b", "#38bdf8", "#ec4899", "#fb7185",
        "#fde68a", "#ffffff", "#2563eb", "#000000"
    ]

    ColorDialog {
        id: colorDialog
        property string target: "color"
        property int paletteIndex: -1
        property string channelName: ""
        selectedColor: bridge.colorHex
        onAccepted: {
            if (target === "color")
                bridge.setColorHex(selectedColor.toString())
            else if (target === "palette" && paletteIndex >= 0)
                bridge.setPaletteColor(paletteIndex, selectedColor.toString())
            else if (target === "paletteAdd")
                bridge.addPaletteColor(selectedColor.toString())
            else if (target === "notification")
                bridge.notificationColor = selectedColor.toString()
            else if (target === "mute")
                bridge.discordMuteColor = selectedColor.toString()
            else if (target === "deafen")
                bridge.discordDeafenColor = selectedColor.toString()
            else if (target === "channel")
                bridge.setChannelColor(channelName, selectedColor.toString())
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.gapLg
        spacing: Theme.gapLg

        // Header: nothing but live hardware truth. The app names itself in the
        // title bar, and the device names itself over its own picture.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap

            Item { Layout.fillWidth: true }

            // The microphone has no chip: the render to the left is a louder
            // statement of the same thing, and says it in words when it is gone.
            StatusChip {
                label: bridge.discordSummary
                state: bridge.discordHealth
                detail: bridge.discordStatus
            }
            StatusChip {
                label: bridge.twitchSummary
                state: bridge.twitchHealth
                detail: bridge.twitchStatus
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gapLg

            // The mic is the subject of the whole window, so it gets the space
            // and everything else arranges itself around it. Its one action and
            // any news sit directly underneath, as part of the same object.
            ColumnLayout {
                Layout.preferredWidth: 300
                Layout.fillHeight: true
                spacing: Theme.gap

                Text {
                    text: "HyperX QuadCast S lighting"
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fsSmall
                    Layout.alignment: Qt.AlignHCenter
                }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.surface
                radius: Theme.radiusLg
                border.width: 1
                border.color: Theme.line

                MicVisual {
                    anchors.fill: parent
                    anchors.margins: Theme.pad
                    upperColor: bridge.upperHex
                    lowerColor: bridge.lowerHex
                    connected: bridge.deviceConnected
                    caption: bridge.lightLabel
                    flipped: bridge.micFlipped
                }

                // Turn the render over for a mic hung under a boom arm. It
                // changes nothing on the device, only which way up the picture
                // matches the desk.
                Rectangle {
                    id: flipButton
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: Theme.gap
                    width: 30
                    height: 30
                    radius: Theme.radiusSm
                    color: flipArea.containsMouse ? Theme.surfaceHigh : "transparent"
                    border.width: 1
                    border.color: bridge.micFlipped ? Theme.lineStrong
                                : flipArea.containsMouse ? Theme.lineStrong : Theme.line
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                    Text {
                        anchors.centerIn: parent
                        text: "\u21C5"
                        color: bridge.micFlipped ? Theme.text : Theme.textMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: 15
                        rotation: bridge.micFlipped ? 180 : 0
                        Behavior on rotation {
                            NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
                        }
                    }

                    MouseArea {
                        id: flipArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: bridge.micFlipped = !bridge.micFlipped
                    }

                    ToolTip.visible: flipArea.containsMouse
                    ToolTip.text: "Flip the mic, for a boom arm mount"
                    ToolTip.delay: 500
                }
            }

                ActionButton {
                    text: "Save to mic"
                    intent: "primary"
                    Layout.fillWidth: false
                    Layout.preferredWidth: 180
                    Layout.alignment: Qt.AlignHCenter
                    onClicked: bridge.saveToMic()
                }

                // Only appears when there is something to say that the mic
                // itself is not already showing.
                Text {
                    visible: text.length > 0
                    text: bridge.statusMessage
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fsMicro
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.gap

                TabBar {
                    id: tabs
                    objectName: "tabs"
                    Layout.fillWidth: false
                    Layout.alignment: Qt.AlignLeft
                    spacing: 4
                    background: Item {}

                    Repeater {
                        model: ["Light", "Discord", "Twitch", "App"]
                        TabButton {
                            text: modelData
                            implicitHeight: 30
                            implicitWidth: 92
                            background: Rectangle {
                                radius: Theme.radiusMd
                                color: checked ? Theme.surfaceHigh : "transparent"
                                border.width: 1
                                border.color: checked ? Theme.lineStrong : "transparent"
                            }
                            contentItem: Text {
                                text: parent.text
                                color: parent.checked ? Theme.text : Theme.textMuted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fsSmall
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }

                StackLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    currentIndex: tabs.currentIndex

                    // ---- Light -------------------------------------------
                    ScrollView {
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: parent.width
                            spacing: Theme.gap

                            Card {
                                title: "Color"

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap

                                    Rectangle {
                                        width: 34
                                        height: 34
                                        radius: Theme.radiusSm
                                        color: bridge.colorHex
                                        border.width: 1
                                        border.color: Theme.lineStrong
                                    }

                                    TextField {
                                        id: hexField
                                        text: bridge.colorHex
                                        Layout.preferredWidth: 96
                                        color: Theme.text
                                        font.family: Theme.monoFamily
                                        font.pixelSize: Theme.fsSmall
                                        selectByMouse: true
                                        background: Rectangle {
                                            radius: Theme.radiusSm
                                            color: Theme.surfaceHigh
                                            border.width: 1
                                            border.color: hexField.activeFocus ? Theme.accent : Theme.line
                                        }
                                        onEditingFinished: bridge.setColorHex(text)
                                    }

                                    ActionButton {
                                        text: "Pick"
                                        Layout.fillWidth: false
                                        Layout.preferredWidth: 74
                                        onClicked: {
                                            colorDialog.target = "color"
                                            colorDialog.selectedColor = bridge.colorHex
                                            colorDialog.open()
                                        }
                                    }

                                    Item { Layout.fillWidth: true }
                                }

                                LabeledSlider {
                                    label: "Brightness"
                                    value: bridge.brightness
                                    onMoved: bridge.brightness = value
                                }

                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Repeater {
                                        model: window.swatches
                                        Rectangle {
                                            width: 28
                                            height: 28
                                            radius: Theme.radiusSm
                                            color: modelData
                                            border.width: 1
                                            border.color: bridge.colorHex.toLowerCase() === modelData
                                                          ? Theme.accent : Theme.lineStrong
                                            scale: swatchArea.pressed ? 0.94 : 1.0
                                            Behavior on scale { NumberAnimation { duration: Theme.durFast } }
                                            MouseArea {
                                                id: swatchArea
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: bridge.setColorHex(modelData)
                                            }
                                        }
                                    }
                                }
                            }

                            Card {
                                title: "Effect"

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap

                                    ComboBox {
                                        id: effectBox
                                        Layout.preferredWidth: 160
                                        model: bridge.effectLabels
                                        currentIndex: bridge.effectKeys.indexOf(bridge.effect)
                                        onActivated: bridge.effect = bridge.effectKeys[currentIndex]
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsSmall
                                        background: Rectangle {
                                            radius: Theme.radiusMd
                                            color: Theme.surfaceHigh
                                            border.width: 1
                                            border.color: Theme.line
                                        }
                                        contentItem: Text {
                                            leftPadding: 10
                                            text: effectBox.displayText
                                            color: Theme.text
                                            font: effectBox.font
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                        indicator: Canvas {
                                            x: effectBox.width - width - 10
                                            y: effectBox.topPadding + (effectBox.availableHeight - height) / 2
                                            width: 10
                                            height: 6
                                            onPaint: {
                                                var ctx = getContext("2d")
                                                ctx.reset()
                                                ctx.strokeStyle = Theme.textMuted
                                                ctx.lineWidth = 1.5
                                                ctx.beginPath()
                                                ctx.moveTo(0, 0)
                                                ctx.lineTo(width / 2, height)
                                                ctx.lineTo(width, 0)
                                                ctx.stroke()
                                            }
                                        }
                                    }

                                    Item { Layout.fillWidth: true }
                                }

                                LabeledSlider {
                                    label: "Flow speed"
                                    from: 1
                                    value: bridge.speed
                                    suffix: ""
                                    onMoved: bridge.speed = value
                                }

                                // Only shown for the preset that actually uses it.
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    visible: bridge.paletteRelevant

                                    Text {
                                        text: "Flow colors"
                                        color: Theme.textFaint
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsMicro
                                    }

                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        Repeater {
                                            model: bridge.flowPalette
                                            Rectangle {
                                                width: 34
                                                height: 28
                                                radius: Theme.radiusSm
                                                color: modelData
                                                border.width: 1
                                                border.color: Theme.line
                                                MouseArea {
                                                    anchors.fill: parent
                                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: function (mouse) {
                                                        if (mouse.button === Qt.RightButton) {
                                                            bridge.removePaletteColor(index)
                                                        } else {
                                                            colorDialog.target = "palette"
                                                            colorDialog.paletteIndex = index
                                                            colorDialog.selectedColor = modelData
                                                            colorDialog.open()
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        Rectangle {
                                            width: 34
                                            height: 28
                                            radius: Theme.radiusSm
                                            color: "transparent"
                                            border.width: 1
                                            border.color: Theme.lineStrong
                                            Text {
                                                anchors.centerIn: parent
                                                text: "+"
                                                color: Theme.textMuted
                                                font.pixelSize: 15
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    colorDialog.target = "paletteAdd"
                                                    colorDialog.selectedColor = bridge.colorHex
                                                    colorDialog.open()
                                                }
                                            }
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Theme.gap

                                        Text {
                                            text: "Click a color to change it, right click to remove."
                                            color: Theme.textFaint
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fsMicro
                                            Layout.fillWidth: true
                                        }

                                        ActionButton {
                                            text: "Reset"
                                            Layout.fillWidth: false
                                            Layout.preferredWidth: 74
                                            onClicked: bridge.resetPalette()
                                        }
                                    }
                                }
                            }

                            Card {
                                title: "Zones"

                                LabeledSlider {
                                    label: "Upper"
                                    value: bridge.upperBrightness
                                    onMoved: bridge.upperBrightness = value
                                }
                                LabeledSlider {
                                    label: "Lower"
                                    value: bridge.lowerBrightness
                                    onMoved: bridge.lowerBrightness = value
                                }
                                Text {
                                    text: "The protocol addresses two zones. Individual LEDs inside a zone cannot be set."
                                    color: Theme.textFaint
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fsMicro
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }

                    // ---- Discord ----------------------------------------
                    ScrollView {
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: parent.width
                            spacing: Theme.gap

                            Card {
                                title: "Discord"

                                Toggle {
                                    label: "React to voice state"
                                    hint: bridge.discordStatus
                                    checked: bridge.discordEnabled
                                    onToggled: bridge.discordEnabled = value
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap
                                    enabled: bridge.discordEnabled
                                    opacity: enabled ? 1.0 : 0.45

                                    ColorField {
                                        label: "Muted"
                                        value: bridge.discordMuteColor
                                        onPick: {
                                            colorDialog.target = "mute"
                                            colorDialog.selectedColor = bridge.discordMuteColor
                                            colorDialog.open()
                                        }
                                    }
                                    ColorField {
                                        label: "Deafened"
                                        value: bridge.discordDeafenColor
                                        onPick: {
                                            colorDialog.target = "deafen"
                                            colorDialog.selectedColor = bridge.discordDeafenColor
                                            colorDialog.open()
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                }

                                LabeledSlider {
                                    label: "Alert level"
                                    value: bridge.discordBrightness
                                    enabled: bridge.discordEnabled
                                    onMoved: bridge.discordBrightness = value
                                }

                                Toggle {
                                    label: "Restore the effect afterwards"
                                    hint: "Off leaves the alert color until you change it yourself."
                                    checked: bridge.discordRestoreDefault
                                    onToggled: bridge.discordRestoreDefault = value
                                }

                                CredentialFields {
                                    clientId: bridge.discordClientId
                                    hasSecret: bridge.discordHasSecret
                                    onSave: function (clientId, secret) {
                                        bridge.saveDiscordCredentials(clientId, secret)
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap
                                    ActionButton {
                                        text: "Authorize Discord"
                                        intent: bridge.discordNeedsAuth ? "primary" : "default"
                                        Layout.fillWidth: false
                                        Layout.preferredWidth: 160
                                        onClicked: bridge.authorizeDiscord()
                                    }
                                    Text {
                                        visible: bridge.discordNeedsAuth
                                        text: "Authorization expired. Sign in to Discord again."
                                        color: Theme.warning
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsMicro
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                            }

                        }
                    }

                    // ---- Twitch -------------------------------------
                    ScrollView {
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: parent.width
                            spacing: Theme.gap

                            Card {
                                title: "Twitch"

                                Toggle {
                                    label: "Blink when a channel goes live"
                                    hint: bridge.twitchStatus
                                    checked: bridge.twitchEnabled
                                    onToggled: bridge.twitchEnabled = value
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap
                                    enabled: bridge.twitchEnabled
                                    opacity: enabled ? 1.0 : 0.45

                                    Text {
                                        text: "Channels"
                                        color: Theme.textMuted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsSmall
                                        Layout.preferredWidth: 62
                                    }
                                    TextField {
                                        id: channelsField
                                        text: bridge.twitchChannels
                                        // Real names read as an example far better than "channel1, channel2".
                                        placeholderText: "forsen, xqc"
                                        Layout.fillWidth: true
                                        color: Theme.text
                                        placeholderTextColor: Theme.textFaint
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsSmall
                                        selectByMouse: true
                                        background: Rectangle {
                                            radius: Theme.radiusSm
                                            color: Theme.surfaceHigh
                                            border.width: 1
                                            border.color: channelsField.activeFocus ? Theme.accent : Theme.line
                                        }
                                        onEditingFinished: bridge.twitchChannels = text
                                    }
                                    ActionButton {
                                        text: "Authorize"
                                        Layout.fillWidth: false
                                        Layout.preferredWidth: 100
                                        onClicked: bridge.authorizeTwitch()
                                    }
                                }

                                CredentialFields {
                                    clientId: bridge.twitchClientId
                                    hasSecret: bridge.twitchHasSecret
                                    onSave: function (clientId, secret) {
                                        bridge.saveTwitchCredentials(clientId, secret)
                                    }
                                }

                                Text {
                                    text: "Without Twitch credentials QuadcastLight checks a public status API "
                                        + "every few minutes instead, so a notification can lag behind the stream."
                                    color: Theme.textFaint
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fsMicro
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            Card {
                                title: "Notification"

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Theme.gap
                                    ColorField {
                                        label: "Color"
                                        value: bridge.notificationColor
                                        onPick: {
                                            colorDialog.target = "notification"
                                            colorDialog.selectedColor = bridge.notificationColor
                                            colorDialog.open()
                                        }
                                    }
                                    ActionButton {
                                        text: "Test notification"
                                        Layout.preferredWidth: 150
                                        Layout.fillWidth: false
                                        onClicked: bridge.testNotification()
                                    }
                                    Item { Layout.fillWidth: true }
                                }

                                LabeledSlider {
                                    label: "Repeats"
                                    from: 1
                                    to: 30
                                    value: bridge.notificationTimes
                                    suffix: "x"
                                    onMoved: bridge.notificationTimes = value
                                }

                                // Stored in seconds; the sliders work in
                                // hundredths so a whole flash can be tuned
                                // without a spin box.
                                LabeledSlider {
                                    label: "Lit for"
                                    from: 5
                                    to: 300
                                    value: Math.round(bridge.notificationOnSeconds * 100)
                                    suffix: " ms"
                                    onMoved: bridge.notificationOnSeconds = value / 100
                                }

                                LabeledSlider {
                                    label: "Dark for"
                                    from: 5
                                    to: 300
                                    value: Math.round(bridge.notificationOffSeconds * 100)
                                    suffix: " ms"
                                    onMoved: bridge.notificationOffSeconds = value / 100
                                }
                            }

                            Card {
                                title: "Per channel"

                                Toggle {
                                    label: "Give each channel its own notification"
                                    hint: "Off: every channel flashes the same way."
                                    checked: bridge.notificationPerChannel
                                    onToggled: bridge.notificationPerChannel = value
                                }

                                ColumnLayout {
                                    id: channelList
                                    objectName: "channelList"
                                    Layout.fillWidth: true
                                    spacing: 4
                                    visible: bridge.notificationPerChannel

                                    // Which row is open, by channel name, so the
                                    // list keeps its state as rows come and go.
                                    property string openChannel: ""

                                    Repeater {
                                        model: bridge.channelNotifications

                                        ChannelNotification {
                                            channel: modelData.name
                                            swatch: modelData.color
                                            times: modelData.times
                                            onSeconds: modelData.onSeconds
                                            offSeconds: modelData.offSeconds
                                            custom: modelData.custom
                                            expanded: channelList.openChannel === modelData.name

                                            onToggle: channelList.openChannel =
                                                (channelList.openChannel === modelData.name
                                                 ? "" : modelData.name)
                                            onPickColor: {
                                                colorDialog.target = "channel"
                                                colorDialog.channelName = modelData.name
                                                colorDialog.selectedColor = modelData.color
                                                colorDialog.open()
                                            }
                                            onTimesEdited: function (value) {
                                                bridge.setChannelTimes(modelData.name, value)
                                            }
                                            onOnSecondsEdited: function (value) {
                                                bridge.setChannelOnSeconds(modelData.name, value)
                                            }
                                            onOffSecondsEdited: function (value) {
                                                bridge.setChannelOffSeconds(modelData.name, value)
                                            }
                                            onTest: bridge.testChannelNotification(modelData.name)
                                            onReset: bridge.resetChannelNotification(modelData.name)
                                        }
                                    }

                                    Text {
                                        visible: bridge.channelNotifications.length === 0
                                        text: "Add Twitch channels above and they will appear here."
                                        color: Theme.textFaint
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fsMicro
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }

                        }
                    }

                    // ---- App -------------------------------------
                    ScrollView {
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: parent.width
                            spacing: Theme.gap

                            Card {
                                title: "Windows"

                                Toggle {
                                    label: "Start QuadcastLight with Windows"
                                    hint: "Closing the window keeps it in the tray. Exit from the tray menu quits."
                                    checked: bridge.startWithWindows
                                    onToggled: bridge.startWithWindows = value
                                }
                            }

                            Card {
                                title: "Troubleshooting"

                                Text {
                                    text: "If an automation stops reacting, the log says why."
                                    color: Theme.textMuted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fsSmall
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                                TextEdit {
                                    text: bridge.logPath
                                    readOnly: true
                                    selectByMouse: true
                                    color: Theme.textFaint
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.fsMicro
                                    wrapMode: Text.WrapAnywhere
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }
            }
        }

    }
}
