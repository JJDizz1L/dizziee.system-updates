import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Networking
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "dizziee.system-updates"
  ipcTarget: "dizziee.system-updates"
  property var repos: []
  property int total: 0
  readonly property var installedRepos: {
    var filtered = []
    for (var i = 0; i < repos.length; i++) {
      if (repos[i].installed === true) filtered.push(repos[i])
    }
    return filtered
  }
  property var repoStatus: ({ "pacman": "idle", "aur": "idle", "flatpak": "idle", "omarchy": "idle" })
  property double lastPingAt: 0
  property string lastCheckedText: ""
  property bool settingsMode: false
  property var draftSettings: ({})
  property string settingsStatusText: ""
  property string pendingRepo: ""
  property bool fastPollActive: false
  property int fastPollCount: 0
  readonly property int maxFastPolls: 30
  // Hyprland event-socket tracking of the updater terminal window. When it
  // closes, updates are done and one immediate rescan replaces blind polling.
  property string watchedWindowAddress: ""
  property bool awaitingUpdateWindow: false

  readonly property string barIcon: root.total > 0 ? "󰜈" : "󰏗"
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"
  readonly property bool networkOnline: !Networking.canCheckConnectivity || Networking.connectivity === NetworkConnectivity.Full
  readonly property var repoUrls: ({
    "pacman": "https://archlinux.org/packages/",
    "aur": "https://aur.archlinux.org/",
    "flatpak": "https://flathub.org/",
    "omarchy": "https://omarchy.org/"
  })

  function refresh() {
    if (!scannerProc.running) scannerProc.running = true
  }

  function updateRepos(raw) {
    var parsed = Model.parseRepoList(raw)
    repos = parsed.repos
    total = parsed.total
  }

  function iconSource(id) {
    if (id === "pacman") return Qt.resolvedUrl("assets/arch-logo.svg")
    if (id === "aur") return Qt.resolvedUrl("assets/arch-logo.svg")
    if (id === "flatpak") return Qt.resolvedUrl("assets/flatpak.svg")
    if (id === "omarchy") return Qt.resolvedUrl("assets/omarchy.svg")
    return ""
  }

  function updateRepo(id) {
    var cmd = ""
    for (var i = 0; i < repos.length; i++) {
      if (repos[i].id === id) {
        cmd = repos[i].updateCmd || ""
        break
      }
    }
    if (!cmd) return

    pendingRepo = id
    fastPollCount = 0
    // Primary completion signal: Hyprland closewindow of the updater terminal.
    if (watchedWindowAddress === "" && !awaitingUpdateWindow) {
      awaitingUpdateWindow = true
      watchCaptureTimeout.restart()
    }
    // Fallback while the terminal stays open (or if event capture fails).
    fastPollActive = true
    fastPollTimer.restart()

    var launcher = "omarchy-launch-terminal"
    root.bar.run(launcher + " bash -c " + Util.shellQuote(cmd))
  }

  function stopFastPoll() {
    pendingRepo = ""
    watchedWindowAddress = ""
    awaitingUpdateWindow = false
    fastPollActive = false
    fastPollTimer.stop()
    refresh()
  }

  function setRepoStatus(id, status) {
    var next = {}
    for (var k in root.repoStatus) next[k] = root.repoStatus[k]
    if (next[id] !== undefined) next[id] = status
    root.repoStatus = next
  }

  function buildPingCommand() {
    var script = ""
    for (var i = 0; i < repos.length; i++) {
      var r = repos[i]
      var url = repoUrls[r.id]
      if (r.installed !== true || !url) continue
      script += "(curl -sI --connect-timeout 6 --max-time 9 " + url +
        " >/dev/null 2>&1 && echo '" + r.id + " online' || echo '" + r.id + " offline') & "
    }
    return script + "wait"
  }

  function pingRepos() {
    if (Date.now() - lastPingAt < 600000 && repoStatus.pacman !== "idle") return
    lastPingAt = Date.now()
    updateLastChecked()
    var next = {}
    for (var k in repoStatus) next[k] = repoStatus[k]
    for (var id in repoUrls) next[id] = "checking"
    repoStatus = next

    if (!networkOnline) {
      var off = {}
      for (var k2 in repoStatus) off[k2] = repoStatus[k2] === "checking" ? "offline" : repoStatus[k2]
      repoStatus = off
      return
    }
    pingProc.command = ["bash", "-c", buildPingCommand()]
    if (!pingProc.running) pingProc.running = true
  }

  function updateLastChecked() {
    if (lastPingAt === 0) { lastCheckedText = ""; return }
    var elapsed = Math.floor((Date.now() - lastPingAt) / 1000)
    if (elapsed < 60) lastCheckedText = elapsed + "s ago"
    else if (elapsed < 3600) lastCheckedText = Math.floor(elapsed / 60) + "m ago"
    else lastCheckedText = Math.floor(elapsed / 3600) + "h ago"
  }

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function cloneObject(value, fallback) {
    if (value === undefined || value === null) return fallback
    try { return JSON.parse(JSON.stringify(value)) }
    catch (e) { return fallback }
  }

  function normalizedSettings(source) {
    var next = cloneObject(source, {}) || {}
    var refresh = Number(next.refreshIntervalSec === undefined || next.refreshIntervalSec === null ? 1800 : next.refreshIntervalSec)
    next.refreshIntervalSec = Math.round(root.clamp(isFinite(refresh) ? refresh : 1800, 300, 7200))
    next.alwaysShow = next.alwaysShow !== false
    return next
  }

  function canPersistSettings() {
    return !!(bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
  }

  function openSettings() {
    draftSettings = normalizedSettings(settings)
    settingsStatusText = ""
    settingsMode = true
    open()
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  function showMain() {
    settingsMode = false
    settingsStatusText = ""
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  function saveSettings() {
    var next = normalizedSettings(draftSettings)
    draftSettings = next
    root.settings = next
    if (canPersistSettings()) {
      bar.shell.updateEntryInline(root.moduleName, next)
      settingsStatusText = "Saved to shell.json"
    } else {
      settingsStatusText = "Saved for this session"
    }
  }

  function draftValue(name, fallback) {
    var value = draftSettings ? draftSettings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function setDraftValue(name, value) {
    var next = normalizedSettings(draftSettings)
    next[name] = value
    draftSettings = next
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

  function triggerPress(button) {
    if (button === Qt.RightButton) {
      openSettings()
      return
    }
    if (button === Qt.MiddleButton) {
      refresh()
      return
    }
    if (opened) close()
    else { open(); refresh() }
  }

  onOpenedChanged: {
    if (opened) { refresh(); pingRepos() }
  }

  visible: total > 0 || setting("alwaysShow", true) === true
  implicitWidth: visible ? button.implicitWidth : 0
  implicitHeight: visible ? button.implicitHeight : 0

  Process {
    id: scannerProc
    command: ["python3", pathFromUrl(Qt.resolvedUrl("scripts/check_updates.py"))]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.updateRepos(text)
    }
  }

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0)
      return decodeURIComponent(value.substring(7))
    return value
  }

  Timer {
    interval: Math.max(300, Number(root.setting("refreshIntervalSec", 1800))) * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    id: fastPollTimer
    interval: 10000
    running: false
    repeat: true
    onTriggered: {
      root.refresh()
      root.fastPollCount++
      if (root.fastPollCount >= root.maxFastPolls) root.stopFastPoll()
    }
  }

  Timer {
    id: lastCheckedTimer
    interval: 5000
    running: root.opened
    repeat: true
    onTriggered: root.updateLastChecked()
  }

  Process {
    id: pingProc
    stdout: SplitParser {
      onRead: function(line) {
        var parts = line.trim().split(" ")
        if (parts.length === 2 && (parts[1] === "online" || parts[1] === "offline"))
          root.setRepoStatus(parts[0], parts[1])
      }
    }
  }

  // Watch the Hyprland event socket: capture the address of the first window
  // opened right after an update is launched, then rescan once when it closes.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (event.name === "openwindow") {
        if (root.awaitingUpdateWindow) {
          root.watchedWindowAddress = String(event.data || "").split(",")[0]
          root.awaitingUpdateWindow = false
          watchCaptureTimeout.stop()
        }
      } else if (event.name === "closewindow") {
        if (root.watchedWindowAddress !== "" && String(event.data || "") === root.watchedWindowAddress)
          root.stopFastPoll()
      }
    }
  }

  Timer {
    id: watchCaptureTimeout
    interval: 15000
    onTriggered: root.awaitingUpdateWindow = false
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barIcon
    fixedWidth: root.bar && root.bar.vertical ? -1 : Style.space(27)
    fixedHeight: root.bar && root.bar.vertical ? Style.space(26) : -1
    tooltipText: {
      var parts = []
      for (var i = 0; i < root.installedRepos.length; i++) {
        var r = root.installedRepos[i]
        if (r.count > 0) parts.push(r.count + " " + r.name)
      }
      if (parts.length === 0) return ""
      return parts.join(", ")
    }
    onPressed: function(b) { root.triggerPress(b) }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: settingsMode && settingsContentLayout.editorActive
      onCloseRequested: root.close()
      onTextKey: function(t) {
        if (t === "s" || t === "S") root.settingsMode ? root.saveSettings() : root.openSettings()
        if (t === "r" || t === "R") root.refresh()
      }

      ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(14)

        RowLayout {
          Layout.fillWidth: true
          spacing: 8

          Text {
            text: root.settingsMode ? "System Updates Settings" : "System Updates"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
          }

          Button {
            visible: root.settingsMode
            text: "Updates"
            foreground: root.fg
            tooltipText: "Back to updates"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: root.showMain()
          }

          Button {
            visible: root.settingsMode
            text: "Save"
            foreground: root.fg
            tooltipText: "Save settings"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            active: true
            onClicked: root.saveSettings()
          }

          Button {
            visible: !root.settingsMode
            text: "Refresh"
            foreground: root.fg
            tooltipText: "Refresh updates"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: root.refresh()
          }
        }

        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.fg
        }

        Repeater {
          visible: !root.settingsMode
          model: root.installedRepos

          delegate: BorderSurface {
            required property var modelData
            Layout.fillWidth: true
            color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.055)
            borderSpec: Border.flat(Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.08), 1)
            radius: Style.cornerRadius
            padding: Style.space(10)

            implicitHeight: repoRow.implicitHeight + contentTopInset + contentBottomInset

            RowLayout {
              id: repoRow
              anchors.fill: parent
              spacing: Style.space(6)

              Image {
                source: root.iconSource(modelData.id)
                Layout.preferredWidth: Style.space(20)
                Layout.preferredHeight: Style.space(20)
                sourceSize.width: Style.space(20)
                sourceSize.height: Style.space(20)
                Layout.leftMargin: Style.space(6)
                fillMode: Image.PreserveAspectFit
                Layout.alignment: Qt.AlignVCenter
              }

              ColumnLayout {
                spacing: 1

                Text {
                  text: modelData.name
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }

                Row {
                  spacing: 2

                  Text {
                    text: modelData.count > 0
                      ? modelData.count + (modelData.count === 1 ? " update" : " updates available")
                      : "Up to date"
                    color: modelData.count > 0 ? root.fg : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    visible: modelData.pkgCount > 0
                    text: " · " + modelData.pkgCount + " pkgs"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    visible: root.repoStatus[modelData.id] === "checking"
                    text: " · Checking..."
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.italic: true
                  }

                  Text {
                    visible: root.repoStatus[modelData.id] === "online"
                    text: " · ● Online"
                    color: "#4ade80"
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    visible: root.repoStatus[modelData.id] === "offline"
                    text: " · ✗ Offline"
                    color: "#f87171"
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    visible: root.lastCheckedText !== "" && root.repoStatus[modelData.id] !== "checking" && root.repoStatus[modelData.id] !== "idle"
                    text: " · Checked " + root.lastCheckedText
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }

              Item { Layout.fillWidth: true }

              Text {
                visible: root.pendingRepo === modelData.id && root.fastPollActive
                text: "\u2026"
                color: root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                Layout.alignment: Qt.AlignVCenter
              }

              Button {
                text: "Update"
                Layout.rightMargin: Style.space(6)
                foreground: root.fg
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY
                active: true
                onClicked: { root.updateRepo(modelData.id); root.close() }
              }
            }
          }
        }

        Text {
          visible: {
            if (root.settingsMode) return false
            if (root.installedRepos.length === 0) return false
            for (var i = 0; i < root.installedRepos.length; i++) {
              if (root.installedRepos[i].count > 0) return false
            }
            return true
          }
          Layout.fillWidth: true
          Layout.topMargin: Style.space(4)
          text: "System is up to date."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          horizontalAlignment: Text.AlignHCenter
        }

        ColumnLayout {
          id: settingsContentLayout
          visible: root.settingsMode
          spacing: Style.space(10)

          readonly property bool editorActive: refreshIntervalField.field.activeFocus

          SectionCard {
            title: "Refresh"

            ColumnLayout {
              width: parent.width
              spacing: Style.space(8)

              NumberField {
                id: refreshIntervalField
                label: "Check for updates every (seconds)"
                value: Number(root.draftValue("refreshIntervalSec", 1800))
                from: 300
                to: 7200
                stepSize: 300
                fieldWidth: parent.width
                foreground: root.fg
                accent: Color.accent
                fontFamily: root.fontFamily
                onModified: function(value) { root.setDraftValue("refreshIntervalSec", value) }
              }

              Text {
                Layout.fillWidth: true
                text: "How often the scanner checks for system updates."
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }
          }

          SectionCard {
            title: "Visibility"

            ColumnLayout {
              width: parent.width
              spacing: Style.space(8)

              Toggle {
                Layout.fillWidth: true
                label: "Always Show"
                description: checked ? "Icon visible even with no updates" : "Icon hidden when no updates available"
                checked: root.draftValue("alwaysShow", true) === true
                foreground: root.fg
                accent: Color.accent
                fontFamily: root.fontFamily
                onClicked: root.setDraftValue("alwaysShow", !checked)
              }
            }
          }

          Text {
            visible: root.settingsStatusText !== ""
            Layout.fillWidth: true
            text: root.settingsStatusText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }

          Text {
            Layout.fillWidth: true
            text: "s saves \u00B7 esc closes"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }
    }
  }

  component SectionCard: BorderSurface {
    id: section
    property string title: ""
    default property alias content: body.data

    Layout.fillWidth: true
    color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.055)
    borderSpec: Border.flat(Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.08), 1)
    radius: Style.cornerRadius
    padding: Style.space(10)
    implicitHeight: body.implicitHeight + contentTopInset + contentBottomInset

    ColumnLayout {
      id: body
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.topMargin: section.contentTopInset
      anchors.rightMargin: section.contentRightInset
      anchors.bottomMargin: section.contentBottomInset
      anchors.leftMargin: section.contentLeftInset
      spacing: Style.space(8)

      Text {
        visible: section.title !== ""
        Layout.fillWidth: true
        text: section.title
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }
}
