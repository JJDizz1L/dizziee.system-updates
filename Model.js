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

if (typeof module !== "undefined") {
  module.exports = {
    parseRepoList: parseRepoList,
    autoRefreshEnabled: autoRefreshEnabled
  }
}
