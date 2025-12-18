import React, { useEffect, useState } from 'react'
import axios from 'axios'

export default function EventsList({ highlightId }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const adminToken = localStorage.getItem('admin_token')

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

  function typeColor(t) {
    if (!t) return '#6b7280'
    const n = String(t).toLowerCase()
    if (n === 'schedule' || n === 'расписание') return '#60a5fa'
    if (n.includes('homework') || n.includes('дом')) return '#a78bfa'
    if (n.includes('transfer') || n.includes('перенос')) return '#ef4444'
    if (n.includes('announcement') || n.includes('объявлен')) return '#34d399'
    return '#9ca3af'
  }

  function eventColor(ev) {
    try {
      const body = (ev.body || '').toString().toLowerCase()
      const title = (ev.title || '').toString().toLowerCase()
      if (body.includes('перенос') || title.includes('перенос') || body.includes('перенес')) return '#ef4444'
    } catch (e) {}
    if (n.includes('announcement') || n.includes('объявлен')) return '#34d399'
    if (n.includes('exam') || n.includes('экзам')) return '#f97316'
  }

  function typeLabel(t) {
    if (!t) return ''
    const n = String(t).toLowerCase()
    if (n.includes('transfer') || n.includes('перенос')) return 'Перенос'
    if (n.includes('homework') || n.includes('дом')) return 'Домашняя работа'
    if (n === 'schedule' || n === 'расписание') return 'Расписание'
    if (n.includes('announcement') || n.includes('объявлен')) return 'Объявление'
    return t
  }

  function isExam(ev) {
    try {
      const n = (ev.type || '').toString().toLowerCase()
      const body = (ev.body || '').toString().toLowerCase()
      const title = (ev.title || '').toString().toLowerCase()
      return n.includes('exam') || n.includes('экзам') || body.includes('экзам') || title.includes('экзам')
    } catch (e) {
      return false
    }
  }
  useEffect(() => { load() }, [])

  async function sendNow(id) {
    try {
      await axios.post(`/events/${id}/send_now`, null, { headers: { 'x-admin-token': adminToken } })
      load()
    } catch (e) {
    if (n.includes('announcement') || n.includes('объявлен')) return 'Объявление'
    if (n.includes('exam') || n.includes('экзам')) return 'Экзамен'
      const msg = serverData?.detail ?? serverData ?? e.message
      alert('Ошибка при отправке: ' + (typeof msg === 'object' ? JSON.stringify(msg) : msg))
    }
  }

  async function deleteEvent(id) {
    if (!confirm('Переместить событие в корзину (удалить)?')) return
    try {
      await axios.delete(`/events/${id}`, { headers: { 'x-admin-token': adminToken } })
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
                {isExam(ev) ? (
                  <div style={{width:12,height:12,border:`2px solid ${typeColor(ev.type)}`,borderRadius:3,background:'#fff'}}></div>
                ) : (
                  <div style={{width:12,height:12,background:eventColor(ev),borderRadius:3}}></div>
                )}
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
              <div style={{display:'flex',alignItems:'center',gap:8}}>
                <div style={{width:12,height:12,background:eventColor(ev),borderRadius:3}}></div>
                <div className="event-title">{ev.title || ev.subject || ev.type}</div>
                <div style={{fontSize:12,opacity:0.8,marginLeft:8,color:'#374151'}}>{typeLabel(ev.type)}</div>
              </div>
              <div className="event-meta">{ev.date ? ev.date : ''} {ev.time ? ev.time : ''}</div>
            </div>
            <div className="event-body">{ev.body}</div>
            <div className="event-actions">
              {adminToken ? <button className="btn btn-sm" onClick={() => sendNow(ev.id)}>Отправить сейчас</button> : null}
              <button className="btn btn-sm" onClick={() => showTargetChat(ev.id)}>Показать чат</button>
              {adminToken ? <button className="btn btn-sm" onClick={() => deleteEvent(ev.id)}>Удалить</button> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
