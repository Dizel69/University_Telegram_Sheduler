/** Учебные семестры: границы включительно (локальная дата YYYY-MM-DD). */
export const ACADEMIC_SEMESTERS = [
  { label: '2 семестр', start: '2026-02-01', end: '2026-07-01' },
  { label: '3 семестр', start: '2026-09-01', end: '2027-01-25' },
  { label: '4 семестр', start: '2027-02-01', end: '2027-07-01' },
]

export function ymdFromDate(d) {
  const dt = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(dt.getTime())) return null
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const day = String(dt.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function getSemesterPeriodByLabel(label) {
  const t = (label || '').trim()
  if (!t) return null
  return ACADEMIC_SEMESTERS.find(s => s.label === t) || null
}

/**
 * Семестр для указанной календарной даты (строка YYYY-MM-DD или Date).
 */
export function getSemesterForDate(dateInput) {
  let ymd
  if (typeof dateInput === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateInput.trim())) {
    ymd = dateInput.trim()
  } else {
    ymd = ymdFromDate(dateInput)
  }
  if (!ymd) return null
  for (const s of ACADEMIC_SEMESTERS) {
    if (ymd >= s.start && ymd <= s.end) return s.label
  }
  return null
}

/** Семестр из календаря, который сейчас идёт по сегодняшней дате. */
export function getCurrentSemesterByToday() {
  return getSemesterForDate(new Date())
}

/** Каноническое название семестра, который ещё не начался относительно todayYmd. */
export function isFutureCanonicalSemesterLabel(label, todayYmd) {
  const p = getSemesterPeriodByLabel(label)
  if (!p) return false
  return p.start > todayYmd
}

export function listCanonicalSemesterLabelsStartedBy(todayYmd) {
  return ACADEMIC_SEMESTERS.filter(s => s.start <= todayYmd).map(s => s.label)
}
