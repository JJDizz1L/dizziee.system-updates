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

function repoById(repos, id) {
  for (var i = 0; i < repos.length; i++) {
    if (repos[i].id === id) return repos[i]
  }
  return null
}

if (typeof module !== "undefined") {
  module.exports = {
    parseRepoList: parseRepoList,
    repoById: repoById
  }
}
