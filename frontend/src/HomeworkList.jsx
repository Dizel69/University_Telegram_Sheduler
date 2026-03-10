import React, { useEffect, useState } from 'react'
import axios from 'axios'

function backendBase() {
  const host = import.meta.env.VITE_HOST || window.location.hostname
  return `http://${host}:8000`
}

function formatDate(dateStr) {
  if (!dateStr || dateStr === 'Без даты') return dateStr
  const date = new Date(dateStr)
  const options = { day: 'numeric', month: 'long', year: 'numeric', weekday: 'long' }
  const formatted = date.toLocaleDateString('ru-RU', options)
  // "1 апреля 2026 г., среда" -> "1 апреля 2026, Среда"
  const parts = formatted.split(', ')
  if (parts.length === 2) {
    const datePart = parts[0].replace(' г.', '')
    const weekdayPart = parts[1].charAt(0).toUpperCase() + parts[1].slice(1)
    return `${datePart}, ${weekdayPart}`
  }
  return formatted
}

export default function HomeworkList() {
  const [events, setEvents] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(backendBase() + '/calendar?type=homework')
      let hw = res.data
      // if backend didn't support ?type parameter (older version) it may return all events
      if (!Array.isArray(hw)) hw = []
      if (hw.length === 0) {
        // try fetching everything and filtering client-side as a fallback
        const all = await axios.get(backendBase() + '/calendar')
        hw = (all.data || []).filter(ev => ev.type === 'homework')
      }
      hw.sort((a,b) => {
        if (!a.date) return 1
        if (!b.date) return -1
        return a.date.localeCompare(b.date)
      })
      // Group by date
      const grouped = {}
      for (const ev of hw) {
        const date = ev.date || 'Без даты'
        if (!grouped[date]) grouped[date] = []
        grouped[date].push(ev)
      }
      setEvents(grouped)
    } catch (e) {
      console.error(e)
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card">
      <h2>Домашние задания</h2>
      {loading && <div>Загрузка...</div>}
      {error && <div className="error">Ошибка: {error}</div>}
      {Object.keys(events).sort((a,b) => {
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
                <div className="homework-subject">{ev.title || ev.subject || '<без названия>'}</div>
                <div className="homework-body">{ev.body}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
