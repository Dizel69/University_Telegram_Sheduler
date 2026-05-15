import React, { useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import {
  getSemesterForDate,
  isFutureCanonicalSemesterLabel,
  listCanonicalSemesterLabelsStartedBy,
  ymdFromDate,
} from './semesterCalendar'

function backendBase() {
  const host = import.meta.env.VITE_HOST || window.location.hostname
  return `http://${host}:8000`
}

const FILTER_ALL = '*'
const FILTER_NO_SEMESTER = '__none__'

function formatDate(dateStr) {
  if (!dateStr || dateStr === 'Без даты') return dateStr
  const date = new Date(dateStr)
  const options = { day: 'numeric', month: 'long', year: 'numeric', weekday: 'long' }
  const formatted = date.toLocaleDateString('ru-RU', options)
  const parts = formatted.split(', ')
  if (parts.length === 2) {
    const datePart = parts[0].replace(' г.', '')
    const weekdayPart = parts[1].charAt(0).toUpperCase() + parts[1].slice(1)
    return `${datePart}, ${weekdayPart}`
  }
  return formatted
}

function homeworkHeading(ev) {
  const t = (ev.title || ev.subject || '').trim()
  return t || '<без названия>'
}

function defaultSemesterFilter() {
  return getSemesterForDate(new Date()) || FILTER_ALL
}

export default function HomeworkList() {
  const [allHomework, setAllHomework] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [semesterFilter, setSemesterFilter] = useState(defaultSemesterFilter)
  const [subjectFilter, setSubjectFilter] = useState(FILTER_ALL)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(backendBase() + '/calendar?type=homework')
      let hw = res.data
      if (!Array.isArray(hw)) hw = []
      if (hw.length === 0) {
        const all = await axios.get(backendBase() + '/calendar')
        hw = (all.data || []).filter(ev => ev.type === 'homework')
      }
      hw.sort((a, b) => {
        if (!a.date) return 1
        if (!b.date) return -1
        return a.date.localeCompare(b.date)
      })
      setAllHomework(hw)
    } catch (e) {
      console.error(e)
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  const todayYmd = useMemo(() => ymdFromDate(new Date()), [])

  const visibleHomework = useMemo(() => {
    return allHomework.filter(ev => {
      const sem = (ev.semester || '').trim()
      if (sem && isFutureCanonicalSemesterLabel(sem, todayYmd)) return false
      return true
    })
  }, [allHomework, todayYmd])

  const anyWithoutSemester = useMemo(
    () => visibleHomework.some(ev => !(ev.semester || '').trim()),
    [visibleHomework]
  )

  const semesterOptions = useMemo(() => {
    const options = new Set(listCanonicalSemesterLabelsStartedBy(todayYmd))
    for (const ev of visibleHomework) {
      const s = (ev.semester || '').trim()
      if (!s) continue
      if (isFutureCanonicalSemesterLabel(s, todayYmd)) continue
      options.add(s)
    }
    return Array.from(options).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [visibleHomework, todayYmd])

  const subjectOptions = useMemo(() => {
    const set = new Set()
    for (const ev of visibleHomework) {
      set.add(homeworkHeading(ev))
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [visibleHomework])

  const currentSemester = useMemo(() => getSemesterForDate(todayYmd), [todayYmd])

  function shouldShowSemesterUnderSubject(ev) {
    const sem = (ev.semester || '').trim()
    if (!sem) return false
    if (semesterFilter !== FILTER_ALL && sem === semesterFilter) return false
    if (currentSemester && sem === currentSemester) return false
    return true
  }

  const filtered = useMemo(() => {
    return visibleHomework.filter(ev => {
      if (semesterFilter === FILTER_NO_SEMESTER) {
        if ((ev.semester || '').trim()) return false
      } else if (semesterFilter !== FILTER_ALL) {
        const sem = (ev.semester || '').trim()
        if (sem !== semesterFilter) return false
      }
      if (subjectFilter !== FILTER_ALL) {
        if (homeworkHeading(ev) !== subjectFilter) return false
      }
      return true
    })
  }, [visibleHomework, semesterFilter, subjectFilter])

  const events = useMemo(() => {
    const grouped = {}
    for (const ev of filtered) {
      const date = ev.date || 'Без даты'
      if (!grouped[date]) grouped[date] = []
      grouped[date].push(ev)
    }
    return grouped
  }, [filtered])

  return (
    <div className="card">
      <h2>Домашние задания</h2>
      <div className="homework-filters form-grid" style={{ marginTop: 12, marginBottom: 8 }}>
        <div>
          <label className="label">Семестр</label>
          <select value={semesterFilter} onChange={e => setSemesterFilter(e.target.value)}>
            <option value={FILTER_ALL}>Все семестры</option>
            {anyWithoutSemester && (
              <option value={FILTER_NO_SEMESTER}>Без семестра</option>
            )}
            {semesterOptions.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Предмет / тема</label>
          <select value={subjectFilter} onChange={e => setSubjectFilter(e.target.value)}>
            <option value={FILTER_ALL}>Все предметы</option>
            {subjectOptions.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
      {loading && <div>Загрузка...</div>}
      {error && <div className="error">Ошибка: {error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="status" style={{ marginTop: 8 }}>Нет заданий по выбранным фильтрам.</div>
      )}
      {Object.keys(events).sort((a, b) => {
        if (a === 'Без даты') return 1
        if (b === 'Без даты') return -1
        return a.localeCompare(b)
      }).map(date => (
        <div key={date} className="homework-day">
          <hr className="homework-divider" />
          <div className="homework-date">{formatDate(date)}</div>
          <div className="homework-list">
            {events[date].map(ev => (
              <div key={ev.id} className="homework-item-card">
                <div className="homework-subject">{homeworkHeading(ev)}</div>
                {shouldShowSemesterUnderSubject(ev) ? (
                  <div className="homework-semester">{(ev.semester || '').trim()}</div>
                ) : null}
                <div className="homework-body">{ev.body}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
