// The scan cache is user-writable, so treat it as untrusted input. Keep only
// the repos this panel knows how to render and the fields it actually uses,
// with all strings and collections bounded.
var MAX_REPOS = 16
var MAX_PACKAGES_PER_REPO = 1000
var MAX_COUNT = 1000000
var MAX_URL = 2048
var KNOWN_REPO_IDS = {
  "pacman": true,
  "aur": true,
  "flatpak": true,
  "omarchy": true,
  "plugins": true,
  "mise": true
}

function text(value, limit) {
  if (value === undefined || value === null) return ""
  var result = typeof value === "string" ? value : String(value)
  return result.length > limit ? result.slice(0, limit) : result
}

function count(value, limit) {
  var number = Number(value)
  if (!isFinite(number) || number <= 0) return 0
  return Math.min(Math.floor(number), limit)
}

function parseRepoList(raw) {
  var data
  try {
    data = JSON.parse(String(raw || "{}"))
  } catch (e) {
    return { repos: [], total: 0 }
  }
  if (!data || !Array.isArray(data.repos)) return { repos: [], total: 0 }

  var repos = []
  for (var i = 0; i < data.repos.length && repos.length < MAX_REPOS; i++) {
    var source = data.repos[i]
    if (!source || typeof source !== "object" || Array.isArray(source)) continue
    var id = text(source.id, 64)
    if (!Object.prototype.hasOwnProperty.call(KNOWN_REPO_IDS, id)) continue

    var packages = []
    if (Array.isArray(source.packages)) {
      for (var j = 0; j < source.packages.length && packages.length < MAX_PACKAGES_PER_REPO; j++) {
        var sourcePackage = source.packages[j]
        if (!sourcePackage || typeof sourcePackage !== "object" || Array.isArray(sourcePackage)) continue
        var name = text(sourcePackage.name, 200)
        if (!name) continue
        packages.push({
          name: name,
          from: text(sourcePackage.from, 100),
          to: text(sourcePackage.to, 100),
          url: text(sourcePackage.url, MAX_URL),
          label: text(sourcePackage.label, 64)
        })
      }
    }

    repos.push({
      id: id,
      name: text(source.name, 80) || id,
      count: count(source.count, MAX_COUNT),
      pkgCount: count(source.pkgCount, MAX_COUNT),
      icon: text(source.icon, 80),
      updater: text(source.updater, 32),
      installed: source.installed === true,
      packages: packages
    })
  }
  return { repos: repos, total: count(data.total, MAX_COUNT) }
}

// Automatic background scans are on unless explicitly turned off. Off means
// the scanner runs only when the panel is opened or refreshed by hand.
function autoRefreshEnabled(value) {
  return value !== false
}

// Upstream links come from package metadata, which is not ours to trust, so
// only plain web addresses are ever handed to the browser.
function isWebUrl(url) {
  return /^https?:\/\/\S/i.test(String(url || ""))
}

if (typeof module !== "undefined") {
  module.exports = {
    parseRepoList: parseRepoList,
    autoRefreshEnabled: autoRefreshEnabled,
    isWebUrl: isWebUrl
  }
}
