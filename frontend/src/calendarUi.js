export function calendarTypeOrder(t) {
  if (t === 'exam_control') return 0
  if (t === 'homework') return 1
  if (t === 'birthday') return 2
  return 2
}

export function localIsoDate(d = new Date()) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function isoFromUtcDate(dt) {
  return dt.toISOString().slice(0, 10)
}

export function formatTimeRange(t, end) {
  if (!t && !end) return ''
  const s = t ? t.slice(0, 5) : ''
  const e = end ? end.slice(0, 5) : ''
  if (s && e) return `${s} – ${e}`
  return s || e
}

export function lessonIcon(lessonType) {
  if (lessonType === 'lecture') return '🔊'
  if (lessonType === 'practice') return '📓'
  return ''
}

export function examKindIcon(lessonType) {
  if (lessonType === 'exam') return '🎓'
  if (lessonType === 'control') return '📝'
  return '📝'
}

export function typeColor(t) {
  if (!t) return '#6b7280'
  const n = String(t).toLowerCase().trim()
  if (n.includes('schedule') || n.includes('расписание')) return '#60a5fa'
  if (n.includes('exam_control') || n.includes('контрольн') || n.includes('экзамен')) return '#f97316'
  if (n.includes('homework') || n.includes('домаш') || n.includes('домашнее_задание') || n.includes('домашняя_работа')) return '#a78bfa'
  if (n.includes('transfer') || n.includes('перенос')) return '#ef4444'
  if (n.includes('announcement') || n.includes('объявлен')) return '#34d399'
  if (n.includes('birthday') || n.includes('рождени')) return '#facc15'
  return '#9ca3af'
}

export function eventColor(ev) {
  try {
    if (!ev) return typeColor(ev?.type)
    const body = (ev.body || '').toString().toLowerCase()
    const title = (ev.title || '').toString().toLowerCase()
    if (ev.type === 'birthday') return '#facc15'
    if (body.includes('перенос') || title.includes('перенос') || body.includes('перенес')) return '#ef4444'
    return typeColor(ev.type)
  } catch {
    return typeColor(ev?.type)
  }
}

export function eventTextColor(ev) {
  return ev?.type === 'birthday' ? '#713f12' : '#fff'
}

export function typeLabel(t) {
  if (!t) return ''
  const n = String(t).toLowerCase().trim()
  if (n.includes('birthday') || n.includes('рождени')) return 'День рождения'
  if (n.includes('transfer') || n.includes('перенос')) return 'Перенос'
  if (n.includes('homework') || n.startsWith('home') || n.includes('домаш')) return 'Домашняя работа'
  if (n.includes('exam_control') || n.includes('контрольн') || n.includes('экзамен')) return 'Контрольная / экзамен'
  if (n.includes('schedule') || n.includes('расписание')) return 'Расписание'
  if (n.includes('announcement') || n.includes('объявлен')) return 'Объявление'
  return t
}

export const WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
export const WEEKDAYS_NARROW = ['П', 'В', 'С', 'Ч', 'П', 'С', 'В']
export const WEEKDAYS_LONG = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
export const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

export function weekdayIndexMondayFirst(utcDate) {
  return (utcDate.getUTCDay() + 6) % 7
}

/** Полные недели месяца, включая дни соседних месяцев в начале и конце сетки. */
export function monthGridDays(year, month) {
  const first = new Date(Date.UTC(year, month, 1))
  const offset = weekdayIndexMondayFirst(first)
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
  const total = Math.ceil((offset + daysInMonth) / 7) * 7
  const list = []
  for (let i = 0; i < total; i++) {
    list.push(new Date(Date.UTC(year, month, 1 - offset + i)))
  }
  return list
}

export function isOutsideMonth(utcDate, month) {
  return utcDate.getUTCMonth() !== month
}

export function formatAgendaDayLabel(utcDate, todayIso) {
  const iso = isoFromUtcDate(utcDate)
  const weekday = WEEKDAYS_LONG[weekdayIndexMondayFirst(utcDate)]
  const dateText = `${utcDate.getUTCDate()} ${MONTHS_GENITIVE[utcDate.getUTCMonth()]}`
  const [y, m, d] = todayIso.split('-').map(Number)
  const today = new Date(Date.UTC(y, m - 1, d))
  const diffDays = Math.round((utcDate.getTime() - today.getTime()) / 86400000)
  let rel = ''
  if (diffDays === 0) rel = 'Сегодня'
  else if (diffDays === 1) rel = 'Завтра'
  else if (diffDays === -1) rel = 'Вчера'
  return { iso, weekday, dateText, rel, isWeekend: weekdayIndexMondayFirst(utcDate) >= 5 }
}

export function filterVisibleEvents(list, showHomework) {
  return (list || []).filter((ev) => showHomework || ev.type !== 'homework')
}
