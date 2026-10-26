import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Omarchy RGB & Cooling: bar temperature + popup with sensors and lighting.
//
// This file never touches hardware. It prepares the core with bootstrap.py,
// then talks to rgbcd over its user socket using the contract in docs/API.md
// (one JSON object per line). Everything shown comes from rgbcd and is
// rendered as plain text.
Panel {
  id: root
  moduleName: "io.github.gsus67.omarchy-rgb-cooling"
  ipcTarget: "omarchy-rgb-cooling"
  implicitWidth: button.implicitWidth

  readonly property string pluginDirectory: decodeURIComponent(String(Qt.resolvedUrl("bootstrap.py")).replace(/^file:\/\//, "")).replace(/\/bootstrap\.py$/, "")
  readonly property string socketPath: (Quickshell.env("XDG_RUNTIME_DIR") || "") + "/omarchy-rgb-cooling.sock"
  // Longest line accepted from rgbcd, same limit the core applies to us.
  readonly property int maxLine: 65536
  readonly property real hotCelsius: 85

  property bool coreReady: false
  property string coreError: ""
  property bool demo: false
  property var sensors: []
  property string primaryId: ""
  property var devices: []
  property string selectedDevice: ""
  property var lighting: null
  property string lightingError: ""
  property int nextId: 1
  property var pending: ({})
  property int reconnectDelay: 1000

  // Keyboard cursor: "devices" (vertical list), "colors" (horizontal row) or
  // "brightness" (slider, -1 sentinel). Pointer hover moves the same cursor.
  property string focusSection: "devices"
  property int selectedIndex: 0
  property bool cursorActive: false

  property var translations: ({})
  readonly property string language: (Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || Qt.locale().name).toLowerCase().split(/[_.-]/)[0] === "es" ? "es" : "en"
  function t(source) {
    var catalog = translations[language] || ({})
    return catalog[source] || source
  }
  FileView {
    path: root.pluginDirectory + "/i18n/messages.json"
    onLoaded: { try { root.translations = JSON.parse(text()) } catch (e) { root.translations = ({}) } }
  }

  // ---- data helpers -------------------------------------------------------

  readonly property var primarySensor: {
    for (var i = 0; i < sensors.length; i++)
      if (sensors[i].id === primaryId) return sensors[i]
    return null
  }
  readonly property bool hot: primarySensor !== null && primarySensor.value !== null && primarySensor.value >= hotCelsius
  readonly property var sensorGroups: {
    var groups = [], index = {}
    for (var i = 0; i < sensors.length; i++) {
      var s = sensors[i]
      var key = String(s.device || "")
      if (index[key] === undefined) { index[key] = groups.length; groups.push({ device: key, sensors: [] }) }
      groups[index[key]].sensors.push(s)
    }
    return groups
  }
  readonly property var lightingDevices: {
    var list = []
    for (var i = 0; i < devices.length; i++) {
      var d = devices[i]
      if (!d.excluded && d.capabilities && d.capabilities.indexOf("lighting.read") >= 0) list.push(d)
    }
    return list
  }
  readonly property var currentDevice: {
    for (var i = 0; i < lightingDevices.length; i++)
      if (lightingDevices[i].id === selectedDevice) return lightingDevices[i]
    return null
  }
  readonly property bool canWrite: currentDevice !== null && currentDevice.writable === true
      && currentDevice.capabilities.indexOf("lighting.write") >= 0
  readonly property bool hasBrightness: canWrite && currentDevice.capabilities.indexOf("brightness") >= 0

  function hex(c) {
    function part(v) { var s = Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16); return s.length < 2 ? "0" + s : s }
    return "#" + part(c.r) + part(c.g) + part(c.b)
  }
  readonly property var swatches: [
    { label: t("Theme"), color: hex(Commons.Color.accent) },
    { label: t("White"), color: "#ffffff" },
    { label: t("Red"), color: "#ff0000" },
    { label: t("Orange"), color: "#ff6000" },
    { label: t("Yellow"), color: "#ffd000" },
    { label: t("Green"), color: "#00ff40" },
    { label: t("Cyan"), color: "#00e0ff" },
    { label: t("Blue"), color: "#0040ff" },
    { label: t("Purple"), color: "#8000ff" },
    { label: t("Off"), color: "#000000" }
  ]

  function formatValue(s) {
    if (s.value === null || s.value === undefined) return "—"
    if (s.kind === "fan") return Math.round(s.value) + " RPM"
    return Math.round(s.value) + "°"
  }
  function supportLabel(d) {
    var labels = {
      "recognized": t("Recognized"),
      "upstream-supported": t("Supported upstream"),
      "simulation-tested": t("Tested in simulation"),
      "physically-tested": t("Tested on hardware")
    }
    return labels[d.support] || ""
  }
  readonly property string heroStatus: {
    if (coreError !== "") return t("CORE UNAVAILABLE")
    if (!coreReady) return t("CONNECTING…")
    if (demo) return t("DEMO · SIMULATED HARDWARE")
    if (primarySensor && primarySensor.value !== null) return (hot ? t("HOT") : t("NORMAL")) + " · " + formatValue(primarySensor)
    return t("NO SENSORS")
  }

  // ---- connection ---------------------------------------------------------

  function send(op, params, callback) {
    if (!socket.connected) return false
    var id = nextId
    nextId = nextId >= 1000000000 ? 1 : nextId + 1
    if (callback) { var p = pending; p[id] = callback; pending = p }
    socket.write(JSON.stringify({ v: 1, id: id, op: op, params: params || ({}) }) + "\n")
    socket.flush()
    return true
  }

  function handleLine(line) {
    if (line.length > maxLine) { socket.connected = false; return }
    var message
    try { message = JSON.parse(line) } catch (e) { return }
    if (!message || typeof message !== "object" || message.v !== 1) return
    if (typeof message.event === "string") {
      var data = message.data || ({})
      if (message.event === "sensors") applySensors(data)
      else if (message.event === "devices") applyDevices(data)
      return
    }
    var callback = pending[message.id]
    if (callback === undefined) return
    var p = pending; delete p[message.id]; pending = p
    callback(message.ok === true, message.ok === true ? (message.result || ({})) : (message.error || ({})))
  }

  function applySensors(data) {
    sensors = Array.isArray(data.sensors) ? data.sensors : []
    primaryId = typeof data.primary === "string" ? data.primary : ""
  }

  function applyDevices(data) {
    devices = Array.isArray(data.devices) ? data.devices : []
    if (currentDevice === null) {
      selectedDevice = lightingDevices.length > 0 ? lightingDevices[0].id : ""
      refreshLighting()
    }
  }

  function subscribe() {
    // The bar only needs the headline temperature; refresh faster while open.
    send("subscribe", { topics: ["sensors", "devices"], interval_ms: opened ? 2000 : 5000 })
  }

  function onConnected() {
    reconnectDelay = 1000
    coreError = ""
    pending = ({})
    send("hello", {}, function(ok, result) {
      if (!ok || result.api !== 1) { coreError = t("Incompatible core version"); socket.connected = false; return }
      demo = result.demo === true
      coreReady = true
      send("sensors", {}, function(ok, r) { if (ok) applySensors(r) })
      send("devices", {}, function(ok, r) { if (ok) applyDevices(r) })
      subscribe()
    })
  }

  function onDisconnected() {
    coreReady = false
    pending = ({})
    reconnectTimer.interval = reconnectDelay
    reconnectDelay = Math.min(reconnectDelay * 2, 30000)
    reconnectTimer.restart()
  }

  onOpenedChanged: if (coreReady) subscribe()

  Process {
    id: bootstrapProc
    command: ["python3", root.pluginDirectory + "/bootstrap.py", root.pluginDirectory]
    stdout: StdioCollector { id: bootstrapOut; waitForEnd: true }
    onExited: function(code) {
      var result = null
      try { result = JSON.parse(String(bootstrapOut.text).trim().split("\n").pop()) } catch (e) {}
      if (code === 0 && result && result.ok === true) { root.coreError = ""; socket.connected = true }
      else root.coreError = result && typeof result.error === "string" ? result.error : root.t("Could not prepare the core")
    }
  }

  Component.onCompleted: bootstrapProc.running = true

  Socket {
    id: socket
    path: root.socketPath
    parser: SplitParser { onRead: function(data) { root.handleLine(data) } }
    onConnectionStateChanged: connected ? root.onConnected() : root.onDisconnected()
  }

  Timer {
    id: reconnectTimer
    repeat: false
    onTriggered: if (!socket.connected && root.coreError === "") socket.connected = true
  }

  // ---- lighting -----------------------------------------------------------

  property string pendingColor: ""
  property int pendingBrightness: -1

  function refreshLighting() {
    lighting = null
    lightingError = ""
    if (selectedDevice === "") return
    var device = selectedDevice
    send("lighting.get", { device: device }, function(ok, r) {
      if (device !== root.selectedDevice) return
      if (ok) root.lighting = r
      else root.lightingError = String(r.message || "")
    })
  }

  function selectDevice(id) {
    if (id === selectedDevice) return
    selectedDevice = id
    refreshLighting()
  }

  function setLighting(color, brightness) {
    if (!canWrite || lighting === null) return
    pendingColor = color !== "" ? color : lighting.color
    pendingBrightness = brightness >= 0 ? brightness : lighting.brightness
    lightingDebounce.restart()
  }

  Timer {
    id: lightingDebounce
    interval: 150
    repeat: false
    onTriggered: {
      var device = root.selectedDevice
      root.send("lighting.set", { device: device, color: root.pendingColor, brightness: root.pendingBrightness }, function(ok, r) {
        if (device !== root.selectedDevice) return
        if (ok) { root.lighting = r; root.lightingError = "" }
        else root.lightingError = String(r.message || "")
      })
    }
  }

  // ---- keyboard -----------------------------------------------------------

  readonly property var visibleSections: {
    var list = []
    if (lightingDevices.length > 0) list.push("devices")
    if (canWrite) list.push("colors")
    if (hasBrightness) list.push("brightness")
    return list
  }
  function sectionCount(section) {
    if (section === "devices") return lightingDevices.length
    if (section === "colors") return swatches.length
    return 0
  }
  function moveCursor(dy) {
    var sections = visibleSections
    if (sections.length === 0) return
    var s = sections.indexOf(focusSection)
    if (s < 0) { focusSection = sections[0]; selectedIndex = 0; return }
    if (focusSection === "devices") {
      var next = selectedIndex + dy
      if (next >= 0 && next < lightingDevices.length) { selectedIndex = next; return }
    }
    var target = s + dy
    if (target < 0 || target >= sections.length) return
    focusSection = sections[target]
    selectedIndex = focusSection === "brightness" ? -1 : (dy < 0 && focusSection === "devices" ? lightingDevices.length - 1 : 0)
  }
  function moveCursorH(dx) {
    if (focusSection === "colors") selectedIndex = Math.max(0, Math.min(swatches.length - 1, selectedIndex + dx))
    else if (focusSection === "brightness" && lighting !== null) setLighting("", Math.max(0, Math.min(100, lighting.brightness + dx * 5)))
  }
  function activateCursor() {
    if (focusSection === "devices" && selectedIndex >= 0 && selectedIndex < lightingDevices.length) selectDevice(lightingDevices[selectedIndex].id)
    else if (focusSection === "colors" && selectedIndex >= 0 && selectedIndex < swatches.length) setLighting(swatches[selectedIndex].color, -1)
  }

  // ---- bar ----------------------------------------------------------------

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.primarySensor && root.primarySensor.value !== null ? "󰔏 " + root.formatValue(root.primarySensor) : "󰔏"
    active: root.hot
    tooltipText: root.primarySensor ? root.primarySensor.label + " · " + root.formatValue(root.primarySensor) : root.t("RGB & Cooling")
    onPressed: function(b) { root.toggle() }
  }

  // ---- panel --------------------------------------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(600))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.moveCursorH(dx)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: panelColumn.implicitHeight > height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(14)

          // Hero
          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: "󰔏"
              color: root.hot ? Commons.Color.urgent : root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: root.t("RGB & Cooling")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                textFormat: Text.PlainText
                text: root.heroStatus
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
                width: parent.width
              }
            }
          }

          Text {
            visible: root.coreError !== ""
            textFormat: Text.PlainText
            text: root.coreError
            color: Commons.Color.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            width: parent.width
          }

          // Sensors, grouped by device
          Repeater {
            model: root.sensorGroups

            Column {
              required property var modelData
              width: panelColumn.width
              spacing: Style.space(6)

              PanelSeparator { foreground: root.bar.foreground }

              PanelSectionHeader {
                text: String(modelData.device || root.t("Sensors")).toUpperCase()
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
              }

              Repeater {
                model: modelData.sensors

                Item {
                  required property var modelData
                  width: panelColumn.width
                  implicitHeight: sensorLabel.implicitHeight

                  Text {
                    id: sensorLabel
                    textFormat: Text.PlainText
                    text: String(modelData.label || modelData.id)
                    color: root.bar.foreground
                    opacity: modelData.stale ? 0.5 : 1
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                    anchors.left: parent.left
                    anchors.leftMargin: Style.space(6)
                    anchors.right: sensorValue.left
                    anchors.rightMargin: Style.space(10)
                  }

                  Text {
                    id: sensorValue
                    textFormat: Text.PlainText
                    text: root.formatValue(modelData)
                    color: modelData.kind === "temp" && modelData.value !== null && modelData.value >= root.hotCelsius ? Commons.Color.urgent : Qt.darker(root.bar.foreground, 1.2)
                    opacity: modelData.stale ? 0.5 : 1
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(6)
                  }
                }
              }
            }
          }

          // Lighting
          PanelSeparator {
            visible: root.coreReady
            foreground: root.bar.foreground
          }

          Column {
            visible: root.coreReady
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader {
              text: root.t("LIGHTING")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Text {
              visible: root.lightingDevices.length === 0
              textFormat: Text.PlainText
              text: root.t("No lighting devices available.")
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
              width: parent.width
            }

            Repeater {
              model: root.lightingDevices

              CursorSurface {
                id: deviceRow
                required property var modelData
                required property int index
                width: panelColumn.width
                height: deviceColumn.implicitHeight + Style.spacing.controlGap
                foreground: root.bar.foreground
                hasCursor: root.cursorActive && root.focusSection === "devices" && root.selectedIndex === index
                current: modelData.id === root.selectedDevice

                Column {
                  id: deviceColumn
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(2)

                  Text {
                    textFormat: Text.PlainText
                    text: String(deviceRow.modelData.name || deviceRow.modelData.id)
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: deviceRow.modelData.id === root.selectedDevice
                    elide: Text.ElideRight
                    width: parent.width
                  }

                  Text {
                    textFormat: Text.PlainText
                    text: root.supportLabel(deviceRow.modelData) + (deviceRow.modelData.writable ? "" : " · " + root.t("read only"))
                    color: Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                    width: parent.width
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onEntered: { root.cursorActive = true; root.focusSection = "devices"; root.selectedIndex = deviceRow.index }
                  onClicked: root.selectDevice(deviceRow.modelData.id)
                }
              }
            }

            // Why writes are off for this device
            Text {
              visible: root.currentDevice !== null && !root.canWrite
              textFormat: Text.PlainText
              text: root.currentDevice ? String(root.currentDevice.blocked_reason || root.t("This device is read only.")) : ""
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
              width: parent.width
            }

            Text {
              visible: root.lightingError !== ""
              textFormat: Text.PlainText
              text: root.lightingError
              color: Commons.Color.urgent
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
              width: parent.width
            }

            Grid {
              id: swatchGrid
              visible: root.canWrite && root.lighting !== null
              width: parent.width
              columns: 5
              spacing: Style.spacing.xs
              readonly property real cell: (width - spacing * (columns - 1)) / columns

              Repeater {
                model: root.swatches

                CursorSurface {
                  id: swatch
                  required property var modelData
                  required property int index
                  width: swatchGrid.cell
                  height: Style.spacing.controlHeight
                  foreground: root.bar.foreground
                  hasCursor: root.cursorActive && root.focusSection === "colors" && root.selectedIndex === index
                  current: root.lighting !== null && root.lighting.color === modelData.color

                  Rectangle {
                    anchors.fill: parent
                    anchors.margins: Style.space(5)
                    radius: Style.space(3)
                    color: swatch.modelData.color
                    border.width: 1
                    border.color: Qt.darker(root.bar.foreground, 2)
                  }

                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onEntered: { root.cursorActive = true; root.focusSection = "colors"; root.selectedIndex = swatch.index }
                    onClicked: root.setLighting(swatch.modelData.color, -1)
                  }
                }
              }
            }

            Item {
              visible: root.hasBrightness && root.lighting !== null
              width: parent.width
              implicitHeight: brightnessHeader.implicitHeight

              PanelSectionHeader {
                id: brightnessHeader
                text: root.t("BRIGHTNESS")
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                anchors.left: parent.left
              }

              Text {
                textFormat: Text.PlainText
                text: root.lighting ? Math.round(brightnessSlider.dragging ? brightnessSlider.liveValue : root.lighting.brightness) + "%" + (root.lighting.brightness_emulated ? " · " + root.t("emulated") : "") : ""
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                anchors.right: parent.right
                anchors.rightMargin: Style.space(6)
                anchors.verticalCenter: parent.verticalCenter
              }
            }

            CursorSurface {
              visible: root.hasBrightness && root.lighting !== null
              width: parent.width
              height: brightnessSlider.implicitHeight + Style.spacing.controlGap
              foreground: root.bar.foreground
              outline: true
              hasCursor: root.cursorActive && root.focusSection === "brightness"

              PanelSlider {
                id: brightnessSlider
                bar: root.bar
                anchors.fill: parent
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                minimum: 0
                maximum: 100
                step: 1
                integer: true
                value: root.lighting ? root.lighting.brightness : 0
                onMoved: function(v) { root.setLighting("", Math.round(v)) }
              }

              HoverHandler {
                onHoveredChanged: if (hovered) { root.cursorActive = true; root.focusSection = "brightness"; root.selectedIndex = -1 }
              }
            }
          }
        }
      }
    }
  }
}
