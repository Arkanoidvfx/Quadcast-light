pragma Singleton
import QtQuick

// Design tokens. One neutral chrome, one accent, one radius scale.
//
// The rule this interface is built on: the only saturated color on screen is
// the color that is currently on the microphone. Everything else stays neutral
// so the live color reads as information, not decoration.
QtObject {
    // Surfaces, coolest to warmest. No pure black: it kills depth.
    readonly property color bg: "#0b0d10"
    readonly property color surface: "#131720"
    readonly property color surfaceHigh: "#1a1f2b"
    readonly property color line: "#232a38"
    readonly property color lineStrong: "#313b4d"

    readonly property color text: "#e7ebf2"
    readonly property color textMuted: "#8b95a7"
    readonly property color textFaint: "#5d6779"

    // A single accent, used only for the primary action and focus.
    readonly property color accent: "#4ade80"
    readonly property color accentText: "#06240f"
    readonly property color danger: "#fb7185"
    readonly property color warning: "#fbbf24"

    // One radius scale, applied everywhere.
    readonly property int radiusSm: 6
    readonly property int radiusMd: 10
    readonly property int radiusLg: 16

    readonly property int gap: 10
    readonly property int gapLg: 18
    readonly property int pad: 16

    readonly property string fontFamily: "Segoe UI Variable Display"
    readonly property string fontFallback: "Segoe UI"
    readonly property string monoFamily: "Cascadia Mono"

    readonly property int fsTitle: 20
    readonly property int fsBody: 13
    readonly property int fsSmall: 12
    readonly property int fsMicro: 11

    // Motion. Short and eased; nothing here loops for decoration.
    readonly property int durFast: 120
    readonly property int durBase: 200
    readonly property int easing: Easing.OutCubic
}
