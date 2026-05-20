import React, { useCallback, useEffect, useState } from 'react'
import axios from 'axios'

function todayYmd() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function userLabel(u) {
  const parts = [u.last_name, u.first_name]
  if (u.middle_name) parts.push(u.middle_name)
  return parts.filter(Boolean).join(' ')
}

function markKey(userId, subject) {
  return `${userId}\0${subject}`
}

export default function AttendanceAdmin() {
  const [date, setDate] = useState(todayYmd)
  const [users, setUsers] = useState([])
  const [subjects, setSubjects] = useState([])
  const [marks, setMarks] = useState(() => new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')
  const [busyKey, setBusyKey] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setStatus('')
    try {
      const { data } = await axios.get('/admin/attendance', { params: { date } })
      setUsers(Array.isArray(data.users) ? data.users : [])
      setSubjects(Array.isArray(data.subjects) ? data.subjects : [])
      const next = new Map()
      for (const m of data.marks || []) {
        next.set(markKey(m.user_id, m.subject), m.mark)
      }
      setMarks(next)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [date])

  useEffect(() => {
    load()
  }, [load])

  async function setMark(userId, subject, nextMark) {
    const key = markKey(userId, subject)
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
        date,
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

  function toggleMark(userId, subject, kind) {
    const key = markKey(userId, subject)
    const current = marks.get(key) || null
    if (current === kind) {
      setMark(userId, subject, null)
    } else {
      setMark(userId, subject, kind)
    }
  }

  return (
    <div className="card attendance-card">
      <h2>Посещаемость</h2>
      <p className="status" style={{ marginTop: 4 }}>
        Строки — пользователи, столбцы — предметы из расписания. Отметки сохраняются по выбранной дате.
      </p>

      <div className="attendance-toolbar">
        <div>
          <label className="label">Дата</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>
        <button type="button" className="btn" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      <div className="attendance-legend">
        <span><strong>Н</strong> — отсутствовал</span>
        <span><strong>Б</strong> — болеет</span>
        <span className="status">Пустая ячейка — присутствовал</span>
      </div>

      {loading && <div style={{ marginTop: 12 }}>Загрузка…</div>}
      {error && <div className="error" style={{ marginTop: 12 }}>{String(error)}</div>}
      {status && <div className="status" style={{ marginTop: 12 }}>{status}</div>}

      {!loading && !error && subjects.length === 0 && (
        <p className="status" style={{ marginTop: 16 }}>
          Нет предметов в расписании. Добавьте занятия в календаре — они появятся здесь как столбцы.
        </p>
      )}

      {!loading && !error && subjects.length > 0 && (
        <div className="attendance-table-wrap">
          <table className="attendance-table">
            <thead>
              <tr>
                <th className="attendance-sticky-col">Студент</th>
                {subjects.map(s => (
                  <th key={s} title={s}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <th className="attendance-sticky-col attendance-user-name" scope="row">
                    {userLabel(u)}
                  </th>
                  {subjects.map(subject => {
                    const key = markKey(u.id, subject)
                    const current = marks.get(key) || null
                    const busy = busyKey === key
                    return (
                      <td key={subject} className={busy ? 'attendance-cell-busy' : ''}>
                        <div className="attendance-cell">
                          <button
                            type="button"
                            className={`attendance-mark-btn${current === 'N' ? ' active-n' : ''}`}
                            disabled={busy}
                            onClick={() => toggleMark(u.id, subject, 'N')}
                            title="Отсутствовал"
                          >
                            Н
                          </button>
                          <button
                            type="button"
                            className={`attendance-mark-btn${current === 'B' ? ' active-b' : ''}`}
                            disabled={busy}
                            onClick={() => toggleMark(u.id, subject, 'B')}
                            title="Болеет"
                          >
                            Б
                          </button>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && subjects.length > 0 && users.length === 0 && (
        <p className="status" style={{ marginTop: 16 }}>Нет пользователей для отображения.</p>
      )}
    </div>
  )
}
