import QtQuick
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Lighting tab: device cards, then the selected device's effect, colour,
// speed, brightness and "Save to device". All state and requests live in the
// panel (RgbCooling.qml); this file only lays them out.
Column {
  id: tab

  required property var panel
  readonly property var bar: panel.bar
  readonly property var lighting: panel.lighting
  readonly property var mode: panel.currentMode
  readonly property bool editable: panel.canWrite && lighting !== null
  readonly property color dim: Qt.darker(bar.foreground, 1.4)

  spacing: Style.space(12)

  function t(text) { return panel.t(text) }
  function percent(value) { return value === null || value === undefined ? 0 : Math.round(value) }

  PanelSeparator { foreground: tab.bar.foreground }

  // ---- header -------------------------------------------------------------
  Item {
    width: parent.width
    implicitHeight: Math.max(lightingHeader.implicitHeight, scanButton.height)

    PanelSectionHeader {
      id: lightingHeader
      text: tab.t("DEVICES")
      foreground: tab.bar.foreground
      fontFamily: tab.bar.fontFamily
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
    }

    PanelActionButton {
      id: scanButton
      iconText: tab.panel.scanning ? "󰑓" : "󰍉"
      tooltipText: tab.panel.scanning ? tab.t("Scanning…") : tab.t("Scan for devices (S)")
      foreground: tab.bar.foreground
      fontFamily: tab.bar.fontFamily
      enabled: !tab.panel.scanning
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onClicked: tab.panel.scan()
    }
  }

  Text {
    visible: tab.panel.lightingDevices.length === 0
    textFormat: Text.PlainText
    text: tab.t("No lighting devices found. If you have RGB hardware, install its engine in the Engines tab.")
    color: tab.dim
    font.family: tab.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
    width: parent.width
  }

  // ---- device cards -------------------------------------------------------
  Repeater {
    model: tab.panel.lightingDevices

    CursorSurface {
      id: card
      required property var modelData
      required property int index
      readonly property bool selected: modelData.id === tab.panel.selectedDevice
      width: tab.width
      height: cardColumn.implicitHeight + Style.space(16)
      foreground: tab.bar.foreground
      bordered: true
      current: selected
      hasCursor: tab.panel.cursorActive && tab.panel.focusSection === "devices" && tab.panel.selectedIndex === index

      // Selecting is the whole card; the enable button sits on top of it.
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: tab.panel.selectDevice(card.modelData.id)
      }

      Row {
        id: cardColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(10)

        Rectangle {
          id: dot
          width: Style.space(12)
          height: width
          radius: width / 2
          anchors.verticalCenter: parent.verticalCenter
          color: card.selected && tab.lighting && tab.lighting.color ? tab.lighting.color : "transparent"
          border.width: 1
          border.color: tab.dim
        }

        Column {
          width: parent.width - dot.width - enableButton.width - parent.spacing * 2
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)

          Text {
            textFormat: Text.PlainText
            text: tab.panel.deviceName(card.modelData)
            color: tab.bar.foreground
            font.family: tab.bar.fontFamily
            font.pixelSize: Style.font.body
            font.bold: card.selected
            elide: Text.ElideRight
            width: parent.width
          }

          Text {
            textFormat: Text.PlainText
            text: card.modelData.enabled !== true ? tab.t("Not enabled")
              : (card.modelData.writable ? tab.panel.supportLabel(card.modelData)
                 : String(card.modelData.blocked_reason || tab.t("Starting…")))
            color: tab.dim
            font.family: tab.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            width: parent.width
          }
        }

        Button {
          id: enableButton
          visible: String(card.modelData.usb || "") !== ""
          width: visible ? implicitWidth : 0
          anchors.verticalCenter: parent.verticalCenter
          text: card.modelData.enabled === true ? tab.t("Disable") : tab.t("Enable")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          bordered: true
          onClicked: {
            if (card.modelData.enabled === true) tab.panel.setEnabled(card.modelData.usb, false)
            else tab.panel.pendingEnable = card.modelData
          }
        }
      }
    }
  }

  // ---- editor for the selected device -------------------------------------
  Column {
    visible: tab.editable
    width: parent.width
    spacing: Style.space(14)

    PanelSeparator { foreground: tab.bar.foreground }

    // Effect
    Column {
      width: parent.width
      spacing: Style.space(6)

      PanelSectionHeader {
        text: tab.t("EFFECT")
        foreground: tab.bar.foreground
        fontFamily: tab.bar.fontFamily
      }

      Dropdown {
        width: parent.width
        showLabel: false
        foreground: tab.bar.foreground
        fontFamily: tab.bar.fontFamily
        options: tab.panel.currentModes.map(function(m) { return { value: m.name, label: m.name } })
        value: tab.lighting ? String(tab.lighting.mode || "") : ""
        onChanged: function(v) { tab.panel.setLighting({ mode: v }) }
      }
    }

    // Colour
    Column {
      visible: tab.mode !== null && tab.mode.color === "single"
      width: parent.width
      spacing: Style.space(8)

      Item {
        width: parent.width
        implicitHeight: Math.max(colorHeader.implicitHeight, randomSwitch.implicitHeight)

        PanelSectionHeader {
          id: colorHeader
          text: tab.t("COLOUR")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
        }

        Row {
          visible: tab.mode !== null && tab.mode.random === true
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(8)

          Text {
            textFormat: Text.PlainText
            text: tab.t("Random")
            color: tab.dim
            font.family: tab.bar.fontFamily
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }

          ToggleSwitch {
            id: randomSwitch
            checked: tab.lighting !== null && tab.lighting.random === true
            foreground: tab.bar.foreground
            onToggled: tab.panel.setLighting({ random: !checked })
          }
        }
      }

      ColorPicker {
        visible: !(tab.lighting !== null && tab.lighting.random === true)
        width: parent.width
        foreground: tab.bar.foreground
        fontFamily: tab.bar.fontFamily
        swatches: tab.panel.swatches
        value: tab.lighting ? String(tab.lighting.color || "#ffffff") : "#ffffff"
        onPicked: function(color) { tab.panel.setLighting({ color: color }) }
      }
    }

    // Speed
    Column {
      visible: tab.mode !== null && tab.mode.speed === true
      width: parent.width
      spacing: Style.space(6)

      Item {
        width: parent.width
        implicitHeight: speedHeader.implicitHeight

        PanelSectionHeader {
          id: speedHeader
          text: tab.t("SPEED")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          anchors.left: parent.left
        }

        Text {
          textFormat: Text.PlainText
          text: tab.percent(speedSlider.dragging ? speedSlider.liveValue : (tab.lighting ? tab.lighting.speed : 0)) + "%"
          color: tab.dim
          font.family: tab.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
        }
      }

      PanelSlider {
        id: speedSlider
        bar: tab.bar
        width: parent.width
        minimum: 0
        maximum: 100
        step: 1
        integer: true
        value: tab.lighting && tab.lighting.speed !== null ? tab.lighting.speed : 0
        onMoved: function(v) { tab.panel.setLighting({ speed: Math.round(v) }) }
      }
    }

    // Brightness
    Column {
      visible: tab.mode !== null && tab.mode.brightness === true
      width: parent.width
      spacing: Style.space(6)

      Item {
        width: parent.width
        implicitHeight: brightnessHeader.implicitHeight

        PanelSectionHeader {
          id: brightnessHeader
          text: tab.t("BRIGHTNESS")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          anchors.left: parent.left
        }

        Text {
          textFormat: Text.PlainText
          text: tab.percent(brightnessSlider.dragging ? brightnessSlider.liveValue : (tab.lighting ? tab.lighting.brightness : 0)) + "%"
                + (tab.lighting && tab.lighting.brightness_emulated ? " · " + tab.t("emulated") : "")
          color: tab.dim
          font.family: tab.bar.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
        }
      }

      PanelSlider {
        id: brightnessSlider
        bar: tab.bar
        width: parent.width
        minimum: 0
        maximum: 100
        step: 1
        integer: true
        value: tab.lighting ? tab.lighting.brightness : 0
        onMoved: function(v) { tab.panel.setLighting({ brightness: Math.round(v) }) }
      }
    }

    PanelSeparator { foreground: tab.bar.foreground }

    // Save to device
    Item {
      width: parent.width
      implicitHeight: Math.max(saveText.implicitHeight, saveButton.implicitHeight)

      Text {
        id: saveText
        anchors.left: parent.left
        anchors.right: saveButton.left
        anchors.rightMargin: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.lighting && tab.lighting.saved
          ? tab.t("Saved to the device: it stays after reboots, OpenRGB can stop.")
          : tab.t("Not saved: OpenRGB keeps running so the lights stay as they are.")
        color: tab.lighting && tab.lighting.saved ? tab.dim : tab.bar.foreground
        font.family: tab.bar.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap
      }

      Button {
        id: saveButton
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        enabled: tab.mode !== null && tab.mode.savable === true && tab.lighting !== null
                 && tab.lighting.saved !== true && !tab.panel.savingLighting
        text: tab.panel.savingLighting ? tab.t("Saving…") : tab.t("Save to device")
        foreground: tab.bar.foreground
        fontFamily: tab.bar.fontFamily
        bordered: true
        onClicked: tab.panel.saveLighting()
      }
    }
  }

  Text {
    visible: tab.panel.lightingError !== ""
    textFormat: Text.PlainText
    text: tab.panel.lightingError
    color: Commons.Color.urgent
    font.family: tab.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
    width: parent.width
  }
}
