import React, { useEffect, useState } from 'react'
import axios from 'axios'

function backendBase() {
  const host = import.meta.env.VITE_HOST || window.location.hostname
  return `http://${host}:8000`
}

export default function HomeworkList() {
  const [events, setEvents] = useState([])
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
      setEvents(hw)
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
      <ul>
        {events.map(ev => (
          <li key={ev.id}>
            {ev.date && <span>{ev.date} — </span>}
            {ev.title || ev.subject || '<без названия>'}
            {ev.body && `: ${ev.body}`}
          </li>
        ))}
      </ul>
    </div>
  )
}
