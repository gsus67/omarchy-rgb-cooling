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
  implicitHeight: button.implicitHeight

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
  // Fans seen spinning since the panel loaded; one that stops again stays
  // visible (and urgent) instead of hiding with the unused headers.
  property var spunFans: ({})
  // The CPU shows its hottest core; clicking that row lists every core.
  property bool coresExpanded: false
  function isCore(s) { return /CPU$/.test(String(s.device || "")) && /^Core \d+$/.test(String(s.label || "")) }
  readonly property var sensorGroups: {
    var groups = [], index = {}, hottest = {}
    for (var i = 0; i < sensors.length; i++) {
      var s = sensors[i]
      var key = String(s.device || "")
      if (index[key] === undefined) { index[key] = groups.length; groups.push({ device: key, sensors: [] }) }
      if (isCore(s)) {
        // Per-core rows are summarised as the hottest core, listed after it when expanded.
        if (s.value !== null && (hottest[key] === undefined || s.value > hottest[key].value)) hottest[key] = s
        if (!coresExpanded) continue
      }
      if (s.kind === "fan" && key === "Motherboard" && !(s.value > 0) && !spunFans[s.id]) continue
      groups[index[key]].sensors.push(s)
    }
    for (var device in hottest) {
      var h = hottest[device]
      var list = groups[index[device]].sensors
      var first = 0
      while (first < list.length && !isCore(list[first])) first++
      list.splice(first, 0, { id: h.id + ":max", label: t("Hottest core") + (coresExpanded ? " ▾" : " ▸"),
                              device: device, kind: "temp", value: h.value, unit: "C",
                              stale: h.stale, summary: true })
    }
    return groups
  }
  function stoppedFan(s) { return s.kind === "fan" && !(s.value > 0) && spunFans[s.id] === true }
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
      else if (message.event === "profile") applyProfile(data)
      return
    }
    var callback = pending[message.id]
    if (callback === undefined) return
    var p = pending; delete p[message.id]; pending = p
    callback(message.ok === true, message.ok === true ? (message.result || ({})) : (message.error || ({})))
  }

  function applySensors(data) {
    sensors = Array.isArray(data.sensors) ? data.sensors : []
    var spun = spunFans, changed = false
    for (var i = 0; i < sensors.length; i++) {
      if (sensors[i].kind === "fan" && sensors[i].value > 0 && !spun[sensors[i].id]) { spun[sensors[i].id] = true; changed = true }
    }
    if (changed) spunFans = spun
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
    // The bar only needs the headline temperature; refresh faster while open,
    // and follow device hotplug only while the panel shows the device list.
    send("subscribe", { topics: opened ? ["sensors", "devices", "profile"] : ["sensors"], interval_ms: opened ? 2000 : 5000 })
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
      subscribe()
      if (opened) { scan(); refreshProfile() }
    })
  }

  // Engines are only contacted on request (docs/API.md, "Engine scans"):
  // once each time the panel opens and from the Scan button.
  property bool scanning: false
  function scan() {
    if (scanning) return
    scanning = true
    var sent = send("devices.rescan", {}, function(ok, r) {
      root.scanning = false
      if (ok) root.applyDevices(r)
      else root.send("devices", {}, function(ok2, r2) { if (ok2) root.applyDevices(r2) })
    })
    if (!sent) scanning = false
  }

  function onDisconnected() {
    coreReady = false
    scanning = false
    pending = ({})
    reconnectTimer.interval = reconnectDelay
    reconnectDelay = Math.min(reconnectDelay * 2, 30000)
    reconnectTimer.restart()
  }

  onOpenedChanged: {
    if (!coreReady) return
    subscribe()
    if (opened) { scan(); refreshProfile() }
  }

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

  // ---- user sensor names ---------------------------------------------------
  // Stored by the panel only (docs/API.md, "User fan names"); rgbcd stays read-only.

  readonly property string labelsPath: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy-rgb-cooling/labels.json"
  readonly property int maxLabel: 32
  property var userLabels: ({})
  property string renamingId: ""

  function displayLabel(s) {
    var custom = userLabels[s.id]
    return typeof custom === "string" && custom !== "" ? custom : String(s.label || s.id)
  }

  function cleanLabel(text) {
    // Plain text only: drop control characters and keep it short.
    return String(text).replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, maxLabel)
  }

  function loadLabels(text) {
    var parsed = null
    try { parsed = JSON.parse(text) } catch (e) {}
    var labels = {}
    if (parsed && parsed.v === 1 && parsed.labels && typeof parsed.labels === "object") {
      for (var id in parsed.labels) {
        var name = cleanLabel(parsed.labels[id])
        if (typeof parsed.labels[id] === "string" && name !== "") labels[id] = name
      }
    }
    userLabels = labels
  }

  function renameSensor(id, text) {
    var labels = {}
    for (var key in userLabels) labels[key] = userLabels[key]
    var name = cleanLabel(text)
    if (name === "") delete labels[id]
    else labels[id] = name
    userLabels = labels
    renamingId = ""
    labelsFile.setText(JSON.stringify({ v: 1, labels: labels }, null, 2) + "\n")
  }

  FileView {
    id: labelsFile
    path: root.labelsPath
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadLabels(text())
    onLoadFailed: root.userLabels = ({})
  }

  // ---- modes (power profiles) --------------------------------------------
  // The modes change how much heat the CPU makes; the BIOS fan curves react.

  property string profile: ""
  property var profilesAvailable: []
  property string profileError: ""
  readonly property var modes: {
    var all = [
      { value: "power-saver", label: t("Silent") },
      { value: "balanced", label: t("Balanced") },
      { value: "performance", label: t("Turbo") }
    ]
    return all.filter(function(m) { return profilesAvailable.indexOf(m.value) >= 0 })
  }

  function applyProfile(data) {
    profile = typeof data.profile === "string" ? data.profile : ""
    profilesAvailable = Array.isArray(data.available) ? data.available : []
  }

  function refreshProfile() {
    send("profile.get", {}, function(ok, r) {
      if (ok) { root.applyProfile(r); root.profileError = "" }
      else { root.profilesAvailable = []; root.profileError = String(r.message || "") }
    })
  }

  function setProfile(value) {
    if (value === profile || profilesAvailable.indexOf(value) < 0) return
    profile = value
    send("profile.set", { profile: value }, function(ok, r) {
      if (ok) { root.applyProfile(r); root.profileError = "" }
      else { root.profileError = String(r.message || ""); root.refreshProfile() }
    })
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
    if (modes.length > 0) list.push("modes")
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
    if (focusSection === "modes") selectedIndex = Math.max(0, Math.min(modes.length - 1, selectedIndex + dx))
    else if (focusSection === "colors") selectedIndex = Math.max(0, Math.min(swatches.length - 1, selectedIndex + dx))
    else if (focusSection === "brightness" && lighting !== null) setLighting("", Math.max(0, Math.min(100, lighting.brightness + dx * 5)))
  }
  function activateCursor() {
    if (focusSection === "modes" && selectedIndex >= 0 && selectedIndex < modes.length) setProfile(modes[selectedIndex].value)
    else if (focusSection === "devices" && selectedIndex >= 0 && selectedIndex < lightingDevices.length) selectDevice(lightingDevices[selectedIndex].id)
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
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(820))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // Typed keys go to the rename field while it is open.
      blocked: root.renamingId !== ""
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.moveCursorH(dx)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTextKey: function(key) {
        if (key === "s") root.scan()
        else if (key === "c") root.coresExpanded = !root.coresExpanded
      }
      onTabRequested: function(direction) { root.switchPanel(direction) }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        // Always visible when there is more to see, in its own gutter at the
        // right edge so it never covers the values.
        readonly property bool overflowing: panelColumn.implicitHeight > height
        ScrollBar.vertical: ScrollBar {
          parent: scrollArea
          anchors.top: scrollArea.top
          anchors.right: scrollArea.right
          anchors.bottom: scrollArea.bottom
          policy: scrollArea.overflowing ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
        }

        Column {
          id: panelColumn
          width: scrollArea.availableWidth - (scrollArea.overflowing ? scrollArea.ScrollBar.vertical.width + Style.space(8) : 0)
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

          // Modes
          Column {
            visible: root.coreReady && root.modes.length > 0
            width: parent.width
            spacing: Style.space(8)

            PanelSeparator { foreground: root.bar.foreground }

            PanelSectionHeader {
              text: root.t("MODE")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            ButtonGroup {
              width: parent.width
              options: root.modes
              value: root.profile
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              cursorIndex: root.cursorActive && root.focusSection === "modes" ? root.selectedIndex : -1
              onChanged: function(v) { root.setProfile(v) }
              onHovered: function(index, isHovered) {
                if (isHovered) { root.cursorActive = true; root.focusSection = "modes"; root.selectedIndex = index }
              }
            }

            Text {
              textFormat: Text.PlainText
              text: root.profileError !== "" ? root.profileError : root.t("Fans follow your BIOS curves.")
              color: root.profileError !== "" ? Commons.Color.urgent : Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
              width: parent.width
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

                  readonly property bool renaming: root.renamingId === modelData.id

                  MouseArea {
                    anchors.fill: parent
                    enabled: !parent.renaming
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: modelData.summary === true ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: function(mouse) {
                      if (mouse.button === Qt.RightButton && modelData.summary !== true) root.renamingId = modelData.id
                      else if (modelData.summary === true) root.coresExpanded = !root.coresExpanded
                    }
                  }

                  TextField {
                    visible: parent.renaming
                    anchors.left: parent.left
                    anchors.right: sensorValue.left
                    anchors.rightMargin: Style.space(10)
                    anchors.verticalCenter: parent.verticalCenter
                    foreground: root.bar.foreground
                    maximumLength: root.maxLabel
                    placeholderText: String(modelData.label || modelData.id)
                    onVisibleChanged: if (visible) { text = root.displayLabel(modelData); forceActiveFocus(); selectAll() }
                    onAccepted: root.renameSensor(modelData.id, text)
                    Keys.onEscapePressed: root.renamingId = ""
                  }

                  Text {
                    id: sensorLabel
                    visible: !parent.renaming
                    textFormat: Text.PlainText
                    text: root.displayLabel(modelData)
                    color: root.bar.foreground
                    opacity: modelData.stale ? 0.5 : 1
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                    anchors.left: parent.left
                    anchors.leftMargin: root.isCore(modelData) ? Style.space(18) : Style.space(6)
                    anchors.right: sensorValue.left
                    anchors.rightMargin: Style.space(10)
                  }

                  Text {
                    id: sensorValue
                    textFormat: Text.PlainText
                    text: root.formatValue(modelData)
                    color: (modelData.kind === "temp" && modelData.value !== null && modelData.value >= root.hotCelsius) || root.stoppedFan(modelData) ? Commons.Color.urgent : Qt.darker(root.bar.foreground, 1.2)
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

          Text {
            visible: root.sensorGroups.length > 0
            textFormat: Text.PlainText
            text: root.t("Right-click a sensor to rename it.")
            color: Qt.darker(root.bar.foreground, 1.6)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            width: parent.width
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

            Item {
              width: parent.width
              implicitHeight: Math.max(lightingHeader.implicitHeight, scanButton.height)

              PanelSectionHeader {
                id: lightingHeader
                text: root.t("LIGHTING")
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              PanelActionButton {
                id: scanButton
                iconText: root.scanning ? "󰑓" : "󰍉"
                tooltipText: root.scanning ? root.t("Scanning…") : root.t("Scan for devices (S)")
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                enabled: !root.scanning
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.scan()
              }
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
