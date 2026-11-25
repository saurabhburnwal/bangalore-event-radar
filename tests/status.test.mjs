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

test('downloadable dashboard includes all local assets and native status uses the poll time', async () => {
  const {mkdtempSync, readFileSync, writeFileSync, rmSync} = await import('node:fs')
  const {execFileSync} = await import('node:child_process')
  const {tmpdir} = await import('node:os')
  const {join} = await import('node:path')
  const dir = mkdtempSync(join(tmpdir(), 'radar-status-'))
  try {
    const html = join(dir, 'status.html')
    execFileSync(process.execPath, ['scripts/build-status.mjs', html])
    const page = readFileSync(html, 'utf8')
    assert.match(page, /<style>/)
    assert.match(page, /function metrics\(/)
    assert.doesNotMatch(page, /from '\.\/metrics|src="status.mjs"|href="status.css"/)
    const json = join(dir, 'status.json')
    const md = join(dir, 'status.md')
    writeFileSync(json, JSON.stringify({started_at:stamp(0), last_attempt:stamp(3), last_usable:stamp(2),
      polls:[stamp(0),stamp(2)], sources:{gdg:{events:0,outcome:'failed',last_usable:stamp(2)}}}))
    execFileSync(process.execPath, ['scripts/status-snapshot.mjs', json, md])
    const snapshot = readFileSync(md, 'utf8')
    assert.match(snapshot, /67% coverage across 2 of 3 completed hours/)
    const review = join(dir, 'first-week.md')
    const later = join(dir, 'later.json')
    writeFileSync(later, JSON.stringify({started_at:stamp(0), last_attempt:stamp(400), polls:[stamp(400)], sources:{}}))
    execFileSync(process.execPath, ['scripts/status-snapshot.mjs', later, md, review, json])
    assert.match(readFileSync(review, 'utf8'), /2 of 168 hours/)
    assert.match(readFileSync(md, 'utf8'), /first-week.md/)
    assert.match(snapshot, /gdg \| failed \| 0 .* Stale \|/)
  } finally {
    rmSync(dir, {recursive:true, force:true})
  }
})
