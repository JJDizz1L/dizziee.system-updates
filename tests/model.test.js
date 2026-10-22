// Run with: node --test tests/
const test = require("node:test")
const assert = require("node:assert/strict")
const Model = require("../Model.js")

test("autoRefreshEnabled defaults to on", () => {
  assert.equal(Model.autoRefreshEnabled(undefined), true)
  assert.equal(Model.autoRefreshEnabled(null), true)
  assert.equal(Model.autoRefreshEnabled(true), true)
})

test("autoRefreshEnabled is off only when explicitly false", () => {
  assert.equal(Model.autoRefreshEnabled(false), false)
})

test("isWebUrl accepts only http and https", () => {
  assert.equal(Model.isWebUrl("https://github.com/owner/repo"), true)
  assert.equal(Model.isWebUrl("http://example.org/x"), true)
  assert.equal(Model.isWebUrl("HTTPS://example.org/x"), true)
})

test("parseRepoList rejects malformed input", () => {
  assert.deepEqual(Model.parseRepoList("not json"), { repos: [], total: 0 })
  assert.deepEqual(Model.parseRepoList('{"repos":{}}'), { repos: [], total: 0 })
  assert.deepEqual(Model.parseRepoList(""), { repos: [], total: 0 })
})

test("parseRepoList keeps known repos and drops unknown ids", () => {
  const result = Model.parseRepoList(JSON.stringify({
    total: "7",
    repos: [
      { id: "pacman", name: "Arch", count: "2", pkgCount: 100, installed: true, packages: [] },
      { id: "__proto__", name: "bad", count: 9, installed: true },
      { id: "not-a-repo", name: "bad", count: 9, installed: true }
    ]
  }))
  assert.equal(result.total, 7)
  assert.equal(result.repos.length, 1)
  assert.equal(result.repos[0].id, "pacman")
  assert.equal(result.repos[0].count, 2)
  assert.equal(result.repos[0].pkgCount, 100)
  assert.equal(result.repos[0].installed, true)
})

test("parseRepoList bounds strings, counts, packages and repo count", () => {
  const packages = Array.from({ length: 1005 }, (_, index) => ({
    name: "pkg-" + index + "-" + "x".repeat(300),
    from: "a".repeat(300),
    to: "b".repeat(300),
    url: "https://example.org/" + "c".repeat(3000),
    label: "d".repeat(100)
  }))
  const repos = Array.from({ length: 20 }, (_, index) => ({
    id: "mise",
    name: "n".repeat(200),
    count: 1e12,
    pkgCount: -4,
    installed: true,
    packages: packages
  }))
  const result = Model.parseRepoList(JSON.stringify({ total: 1e12, repos: repos }))
  assert.equal(result.total, 1000000)
  assert.equal(result.repos.length, 16)
  assert.equal(result.repos[0].name.length, 80)
  assert.equal(result.repos[0].count, 1000000)
  assert.equal(result.repos[0].pkgCount, 0)
  assert.equal(result.repos[0].packages.length, 1000)
  assert.equal(result.repos[0].packages[0].name.length, 200)
  assert.equal(result.repos[0].packages[0].from.length, 100)
  assert.equal(result.repos[0].packages[0].url.length, 2048)
  assert.equal(result.repos[0].packages[0].label.length, 64)
})

test("parseRepoList prefers a fallback name and strict installed flag", () => {
  const result = Model.parseRepoList(JSON.stringify({
    repos: [{ id: "aur", installed: "true" }]
  }))
  assert.equal(result.repos[0].name, "aur")
  assert.equal(result.repos[0].installed, false)
})

test("isWebUrl rejects local and other schemes", () => {
  assert.equal(Model.isWebUrl("file:///etc/passwd"), false)
  assert.equal(Model.isWebUrl("git://example.org/repo"), false)
  assert.equal(Model.isWebUrl("ext::sh -c id"), false)
  assert.equal(Model.isWebUrl("javascript:alert(1)"), false)
  assert.equal(Model.isWebUrl(" https://example.org/x"), false)
  assert.equal(Model.isWebUrl(""), false)
  assert.equal(Model.isWebUrl(undefined), false)
})
