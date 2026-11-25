const hour = 3600000
const week = 7 * 24 * hour

export function stale(timestamp, now) {
  const time = Date.parse(timestamp)
  if (!Number.isFinite(time)) return 'Unknown'
  return now - time >= hour ? 'Stale' : 'Fresh'
}

export function metrics(data, now) {
  const started = Date.parse(data.started_at)
  const endHour = Math.floor(now / hour)
  const firstHour = Math.max(endHour - 168, Math.ceil(started / hour))
  const since = Math.max(started, now - week)
  const times = data.polls.map(Date.parse).filter(Number.isFinite).sort((a, b) => a - b)
  const covered = new Set(times.map(t => Math.floor(t / hour)).filter(h => h >= firstHour && h < endHour))
  let previous = since
  let longest = 0
  for (const time of times.filter(t => t >= since && t <= now)) {
    longest = Math.max(longest, time - previous)
    previous = time
  }
  return {covered: covered.size, hours: Math.max(0, endHour - firstHour), gap: Math.max(longest, now - previous)}
}
