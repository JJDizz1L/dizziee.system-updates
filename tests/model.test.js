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

test("isWebUrl rejects local and other schemes", () => {
  assert.equal(Model.isWebUrl("file:///etc/passwd"), false)
  assert.equal(Model.isWebUrl("git://example.org/repo"), false)
  assert.equal(Model.isWebUrl("ext::sh -c id"), false)
  assert.equal(Model.isWebUrl("javascript:alert(1)"), false)
  assert.equal(Model.isWebUrl(" https://example.org/x"), false)
  assert.equal(Model.isWebUrl(""), false)
  assert.equal(Model.isWebUrl(undefined), false)
})
