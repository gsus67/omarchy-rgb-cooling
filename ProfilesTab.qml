import QtQuick
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Named RGB + system-power profiles. Cooling remains with BIOS/CoolerControl.
Column {
  id: tab

  required property var panel
  readonly property var bar: panel.bar
  readonly property color dim: Qt.darker(bar.foreground, 1.4)
  spacing: Style.space(12)

  function t(text) { return panel.t(text) }
  function existing(name) {
    for (var i = 0; i < panel.savedProfiles.length; i++)
      if (panel.savedProfiles[i].name === name) return true
    return false
  }

  PanelSeparator { foreground: tab.bar.foreground }

  PanelSectionHeader {
    text: tab.t("PROFILES")
    foreground: tab.bar.foreground
    fontFamily: tab.bar.fontFamily
  }

  Text {
    textFormat: Text.PlainText
    text: tab.t("Save the current RGB settings and system power mode together. Fan curves stay with BIOS or CoolerControl.")
    color: tab.dim
    font.family: tab.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
    width: parent.width
  }

  Row {
    width: parent.width
    spacing: Style.space(8)

    TextField {
      id: profileName
      width: parent.width - saveButton.implicitWidth - parent.spacing
      foreground: tab.bar.foreground
      maximumLength: 48
      placeholderText: tab.t("Profile name")
      onAccepted: tab.panel.saveCurrentProfile(profileName.text)
    }

    Button {
      id: saveButton
      text: tab.t("Save")
      foreground: tab.bar.foreground
      fontFamily: tab.bar.fontFamily
      bordered: true
      enabled: !tab.panel.profilesBusy && profileName.text.length > 0
               && (tab.existing(profileName.text) || tab.panel.savedProfiles.length < 32)
      Accessible.name: text
      onClicked: tab.panel.saveCurrentProfile(profileName.text)
    }
  }

  Item {
    width: parent.width
    implicitHeight: Math.max(themeText.implicitHeight, themeSwitch.implicitHeight)

    Column {
      id: themeText
      anchors.left: parent.left
      anchors.right: themeSwitch.left
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(2)

      Text {
        textFormat: Text.PlainText
        text: tab.t("Follow Omarchy theme colour")
        color: tab.bar.foreground
        font.family: tab.bar.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        width: parent.width
      }

      Text {
        textFormat: Text.PlainText
        text: tab.t("Off by default. Theme events update the selected RGB device; no polling.")
        color: tab.dim
        font.family: tab.bar.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap
        width: parent.width
      }
    }

    ToggleSwitch {
      id: themeSwitch
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      checked: tab.panel.syncTheme
      enabled: !tab.panel.profilesBusy
      Accessible.name: tab.t("Follow Omarchy theme colour")
      onToggled: tab.panel.setThemeSync(!checked)
    }
  }

  Text {
    visible: tab.panel.savedProfiles.length === 0
    textFormat: Text.PlainText
    text: tab.t("No profiles saved yet.")
    color: tab.dim
    font.family: tab.bar.fontFamily
    font.pixelSize: Style.font.caption
    width: parent.width
  }

  Repeater {
    model: tab.panel.savedProfiles

    Item {
      id: row
      required property var modelData
      width: tab.width
      implicitHeight: Math.max(profileText.implicitHeight, actions.implicitHeight)

      Column {
        id: profileText
        anchors.left: parent.left
        anchors.right: actions.left
        anchors.rightMargin: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        Text {
          textFormat: Text.PlainText
          text: String(row.modelData.name || "")
          color: tab.bar.foreground
          font.family: tab.bar.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          elide: Text.ElideRight
          width: parent.width
        }

        Text {
          textFormat: Text.PlainText
          text: String(row.modelData.lighting ? row.modelData.lighting.color || row.modelData.lighting.mode : "")
                + " · " + String(row.modelData.power_profile || "")
          color: tab.dim
          font.family: tab.bar.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
          width: parent.width
        }
      }

      Row {
        id: actions
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)

        Button {
          text: tab.t("Apply")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          bordered: true
          enabled: !tab.panel.profilesBusy
          Accessible.name: text
          onClicked: tab.panel.applySavedProfile(row.modelData)
        }

        PanelActionButton {
          iconText: "󰆴"
          tooltipText: tab.t("Delete profile")
          foreground: tab.bar.foreground
          fontFamily: tab.bar.fontFamily
          enabled: !tab.panel.profilesBusy
          Accessible.name: tooltipText
          onClicked: tab.panel.deleteSavedProfile(String(row.modelData.name || ""))
        }
      }
    }
  }

  Text {
    visible: tab.panel.profilesMessage !== ""
    textFormat: Text.PlainText
    text: tab.panel.profilesMessage
    color: tab.panel.profilesMessage === tab.t("Profile applied.")
           || tab.panel.profilesMessage === tab.t("Profile saved.")
           || tab.panel.profilesMessage === tab.t("Profile deleted.")
           || tab.panel.profilesMessage === tab.t("Applying profile…")
         ? tab.dim : Commons.Color.urgent
    font.family: tab.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.Wrap
    width: parent.width
  }
}
