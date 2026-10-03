import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { normalizeSemesterLabel } from './semesterCalendar'
import { FormattedBody } from './FormattedTextEditor'

const FILTER_ALL = '*'

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

function groupByDate(items) {
  const grouped = {}
  for (const ev of items) {
    const date = ev.date || 'Без даты'
    if (!grouped[date]) grouped[date] = []
    grouped[date].push(ev)
  }
  return grouped
}

export default function HomeworkList({ accountUser }) {
  const [allHomework, setAllHomework] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [subjectFilter, setSubjectFilter] = useState(FILTER_ALL)
  const [completedIds, setCompletedIds] = useState(() => new Set())
  const [hwTab, setHwTab] = useState('active')
  const [busyId, setBusyId] = useState(null)

  const loadCalendar = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let res = await axios.get('/calendar?type=homework')
      let hw = res.data
      if (!Array.isArray(hw)) hw = []
      if (hw.length === 0) {
        const all = await axios.get('/calendar')
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
  }, [])

  useEffect(() => { loadCalendar() }, [loadCalendar])

  const reloadCompletions = useCallback(async () => {
    if (!accountUser?.id) {
      setCompletedIds(new Set())
      return
    }
    try {
      const { data } = await axios.get('/homework-completion')
      const ids = data?.event_ids
      setCompletedIds(new Set(Array.isArray(ids) ? ids : []))
    } catch {
      setCompletedIds(new Set())
    }
  }, [accountUser])

  useEffect(() => { reloadCompletions() }, [reloadCompletions])

  useEffect(() => {
    function onUser() {
      reloadCompletions()
      loadCalendar()
    }
    window.addEventListener('user-auth-changed', onUser)
    return () => window.removeEventListener('user-auth-changed', onUser)
  }, [reloadCompletions, loadCalendar])

  const subjectOptions = useMemo(() => {
    const set = new Set()
    for (const ev of allHomework) {
      set.add(homeworkHeading(ev))
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [allHomework])

  const filtered = useMemo(() => {
    return allHomework.filter(ev => {
      if (subjectFilter !== FILTER_ALL) {
        if (homeworkHeading(ev) !== subjectFilter) return false
      }
      return true
    })
  }, [allHomework, subjectFilter])

  const activeList = useMemo(() => {
    if (!accountUser) return filtered
    return filtered.filter(ev => !completedIds.has(ev.id))
  }, [filtered, accountUser, completedIds])

  const doneList = useMemo(() => {
    if (!accountUser) return []
    return filtered.filter(ev => completedIds.has(ev.id))
  }, [filtered, accountUser, completedIds])

  const listForView = accountUser
    ? (hwTab === 'active' ? activeList : doneList)
    : filtered

  const events = useMemo(() => groupByDate(listForView), [listForView])

  async function markComplete(evId) {
    if (!accountUser) return
    setBusyId(evId)
    try {
      await axios.post(`/homework-completion/${evId}`)
      setCompletedIds(prev => {
        const n = new Set(prev)
        n.add(evId)
        return n
      })
    } catch (e) {
      console.error(e)
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setBusyId(null)
    }
  }

  async function markUncomplete(evId) {
    if (!accountUser) return
    setBusyId(evId)
    try {
      await axios.delete(`/homework-completion/${evId}`)
      setCompletedIds(prev => {
        const n = new Set(prev)
        n.delete(evId)
        return n
      })
    } catch (e) {
      console.error(e)
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="card">
      <h2>Домашние задания</h2>
      {accountUser ? (
        <div className="homework-mode-tabs" style={{ marginTop: 12 }}>
          <button
            type="button"
            className={hwTab === 'active' ? 'tab active' : 'tab'}
            onClick={() => setHwTab('active')}
          >
            К выполнению
          </button>
          <button
            type="button"
            className={hwTab === 'done' ? 'tab active' : 'tab'}
            onClick={() => setHwTab('done')}
          >
            Завершённые
          </button>
        </div>
      ) : null}
      <div className="homework-filters form-grid" style={{ marginTop: 12, marginBottom: 8 }}>
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
      {!loading && !error && listForView.length === 0 && (
        <div className="status" style={{ marginTop: 8 }}>
          {accountUser && hwTab === 'done'
            ? 'Нет завершённых заданий по фильтрам.'
            : 'Нет заданий по выбранным фильтрам.'}
        </div>
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
                {(ev.semester || '').trim() ? (
                  <div className="homework-semester">{normalizeSemesterLabel(ev.semester)}</div>
                ) : null}
                <FormattedBody html={ev.body} className="homework-body" />
                {accountUser ? (
                  <div className="homework-item-actions">
                    {hwTab === 'active' ? (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={busyId === ev.id}
                        onClick={() => markComplete(ev.id)}
                      >
                        Выполнено
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busyId === ev.id}
                        onClick={() => markUncomplete(ev.id)}
                      >
                        Вернуть в активные
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
