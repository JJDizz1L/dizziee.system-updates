import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Networking
import qs.Commons
import qs.Commons as Commons
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
  property var repoStatus: ({ "pacman": "idle", "aur": "idle", "flatpak": "idle", "omarchy": "idle", "mise": "idle" })
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
  readonly property color fg: root.bar ? root.bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"
  Commons.Translations {
    id: strings
    directory: Qt.resolvedUrl("i18n")
  }

  function fmtInt(value) {
    return Commons.I18n.formatNumber(Math.floor(Number(value) || 0))
  }
  // Only skip curl probes when NetworkManager definitively reports no
  // connectivity. Unknown/Portal/Limited must still attempt curl (ground
  // truth) — requiring Full here marked all repos offline when NM checks
  // are disabled, unconfigured, or return a captive-portal/limited state.
  readonly property bool networkOnline: !Networking.canCheckConnectivity || Networking.connectivity !== NetworkConnectivity.None
  readonly property var repoUrls: ({
    "pacman": "https://archlinux.org/packages/",
    "aur": "https://aur.archlinux.org/",
    "flatpak": "https://flathub.org/",
    "omarchy": "https://omarchy.org/",
    "mise": "https://mise-versions.jdx.dev/"
  })

  // Update commands are owned by this panel, not by the scan cache. The cache
  // is user-writable, so a command read back from it must never reach a shell.
  // AUR is the only repo whose command depends on the installed helper; the
  // scanner reports that helper as a fixed enum and it is validated below.
  readonly property var repoUpdateCommands: ({
    "pacman": "sudo env OMARCHY_ALLOW_DIRECT_PACMAN=1 pacman -Syu; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
    "flatpak": "flatpak update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
    "omarchy": "omarchy update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
    "plugins": "omarchy plugin update --yes; omarchy theme update; echo; read -n 1 -s -r -p 'Done. Press any key to close'",
    "mise": "MISE_MINIMUM_RELEASE_AGE=0 mise up; echo; read -n 1 -s -r -p 'Done. Press any key to close'"
  })
  readonly property var aurHelpers: ["checkupdates-aur", "yay", "paru"]

  // Rows the user has expanded to reveal their pending packages, keyed by
  // repo id. A plain object keeps multiple rows open at once.
  property var expandedRepos: ({})

  function isRepoExpanded(id) {
    return expandedRepos[id] === true
  }

  function toggleRepo(id) {
    var next = {}
    for (var key in expandedRepos) next[key] = expandedRepos[key]
    next[id] = !next[id]
    expandedRepos = next
  }

  function openUrl(url) {
    if (Model.isWebUrl(url)) Qt.openUrlExternally(url)
  }

  function refresh() {
    if (!scannerProc.running) scannerProc.running = true
  }

  property string lastCacheText: ""

  // Last-good scan result on disk: the bar renders it instantly at shell
  // start with zero spawns, and the first live scan waits for bootTimer.
  // The file lives in ~/.cache/omarchy, which already exists.
  readonly property string cachePath: {
    var base = Quickshell.env("XDG_CACHE_HOME")
    if (!base) base = Quickshell.env("HOME") + "/.cache"
    return base + "/omarchy/dizziee.system-updates.json"
  }

  function updateRepos(raw) {
    var text = String(raw || "")
    var parsed = Model.parseRepoList(text)
    repos = parsed.repos
    total = parsed.total
    // One small disk write per changed result, not per poll; the
    // text !== lastCacheText guard also makes a write->load echo a no-op.
    if (text !== "" && text !== lastCacheText) {
      lastCacheText = text
      try { cacheFile.setText(text) } catch (e) {}
    }
  }

  function iconSource(id) {
    if (id === "pacman") return Qt.resolvedUrl("assets/arch-logo.svg")
    if (id === "aur") return Qt.resolvedUrl("assets/arch-logo.svg")
    if (id === "flatpak") return Qt.resolvedUrl("assets/flatpak.svg")
    if (id === "omarchy") return Qt.resolvedUrl("assets/omarchy.svg")
    if (id === "plugins") return Qt.resolvedUrl("assets/plugins.svg")
    if (id === "mise") return Qt.resolvedUrl("assets/mise.svg")
    return ""
  }

  // Counts come from the scan cache, so coerce them before placing them in
  // the one rich-text label this panel builds. Anything else in that label is
  // a fixed string or a timestamp this panel generated.
  function nonNegativeCount(value) {
    var count = Number(value)
    return isFinite(count) && count > 0 ? Math.floor(count) : 0
  }

  // One styled, elide-able string per repo card so long metadata can never
  // render underneath the Update button.
  function statusHtml(repo) {
    var fg = root.fg.toString()
    var dim = root.dim.toString()
    var accent = Commons.Color.accent.toString()
    var urgent = Commons.Color.urgent.toString()
    var count = root.nonNegativeCount(repo.count)
    var pkgCount = root.nonNegativeCount(repo.pkgCount)
    var parts = []
    if (count > 0) {
      var countText = count === 1 ? strings.t("updates.oneUpdate").arg(fmtInt(count)) : strings.t("updates.manyUpdates").arg(fmtInt(count))
      parts.push("<font color=\"" + fg + "\">" + countText + "</font>")
    } else {
      parts.push("<font color=\"" + dim + "\">" + strings.t("updates.upToDateShort") + "</font>")
    }
    var status = root.repoStatus[repo.id]
    if (pkgCount > 0)
      parts.push("<font color=\"" + dim + "\">· " + strings.t("updates.pkgs").arg(fmtInt(pkgCount)) + "</font>")
    if (status === "checking")
      parts.push("<i><font color=\"" + dim + "\">· " + strings.t("updates.checking") + "</font></i>")
    else if (status === "online")
      parts.push("<font color=\"" + accent + "\">● " + strings.t("updates.online") + "</font>")
    else if (status === "offline")
      parts.push("<font color=\"" + urgent + "\">✗ " + strings.t("updates.offline") + "</font>")
    if (root.lastCheckedText !== "" && status !== "checking" && status !== "idle")
      parts.push("<font color=\"" + dim + "\">· Checked " + root.lastCheckedText + "</font>")
    return parts.join(" ")
  }

  function updateCommandFor(repo) {
    var id = String(repo && repo.id || "")
    if (id === "aur") {
      var helper = String(repo.updater || "")
      if (root.aurHelpers.indexOf(helper) === -1) return ""
      return helper + (helper === "checkupdates-aur" ? "" : " -Sua")
        + "; echo; read -n 1 -s -r -p 'Done. Press any key to close'"
    }
    return Object.prototype.hasOwnProperty.call(root.repoUpdateCommands, id)
      ? root.repoUpdateCommands[id] : ""
  }

  function updateRepo(id) {
    var repo = null
    for (var i = 0; i < repos.length; i++) {
      if (repos[i].id === id) {
        repo = repos[i]
        break
      }
    }
    var cmd = root.updateCommandFor(repo)
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
    fastPollTimer.interval = 10000
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
    fastPollTimer.interval = 10000
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
      var id = String(r.id || "")
      // The cache is user-writable: only an id this panel knows may be
      // spliced into the shell command below.
      if (!Object.prototype.hasOwnProperty.call(repoUrls, id)) continue
      var url = repoUrls[id]
      // Every installed repo is probed — the Online/Offline badge is useful
      // on up-to-date repos too, not just ones with updates waiting.
      if (r.installed !== true) continue
      script += "(curl -sI --connect-timeout 6 --max-time 9 " + url +
        " >/dev/null 2>&1 && echo '" + id + " online' || echo '" + id + " offline') & "
    }
    return script + "wait"
  }

  function pingRepos() {
    if (Date.now() - lastPingAt < 600000 && repoStatus.pacman !== "idle") return
    lastPingAt = Date.now()
    updateLastChecked()
    var next = {}
    for (var k in repoStatus) next[k] = repoStatus[k]
    var pinged = 0
    for (var i = 0; i < repos.length; i++) {
      var r = repos[i]
      var id = String(r.id || "")
      if (r.installed === true && Object.prototype.hasOwnProperty.call(repoUrls, id)) {
        next[id] = "checking"
        pinged++
      }
    }
    repoStatus = next
    if (pinged === 0) return

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
    if (elapsed < 60) lastCheckedText = strings.t("updates.checkedAgoSec").arg(fmtInt(elapsed))
    else if (elapsed < 3600) lastCheckedText = strings.t("updates.checkedAgoMin").arg(fmtInt(Math.floor(elapsed / 60)))
    else lastCheckedText = strings.t("updates.checkedAgoHour").arg(fmtInt(Math.floor(elapsed / 3600)))
  }

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  // `omarchy bar set` stores a bare value as a JSON string unless --json is
  // used, so a boolean read back from shell.json can be "false". Coerce it
  // instead of treating every non-false value as true.
  function boolValue(value, fallback) {
    if (value === undefined || value === null) return fallback
    if (typeof value === "string") return value !== "false" && value !== "0" && value !== ""
    return value !== false
  }

  function boolSetting(name, fallback) {
    return root.boolValue(root.setting(name, fallback), fallback)
  }

  readonly property bool autoRefresh: root.boolSetting("autoRefresh", true)
  readonly property bool alwaysShow: root.boolSetting("alwaysShow", true)
  readonly property int refreshIntervalSec: {
    var value = Number(root.setting("refreshIntervalSec", 1800))
    if (!isFinite(value)) value = 1800
    return Math.round(root.clamp(value, 300, 7200))
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
    next.alwaysShow = root.boolValue(next.alwaysShow, true)
    next.autoRefresh = root.boolValue(next.autoRefresh, true)
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
      settingsStatusText = strings.t("updates.savedToShell")
    } else {
      settingsStatusText = strings.t("updates.savedForSession")
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

  // The Panel base auto-wires open/close/show/hide/toggle IPC, but has no
  // headless refresh — and a second IpcHandler on the same target conflicts
  // with it. So take over IPC wholesale (unifi-panel pattern) and re-expose
  // the full set plus refresh, which runs a scan without opening the panel.
  manageIpc: false

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }
  }

  visible: total > 0 || root.alwaysShow
  implicitWidth: visible ? button.implicitWidth : 0
  implicitHeight: visible ? button.implicitHeight : 0

  Process {
    id: scannerProc
    command: ["python3", pathFromUrl(Qt.resolvedUrl("scripts/check_updates.py"))]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.updateRepos(text)
    }
    stderr: StdioCollector {
      id: scannerErr
      waitForEnd: true
    }
    // A failed scan used to be completely silent (empty output parses to an
    // empty list, and nothing was logged). Surface it so the log — and the
    // missing cache file — actually says what broke.
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        var detail = String(scannerErr.text || "").replace(/\s+/g, " ").trim()
        console.warn("system-updates: scanner exited with code " + exitCode
          + (detail !== "" ? ": " + detail : ""))
      }
    }
  }

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0)
      return decodeURIComponent(value.substring(7))
    return value
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: root.autoRefresh
    repeat: true
    onTriggered: root.refresh()
  }

  // First live scan waits until after boot: the disk cache renders
  // instantly, so shell startup pays no scanner cost. Opening the panel
  // (middle-click, R key, or left-click) still scans immediately.
  Timer {
    id: bootTimer
    interval: 90000
    running: root.autoRefresh
    repeat: false
    onTriggered: root.refresh()
  }

  FileView {
    id: cacheFile
    path: root.cachePath
    watchChanges: false
    printErrors: false
    onLoaded: {
      root.lastCacheText = String(text() || "")
      root.updateRepos(text())
    }
  }

  Timer {
    id: fastPollTimer
    interval: 10000
    running: false
    repeat: true
    onTriggered: {
      root.refresh()
      root.fastPollCount++
      // Back off while the updater terminal stays open: early polls catch a
      // quick update, later ones just keep the numbers from going stale.
      if (root.fastPollCount >= 5) fastPollTimer.interval = 30000
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
        if (r.count > 0) parts.push(fmtInt(r.count) + " " + Model.text(r.name, 80))
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
    contentWidth: panel.fittedContentWidth(Style.space(560))
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
            textFormat: Text.PlainText
            text: root.settingsMode ? strings.t("updates.settingsTitle") : strings.t("updates.title")
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
          }

          Button {
            visible: root.settingsMode
            text: strings.t("updates.updates")
            foreground: root.fg
            tooltipText: strings.t("updates.backToUpdates")
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            onClicked: root.showMain()
          }

          Button {
            visible: root.settingsMode
            text: strings.t("updates.save")
            foreground: root.fg
            tooltipText: strings.t("updates.saveSettings")
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY
            active: true
            onClicked: root.saveSettings()
          }

          Button {
            visible: !root.settingsMode
            text: strings.t("updates.refresh")
            foreground: root.fg
            tooltipText: strings.t("updates.refreshStats")
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
          model: root.opened ? root.installedRepos : []

          delegate: BorderSurface {
            id: repoCard
            required property var modelData

            readonly property var packages: modelData.packages || []
            readonly property bool expandable: packages.length > 0
            readonly property bool expanded: root.isRepoExpanded(modelData.id)

            Layout.fillWidth: true
            color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.055)
            borderSpec: Border.flat(Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.08), 1)
            radius: Style.cornerRadius
            padding: Style.space(10)

            implicitHeight: repoColumn.implicitHeight + contentTopInset + contentBottomInset

            ColumnLayout {
              id: repoColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              anchors.leftMargin: repoCard.contentLeftInset
              anchors.rightMargin: repoCard.contentRightInset
              anchors.topMargin: repoCard.contentTopInset
              spacing: Style.space(6)

              // Header. The MouseArea sits under the row, so clicks on the
              // text or whitespace toggle the row while the Update button
              // keeps its own clicks.
              Item {
                Layout.fillWidth: true
                implicitHeight: repoRow.implicitHeight

                MouseArea {
                  anchors.fill: parent
                  enabled: repoCard.expandable
                  hoverEnabled: repoCard.expandable
                  cursorShape: repoCard.expandable ? Qt.PointingHandCursor : Qt.ArrowCursor
                  onClicked: root.toggleRepo(repoCard.modelData.id)
                }

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
                      textFormat: Text.PlainText
                      text: modelData.name
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      font.bold: true
                    }

                    Text {
                      Layout.fillWidth: true
                      textFormat: Text.StyledText
                      elide: Text.ElideRight
                      text: root.statusHtml(modelData)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  Item { Layout.fillWidth: true }

                  Text {
                    textFormat: Text.PlainText
                    visible: root.pendingRepo === modelData.id && root.fastPollActive
                    text: "\u2026"
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    Layout.alignment: Qt.AlignVCenter
                  }

                  Text {
                    textFormat: Text.PlainText
                    visible: repoCard.expandable
                    text: repoCard.expanded ? "\uF078" : "\uF054"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    Layout.alignment: Qt.AlignVCenter
                  }

                  Button {
                    text: strings.t("updates.update")
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

              // Expanded package list. Each package links to its release notes
              // when the upstream is a known code host, else to its repo. The
              // list is capped and scrolls so a large batch can't overflow the
              // panel.
              Flickable {
                id: packageList
                visible: repoCard.expanded
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(packagesColumn.implicitHeight, Style.space(260))
                contentWidth: width
                contentHeight: packagesColumn.implicitHeight
                clip: true
                interactive: contentHeight > height
                boundsBehavior: Flickable.StopAtBounds

                ColumnLayout {
                  id: packagesColumn
                  width: parent.width
                  spacing: Style.space(2)

                  Repeater {
                    model: repoCard.packages

                    delegate: RowLayout {
                      required property var modelData
                      Layout.fillWidth: true
                      spacing: Style.space(8)

                      Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: modelData.name
                        color: root.fg
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.bodySmall
                        elide: Text.ElideRight
                      }

                      Text {
                        textFormat: Text.PlainText
                        visible: (modelData.from || "") !== "" || (modelData.to || "") !== ""
                        text: ((modelData.from || "") !== "" ? modelData.from + " \u2192 " : "") + (modelData.to || "")
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        Layout.alignment: Qt.AlignVCenter
                      }

                      Text {
                        id: linkText
                        textFormat: Text.PlainText
                        visible: (modelData.url || "") !== ""
                        text: modelData.label || strings.t("updates.repo")
                        color: linkMouse.containsMouse ? root.fg : Commons.Color.accent
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.underline: linkMouse.containsMouse
                        Layout.alignment: Qt.AlignVCenter

                        MouseArea {
                          id: linkMouse
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.openUrl(modelData.url)
                        }

                        PanelToolTip {
                          visible: linkMouse.containsMouse
                          text: modelData.url || ""
                          fontFamily: root.fontFamily
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }

        Text {
          textFormat: Text.PlainText
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
          text: strings.t("updates.upToDate")
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
            title: strings.t("updates.refreshSection")

            ColumnLayout {
              width: parent.width
              spacing: Style.space(8)

              NumberField {
                id: refreshIntervalField
                label: strings.t("updates.refreshInterval")
                value: Number(root.draftValue("refreshIntervalSec", 1800))
                from: 300
                to: 7200
                stepSize: 300
                fieldWidth: parent.width
                foreground: root.fg
                accent: Commons.Color.accent
                fontFamily: root.fontFamily
                onModified: function(value) { root.setDraftValue("refreshIntervalSec", value) }
              }

              Text {
                Layout.fillWidth: true
                textFormat: Text.PlainText
                text: strings.t("updates.refreshHelp")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }

              Toggle {
                Layout.fillWidth: true
                label: strings.t("updates.autoChecks")
                description: checked ? strings.t("updates.autoChecksOn") : strings.t("updates.autoChecksOff")
                checked: root.draftValue("autoRefresh", true) === true
                foreground: root.fg
                accent: Commons.Color.accent
                fontFamily: root.fontFamily
                onClicked: root.setDraftValue("autoRefresh", !checked)
              }
            }
          }

          SectionCard {
            title: strings.t("updates.visibility")

            ColumnLayout {
              width: parent.width
              spacing: Style.space(8)

              Toggle {
                Layout.fillWidth: true
                label: strings.t("updates.alwaysShow")
                description: checked ? strings.t("updates.alwaysShowOn") : strings.t("updates.alwaysShowOff")
                checked: root.draftValue("alwaysShow", true) === true
                foreground: root.fg
                accent: Commons.Color.accent
                fontFamily: root.fontFamily
                onClicked: root.setDraftValue("alwaysShow", !checked)
              }
            }
          }

          Text {
            textFormat: Text.PlainText
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
            textFormat: Text.PlainText
            text: strings.t("updates.keysHint")
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
        textFormat: Text.PlainText
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
