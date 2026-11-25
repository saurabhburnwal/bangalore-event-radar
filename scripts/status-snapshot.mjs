import {existsSync, readFileSync, writeFileSync} from 'node:fs'
import {metrics, stale} from '../status/metrics.mjs'

const data = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const now = Date.parse(data.last_attempt)
const {covered, hours, gap} = metrics(data, now)
const minutes = Math.floor(gap / 60000)
const format = new Intl.DateTimeFormat('en-GB', {dateStyle:'medium', timeStyle:'short', timeZone:'Asia/Kolkata'})
const display = t => t ? format.format(Date.parse(t)) : 'Unknown'
const repo = process.env.GITHUB_REPOSITORY || 'saurabhburnwal/bangalore-event-radar'
const url = 'https://github.com/' + repo
const [reviewPath, previousPath] = process.argv.slice(4)
const hour = 3600000
const firstHour = Math.ceil(Date.parse(data.started_at) / hour) * hour
const weekEnd = firstHour + 168 * hour
if (reviewPath && now >= weekEnd && !existsSync(reviewPath)) {
  // A long outage can age the first week's timestamps out of the latest projection.
  const previous = previousPath && existsSync(previousPath) ? JSON.parse(readFileSync(previousPath, 'utf8')) : {}
  const polls = [...new Set([...(previous.polls ?? []), ...data.polls])]
  const week = metrics({...data, polls}, weekEnd)
  const gapMinutes = Math.ceil(week.gap / 60000)
  const goal = week.gap <= hour ? 'The radar met the 60-minute target.' : 'The radar exceeded the 60-minute target.'
  writeFileSync(reviewPath, [
    '# First week of hourly coverage', '',
    display(new Date(firstHour).toISOString()) + ' to ' + display(new Date(weekEnd).toISOString()) + ' IST.', '',
    week.covered + ' of 168 hours had a usable poll (' + Math.round(100 * week.covered / 168) + '%).',
    'The longest gap within the week was ' + gapMinutes + ' minutes. ' + goal, ''
  ].join('\n'))
}
const content = [
  '# Bangalore Event Radar status', '',
  'Latest poll on **' + display(data.last_attempt) + ' IST**. Last usable poll on **' + display(data.last_usable) + ' IST**.', '',
  'Coverage and freshness below are measured at the latest poll. Open the downloaded dashboard to see current freshness, including while workflows are idle.', '',
  '[Download live dashboard](' + url + '/releases/download/feed-status/radar-status.html) · [Open poll workflow](' + url + '/actions/workflows/poll.yml)', '',
  '## Hourly coverage', '',
  (hours ? Math.round(100 * covered / hours) + '% coverage across ' + covered + ' of ' + hours + ' completed hours' : 'Waiting for the first full hour') +
    ' in the seven-day window. Longest gap observed was ' + Math.floor(minutes / 60) + 'h ' + minutes % 60 + 'm.', '',
  '| Source | Latest attempt | Listings | Last usable check (IST) | Freshness at poll |',
  '| --- | --- | ---: | --- | --- |',
  ...Object.entries(data.sources).map(([name, row]) =>
    '| ' + [name, row.outcome, row.events, display(row.last_usable), stale(row.last_usable, now)].join(' | ') + ' |'),
  '', 'A feed is stale after 60 minutes. A partial result includes the listings from the pages that loaded.', ''
].join('\n')
const reviewLink = reviewPath && existsSync(reviewPath) ? '\n[First-week coverage review](first-week.md)\n' : ''
writeFileSync(process.argv[3], content + reviewLink)
