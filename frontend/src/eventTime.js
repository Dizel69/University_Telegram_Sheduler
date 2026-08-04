/** Локальное wall-clock время границ события (как в EventsList). */

function parseYmd(dateStr) {
  if (!dateStr) return null
  const [year, month, day] = String(dateStr).split('-').map(Number)
  if (!year || !month || !day) return null
  return { year, month, day }
}

function parseHms(timeValue, fallback = [0, 0, 0]) {
  const parts = String(timeValue || '').split(':').map(Number)
  return [
    Number.isFinite(parts[0]) ? parts[0] : fallback[0],
    Number.isFinite(parts[1]) ? parts[1] : fallback[1],
    Number.isFinite(parts[2]) ? parts[2] : fallback[2],
  ]
}

function toMs(now) {
  return typeof now === 'number' ? now : (now instanceof Date ? now.getTime() : Date.now())
}

/** Начало события: date + time, иначе 00:00. */
export function parseEventStart(ev) {
  const ymd = parseYmd(ev?.date)
  if (!ymd) return null
  const [h, m, s] = ev?.time ? parseHms(ev.time, [0, 0, 0]) : [0, 0, 0]
  return new Date(ymd.year, ymd.month - 1, ymd.day, h, m, s)
}

/**
 * Конец события: end_time, иначе time, иначе 23:59:59.
 * Совпадает с логикой «завершённых» в EventsList.
 */
export function parseEventEnd(ev) {
  const ymd = parseYmd(ev?.date)
  if (!ymd) return null
  const timeValue = ev?.end_time || ev?.time || '23:59:59'
  const [h, m, s] = parseHms(timeValue, [23, 59, 59])
  return new Date(ymd.year, ymd.month - 1, ymd.day, h, m, s)
}

/** @deprecated alias — совместимость с EventsList */
export function parseEventBoundary(ev) {
  return parseEventEnd(ev)
}

export function isPastEvent(ev, now = Date.now()) {
  const end = parseEventEnd(ev)
  if (!end) return false
  return end.getTime() < toMs(now)
}

export function isCompletedEvent(ev, now = Date.now()) {
  return isPastEvent(ev, now)
}

/**
 * Идёт прямо сейчас: пары и контрольные/экзамены с известным интервалом.
 * Если есть только time без end_time — считаем длительность 90 минут.
 */
export function isOngoingEvent(ev, now = Date.now()) {
  const type = String(ev?.type || '').toLowerCase()
  if (type !== 'schedule' && type !== 'exam_control') return false
  if (!ev?.time) return false

  const start = parseEventStart(ev)
  if (!start) return false

  let endMs
  if (ev.end_time) {
    const end = parseEventEnd(ev)
    if (!end) return false
    endMs = end.getTime()
  } else {
    endMs = start.getTime() + 90 * 60 * 1000
  }

  const n = toMs(now)
  return start.getTime() <= n && n <= endMs
}

export function eventTemporalClass(ev, now = Date.now()) {
  if (isOngoingEvent(ev, now)) return 'is-ongoing'
  if (isPastEvent(ev, now)) return 'is-past'
  return ''
}
