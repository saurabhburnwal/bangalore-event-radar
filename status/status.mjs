import {metrics, stale} from './metrics.mjs'

const names = {luma:'Luma', unstop:'Unstop', devfolio:'Devfolio', meetup:'Meetup', gdg:'GDG', hackbriven:'Hackbriven', hasgeek:'Hasgeek'}
const format = new Intl.DateTimeFormat('en-IN', {dateStyle:'medium', timeStyle:'short', timeZone:'Asia/Kolkata'})
const element = id => document.getElementById(id)
const repository = location.hostname.endsWith('.github.io')
  ? location.hostname.split('.')[0] + '/' + location.pathname.split('/')[1]
  : 'saurabhburnwal/bangalore-event-radar'
element('workflow').href = 'https://github.com/' + repository + '/actions/workflows/poll.yml'
let data

function render() {
  const now = Date.now()
  const last = data?.last_usable
  element('last').textContent = last ? stale(last, now) + ' · Last usable check ' + format.format(Date.parse(last)) + ' IST'
    : data ? 'Unknown · No usable check recorded yet.' : 'Unknown · Feed status is unavailable.'
  const rows = []
  for (const [key, row] of Object.entries(data?.sources ?? names)) {
    const tr = document.createElement('tr')
    for (const value of [names[key] ?? key, row.outcome ?? 'Unknown', row.events ?? '—',
      row.last_usable ? format.format(Date.parse(row.last_usable)) : '—', stale(row.last_usable, now)]) {
      const td = document.createElement('td')
      td.textContent = value
      td.dataset.value = value
      tr.append(td)
    }
    rows.push(tr)
  }
  element('feeds').replaceChildren(...rows)
  const measured = data && metrics(data, now)
  element('coverage').textContent = measured?.hours ? Math.round(100 * measured.covered / measured.hours) + '%' : '—'
  element('windows').textContent = measured ? measured.covered + ' of ' + measured.hours + ' completed hours in the last 7 days' : 'Completed hours over the last 7 days'
  const minutes = measured ? Math.floor(measured.gap / 60000) : 0
  element('gap').textContent = measured ? Math.floor(minutes / 60) + 'h ' + minutes % 60 + 'm' : '—'
}

async function refresh() {
  try {
    const response = await fetch('https://api.github.com/repos/' + repository + '/contents/state/status.json?ref=main',
      {cache:'no-store', headers:{Accept:'application/vnd.github.raw+json'}})
    if (!response.ok) throw Error()
    const snapshot = await response.json()
    if (!Number.isFinite(Date.parse(snapshot.started_at)) || !Array.isArray(snapshot.polls) || !snapshot.sources) throw Error()
    data = snapshot
  } catch {
    data = undefined
  }
  render()
}
refresh()
setInterval(refresh, 5 * 60000)
setInterval(render, 30000)
