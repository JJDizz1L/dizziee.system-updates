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

if (typeof module !== "undefined") {
  module.exports = {
    parseRepoList: parseRepoList
  }
}
