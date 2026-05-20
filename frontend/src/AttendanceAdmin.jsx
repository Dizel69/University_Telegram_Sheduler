import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react'
import axios from 'axios'

/** Локальная дата в YYYY-MM-DD (без UTC-сдвига). */
function ymdFromDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Понедельник ISO-недели для локальной даты. */
function mondayOfWeekContaining(ymdOrDate) {
  let d
  if (typeof ymdOrDate === 'string') {
    const [y, m, day] = ymdOrDate.split('-').map(Number)
    d = new Date(y, m - 1, day)
  } else {
    d = new Date(ymdOrDate)
  }
  const fromMon = (d.getDay() + 6) % 7
  const mon = new Date(d)
  mon.setDate(d.getDate() - fromMon)
  return mon
}

function ymdToday() {
  return ymdFromDate(new Date())
}

function formatDdMm(ymd) {
  if (!ymd) return ''
  const [y, m, d] = ymd.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  return `${String(dt.getDate()).padStart(2, '0')}.${String(dt.getMonth() + 1).padStart(2, '0')}`
}

function weekdayShortRu(ymd) {
  const [y, m, d] = ymd.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  const monIdx = (dt.getDay() + 6) % 7
  const names = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
  return names[monIdx]
}

function addDaysYmd(ymd, delta) {
  const [y, m, d] = ymd.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + delta)
  return ymdFromDate(dt)
}

function userLabel(u) {
  const parts = [u.last_name, u.first_name]
  if (u.middle_name) parts.push(u.middle_name)
  const base = parts.filter(Boolean).join(' ')
  if (u.is_admin && !u.is_owner) return `${base} (админ)`
  return base
}

function markKey(userId, dateStr, subject) {
  return `${userId}\0${dateStr}\0${subject}`
}

function countWeekMarks(userId, markMap) {
  let absent = 0
  let sick = 0
  const prefix = `${userId}\0`
  for (const [k, v] of markMap.entries()) {
    if (!k.startsWith(prefix)) continue
    if (v === 'N') absent++
    if (v === 'B') sick++
  }
  return { absent, sick }
}

function AttendanceMarkCell({
  cellKey,
  current,
  busy,
  menuOpen,
  onToggleMenu,
  onPick,
}) {
  const wrapRef = useRef(null)

  const hasMenu = menuOpen === cellKey

  useEffect(() => {
    if (!hasMenu) return
    function onDocDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        onToggleMenu(null)
      }
    }
    document.addEventListener('mousedown', onDocDown)
    return () => document.removeEventListener('mousedown', onDocDown)
  }, [hasMenu, onToggleMenu])

  return (
    <div className="attendance-dropdown-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`attendance-cell-trigger${current === 'N' ? ' attendance-cell-trigger-n' : ''}${current === 'B' ? ' attendance-cell-trigger-b' : ''}`}
        disabled={busy}
        onClick={e => {
          e.stopPropagation()
          onToggleMenu(hasMenu ? null : cellKey)
        }}
        title="Нажмите, чтобы выбрать отметку"
      >
        {current === 'N' ? 'Н' : current === 'B' ? 'Б' : '\u00a0'}
      </button>
      {hasMenu && (
        <ul className="attendance-dropdown-menu" role="menu">
          <li>
            <button type="button" className="attendance-dropdown-item" onClick={() => onPick(null)} role="menuitem">
              Нет отметки
            </button>
          </li>
          <li>
            <button type="button" className="attendance-dropdown-item" onClick={() => onPick('N')} role="menuitem">
              Н — неуважительная причина
            </button>
          </li>
          <li>
            <button type="button" className="attendance-dropdown-item" onClick={() => onPick('B')} role="menuitem">
              Б — по болезни
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}

export default function AttendanceAdmin() {
  const [weekMonday, setWeekMonday] = useState(() => ymdFromDate(mondayOfWeekContaining(ymdToday())))
  const [days, setDays] = useState([])
  const [users, setUsers] = useState([])
  const [marks, setMarks] = useState(() => new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')
  const [busyKey, setBusyKey] = useState(null)
  const [menuOpenKey, setMenuOpenKey] = useState(null)

  const weekEndYmd = useMemo(() => addDaysYmd(weekMonday, 6), [weekMonday])
  const weekRangeLabel = useMemo(
    () => `${formatDdMm(weekMonday)}–${formatDdMm(weekEndYmd)}`,
    [weekMonday, weekEndYmd],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setStatus('')
    setMenuOpenKey(null)
    try {
      const { data } = await axios.get('/admin/attendance', { params: { week_start: weekMonday } })
      setUsers(Array.isArray(data.users) ? data.users : [])
      setDays(Array.isArray(data.days) ? data.days : [])
      const next = new Map()
      for (const m of data.marks || []) {
        const ds = typeof m.date === 'string' ? m.date.slice(0, 10) : m.date
        next.set(markKey(m.user_id, ds, m.subject), m.mark)
      }
      setMarks(next)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [weekMonday])

  useEffect(() => {
    load()
  }, [load])

  function goPrevWeek() {
    setWeekMonday(w => addDaysYmd(w, -7))
  }

  function goNextWeek() {
    setWeekMonday(w => addDaysYmd(w, 7))
  }

  async function setMark(userId, dateStr, subject, nextMark) {
    const key = markKey(userId, dateStr, subject)
    const prev = marks.get(key) || null
    setBusyKey(key)
    setStatus('')
    setMarks(prevMap => {
      const copy = new Map(prevMap)
      if (nextMark) copy.set(key, nextMark)
      else copy.delete(key)
      return copy
    })
    try {
      await axios.put('/admin/attendance', {
        user_id: userId,
        subject,
        date: dateStr,
        mark: nextMark,
      })
    } catch (e) {
      setMarks(prevMap => {
        const copy = new Map(prevMap)
        if (prev) copy.set(key, prev)
        else copy.delete(key)
        return copy
      })
      setStatus(e.response?.data?.detail || e.message || String(e))
    } finally {
      setBusyKey(null)
    }
  }

  function handlePick(userId, dateStr, subject, value) {
    setMenuOpenKey(null)
    setMark(userId, dateStr, subject, value)
  }

  return (
    <div className="card attendance-card">
      <h2>Посещаемость</h2>
      <p className="status" style={{ marginTop: 4 }}>
        Неделя с понедельника по воскресенье. Учётка <strong>владельца</strong> в списке не отображается; остальные
        администраторы — как и студенты. Нажмите ячейку, чтобы выбрать <strong>Н</strong> или <strong>Б</strong>.
      </p>

      <div className="attendance-week-nav" role="group" aria-label="Выбор недели">
        <button type="button" className="btn attendance-week-arrow" onClick={goPrevWeek} disabled={loading}>
          ←
        </button>
        <span className="attendance-week-range">{weekRangeLabel}</span>
        <button type="button" className="btn attendance-week-arrow" onClick={goNextWeek} disabled={loading}>
          →
        </button>
      </div>

      <div className="attendance-toolbar attendance-toolbar-row">
        <button type="button" className="btn btn-sm" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      <div className="attendance-legend">
        <span><strong>Н</strong> — неуважительная причина</span>
        <span><strong>Б</strong> — по болезни</span>
        <span className="status">Пустая ячейка — без отметки (считается присутствие или сброс через меню)</span>
      </div>

      {loading && <div style={{ marginTop: 12 }}>Загрузка…</div>}
      {error && <div className="error" style={{ marginTop: 12 }}>{String(error)}</div>}
      {status && <div className="status" style={{ marginTop: 12 }}>{status}</div>}

      {!loading && !error && days.length > 0 && !days.some(d => (d.subjects || []).length > 0) && (
        <p className="status" style={{ marginTop: 12 }}>
          На выбранной неделе в календаре нет занятий — ниже сетка по дням; столбцы заполнятся после добавления расписания.
        </p>
      )}

      {!loading && !error && days.length > 0 && (
        <div className="attendance-table-wrap">
          <table className="attendance-table attendance-table-weekly">
            <thead>
              <tr>
                <th rowSpan={2} className="attendance-sticky-col">Студент</th>
                {days.map(day => {
                  const dateStr = typeof day.date === 'string' ? day.date.slice(0, 10) : day.date
                  const subs = day.subjects || []
                  const colSpan = Math.max(1, subs.length)
                  return (
                    <th key={dateStr} colSpan={colSpan} className="attendance-day-head">
                      <div className="attendance-day-weekday">{weekdayShortRu(dateStr)}</div>
                      <div className="attendance-day-num">{formatDdMm(dateStr)}</div>
                    </th>
                  )
                })}
                <th colSpan={2} rowSpan={1} className="attendance-summary-group head">Отсутствие за неделю</th>
              </tr>
              <tr>
                {days.flatMap(day => {
                  const dateStr = typeof day.date === 'string' ? day.date.slice(0, 10) : day.date
                  const subs = day.subjects || []
                  if (subs.length === 0) {
                    return [
                      <th key={`${dateStr}-empty`} className="attendance-no-lessons">Нет пар</th>,
                    ]
                  }
                  return subs.map(s => (
                    <th key={`${dateStr}-${s}`} title={s}>{s}</th>
                  ))
                })}
                <th className="attendance-summary-sub">По болезни</th>
                <th className="attendance-summary-sub">Неуважительная причина</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => {
                const { absent, sick } = countWeekMarks(u.id, marks)
                return (
                  <tr key={u.id}>
                    <th className="attendance-sticky-col attendance-user-name" scope="row">
                      {userLabel(u)}
                    </th>
                    {days.flatMap(day => {
                      const dateStr = typeof day.date === 'string' ? day.date.slice(0, 10) : day.date
                      const subs = day.subjects || []
                      if (subs.length === 0) {
                        return [
                          <td key={`${u.id}-${dateStr}-empty`} className="attendance-no-lessons">—</td>,
                        ]
                      }
                      return subs.map(subject => {
                        const key = markKey(u.id, dateStr, subject)
                        const current = marks.get(key) || null
                        const busy = busyKey === key
                        return (
                          <td key={key} className={busy ? 'attendance-cell-busy' : ''}>
                            <AttendanceMarkCell
                              cellKey={key}
                              current={current}
                              busy={busy}
                              menuOpen={menuOpenKey}
                              onToggleMenu={setMenuOpenKey}
                              onPick={v => handlePick(u.id, dateStr, subject, v)}
                            />
                          </td>
                        )
                      })
                    })}
                    <td className="attendance-summary-cell">{sick}</td>
                    <td className="attendance-summary-cell">{absent}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && days.length > 0 && users.length === 0 && (
        <p className="status" style={{ marginTop: 16 }}>Нет пользователей для отображения (кроме владельца).</p>
      )}
    </div>
  )
}
