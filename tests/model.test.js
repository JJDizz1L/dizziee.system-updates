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
