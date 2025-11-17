import React, { useEffect, useState } from 'react'
import axios from 'axios'

export default function EventsList({ highlightId }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  async function load() {
    setLoading(true)
    try {
  const res = await axios.get('/events')
  // hide events created manually via calendar UI (source === 'manual')
  const list = (res.data || []).filter(ev => ev.source !== 'manual')
  setEvents(list)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function sendNow(id) {
    try {
      await axios.post(`/events/${id}/send_now`)
      load()
    } catch (e) {
      const serverData = e.response?.data
      const msg = serverData?.detail ?? serverData ?? e.message
      alert('Ошибка при отправке: ' + (typeof msg === 'object' ? JSON.stringify(msg) : msg))
    }
  }

  async function deleteEvent(id) {
    if (!confirm('Переместить событие в корзину (удалить)?')) return
    try {
      await axios.delete(`/events/${id}`)
      load()
    } catch (e) {
      alert('Ошибка удаления: ' + (e.response?.data?.detail || e.message))
    }
  }

  async function showTargetChat(id) {
    try {
      const res = await axios.get(`/events/${id}/resolve_chat`)
      alert(`Тип: ${res.data.type}\nchat_id: ${res.data.chat_id}\nthread_id: ${res.data.thread_id}`)
    } catch (e) {
      alert('Не удалось определить чат: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div className="card">
      <div className="list-header">
        <h3>События</h3>
        <button className="btn" onClick={load}>Обновить</button>
      </div>

      {loading && <div>Загрузка...</div>}
      {error && <div className="error">Ошибка: {error}</div>}

      {!loading && !events.length && <div>Событий нет.</div>}

      <div className="events-grid">
        {events.map(ev => (
          <div key={ev.id} className={"event-card" + (highlightId===ev.id ? ' highlight':'' )}>
            <div className="event-row">
              <div className="event-title">{ev.title || ev.subject || ev.type}</div>
              <div className="event-meta">{ev.date ? ev.date : ''} {ev.time ? ev.time : ''}</div>
            </div>
            <div className="event-body">{ev.body}</div>
            <div className="event-actions">
              <button className="btn btn-sm" onClick={() => sendNow(ev.id)}>Отправить сейчас</button>
              <button className="btn btn-sm" onClick={() => showTargetChat(ev.id)}>Показать чат</button>
              <button className="btn btn-sm" onClick={() => deleteEvent(ev.id)}>Удалить</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
