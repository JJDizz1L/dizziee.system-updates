function parseRepoList(raw) {
  try {
    var data = JSON.parse(String(raw || "{}"))
    if (!data || !Array.isArray(data.repos)) return { repos: [], total: 0 }
    return {
      repos: data.repos,
      total: data.total || 0
    }
  } catch (e) {
    return { repos: [], total: 0 }
  }
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
