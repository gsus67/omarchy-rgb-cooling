import QtQuick
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Full colour picker: saturation/brightness square, hue bar, hex field and a
// row of quick swatches. Emits `picked("#rrggbb")` while dragging (the caller
// debounces) and keeps its own HSV so dragging through black or grey does not
// lose the hue.
Item {
  id: root

  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property var swatches: []
  property string value: "#ffffff"
  property var t: function(text) { return text }

  signal picked(string color)

  property real hue: 0
  property real saturation: 0
  property real brightness: 1
  property bool editing: false

  implicitWidth: 320
  implicitHeight: column.implicitHeight

  function hex(c) {
    function part(v) { var s = Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16); return s.length < 2 ? "0" + s : s }
    return "#" + part(c.r) + part(c.g) + part(c.b)
  }
  function current() { return hex(Qt.hsva(hue, saturation, brightness, 1)) }
  function emitCurrent() { picked(current()) }

  // Follow external changes (another device, a swatch, the core's re-read)
  // without fighting the user while they drag.
  onValueChanged: if (!editing) syncFrom(value)
  Component.onCompleted: syncFrom(value)
  function syncFrom(text) {
    if (!/^#[0-9a-fA-F]{6}$/.test(String(text))) return
    var c = Qt.color(text)
    if (c.hsvSaturation > 0 && c.hsvValue > 0) hue = Math.max(0, c.hsvHue)
    saturation = c.hsvValue > 0 ? c.hsvSaturation : saturation
    brightness = c.hsvValue
    hexField.text = String(text).toLowerCase()
  }

  Column {
    id: column
    width: parent.width
    spacing: Style.space(10)

    // Saturation (left to right) and brightness (top to bottom) for the hue.
    Rectangle {
      id: square
      width: parent.width
      height: Math.round(width * 0.5)
      radius: Style.space(4)
      color: Qt.hsva(root.hue, 1, 1, 1)
      clip: true

      Rectangle {
        anchors.fill: parent
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: "#ffffffff" }
          GradientStop { position: 1; color: "#00ffffff" }
        }
      }
      Rectangle {
        anchors.fill: parent
        gradient: Gradient {
          GradientStop { position: 0; color: "#00000000" }
          GradientStop { position: 1; color: "#ff000000" }
        }
      }
      Rectangle {
        width: Style.space(14); height: width; radius: width / 2
        x: root.saturation * square.width - width / 2
        y: (1 - root.brightness) * square.height - height / 2
        color: "transparent"
        border.width: 2
        border.color: root.brightness > 0.5 ? "#000000" : "#ffffff"
      }
      MouseArea {
        anchors.fill: parent
        preventStealing: true
        function pick(mouse) {
          root.saturation = Math.max(0, Math.min(1, mouse.x / width))
          root.brightness = Math.max(0, Math.min(1, 1 - mouse.y / height))
          hexField.text = root.current()
          root.emitCurrent()
        }
        onPressed: function(mouse) { root.editing = true; pick(mouse) }
        onPositionChanged: function(mouse) { if (pressed) pick(mouse) }
        onReleased: root.editing = false
      }
    }

    // Hue bar.
    Rectangle {
      id: hueBar
      width: parent.width
      height: Style.space(14)
      radius: height / 2
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.000; color: "#ff0000" }
        GradientStop { position: 0.167; color: "#ffff00" }
        GradientStop { position: 0.333; color: "#00ff00" }
        GradientStop { position: 0.500; color: "#00ffff" }
        GradientStop { position: 0.667; color: "#0000ff" }
        GradientStop { position: 0.833; color: "#ff00ff" }
        GradientStop { position: 1.000; color: "#ff0000" }
      }
      Rectangle {
        width: Style.space(6); height: parent.height + Style.space(6)
        anchors.verticalCenter: parent.verticalCenter
        x: root.hue * hueBar.width - width / 2
        radius: width / 2
        color: "#ffffff"
        border.width: 1
        border.color: "#000000"
      }
      MouseArea {
        anchors.fill: parent
        anchors.margins: -Style.space(4)
        preventStealing: true
        function pick(mouse) {
          root.hue = Math.max(0, Math.min(0.9999, (mouse.x - Style.space(4)) / hueBar.width))
          if (root.saturation === 0) root.saturation = 1
          if (root.brightness === 0) root.brightness = 1
          hexField.text = root.current()
          root.emitCurrent()
        }
        onPressed: function(mouse) { root.editing = true; pick(mouse) }
        onPositionChanged: function(mouse) { if (pressed) pick(mouse) }
        onReleased: root.editing = false
      }
    }

    // Preview + exact hex value.
    Row {
      width: parent.width
      spacing: Style.space(10)

      Rectangle {
        id: preview
        width: Style.spacing.controlHeight
        height: width
        radius: Style.space(4)
        color: root.current()
        border.width: 1
        border.color: Qt.darker(root.foreground, 2)
      }

      TextField {
        id: hexField
        width: parent.width - preview.width - parent.spacing
        anchors.verticalCenter: parent.verticalCenter
        foreground: root.foreground
        maximumLength: 7
        placeholderText: "#rrggbb"
        validator: RegularExpressionValidator { regularExpression: /^#?[0-9a-fA-F]{0,6}$/ }
        onAccepted: {
          var text = String(hexField.text).trim()
          if (text.charAt(0) !== "#") text = "#" + text
          if (/^#[0-9a-fA-F]{6}$/.test(text)) { root.syncFrom(text.toLowerCase()); root.emitCurrent() }
        }
      }
    }

    // Quick swatches.
    Flow {
      width: parent.width
      spacing: Style.space(6)

      Repeater {
        model: root.swatches

        Rectangle {
          required property var modelData
          width: Style.space(26)
          height: width
          radius: width / 2
          color: modelData.color
          border.width: root.current() === modelData.color ? 2 : 1
          border.color: root.current() === modelData.color ? root.foreground : Qt.darker(root.foreground, 2)

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: { root.syncFrom(parent.modelData.color); root.emitCurrent() }
          }
        }
      }
    }
  }
}
