import assert from 'node:assert/strict'
import test from 'node:test'
import {metrics, stale} from '../status/metrics.mjs'
const stamp = h => new Date(Date.UTC(2026, 0, 1) + h * 3600000).toISOString()
test('freshness advances without a new poll', () => {
  assert.equal(stale(null, Date.parse(stamp(3))), 'Unknown')
  assert.equal(stale(stamp(2), Date.parse(stamp(3)) - 1), 'Fresh')
  assert.equal(stale(stamp(2), Date.parse(stamp(3))), 'Stale')
})
test('coverage counts completed observed hours once and includes the open gap', () => {
  const data = {started_at:stamp(.5), polls:[.5,1,1.5,3,7].map(stamp)}
  assert.deepEqual(metrics(data, Date.parse(stamp(8))), {covered:3,hours:7,gap:4*3600000})
  assert.deepEqual(metrics(data, Date.parse(stamp(200))), {covered:0,hours:168,gap:168*3600000})
})
