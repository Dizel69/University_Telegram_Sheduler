import React, { useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { bearerAuthHeaders } from './authHeaders'
import { isCompletedEvent, parseEventBoundary } from './eventTime'
import { FormattedBody } from './FormattedTextEditor'

export default function EventsList({ highlightId, isAdmin = false }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [eventsTab, setEventsTab] = useState('current')
  const [backingUp, setBackingUp] = useState(false)

  function eventSortValue(ev) {
    const boundary = parseEventBoundary(ev)
    return boundary ? boundary.getTime() : Number.MAX_SAFE_INTEGER
  }

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
    if (n.includes('exam_control') || n.includes('контрольн') || n.includes('экзамен')) return '#f97316'
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
    return typeColor(ev.type)
  }

  function typeLabel(t) {
    if (!t) return ''
    const n = String(t).toLowerCase()
    if (n.includes('transfer') || n.includes('перенос')) return 'Перенос'
    if (n.includes('homework') || n.includes('дом')) return 'Домашняя работа'
    if (n.includes('exam_control') || n.includes('контрольн') || n.includes('экзамен')) return 'Контрольная / экзамен'
    if (n === 'schedule' || n === 'расписание') return 'Расписание'
    if (n.includes('announcement') || n.includes('объявлен')) return 'Объявление'
    return t
  }

  useEffect(() => { load() }, [])

  const { currentEvents, completedEvents } = useMemo(() => {
    const current = []
    const completed = []
    for (const ev of events) {
      if (isCompletedEvent(ev)) completed.push(ev)
      else current.push(ev)
    }
    current.sort((a, b) => eventSortValue(a) - eventSortValue(b))
    completed.sort((a, b) => eventSortValue(b) - eventSortValue(a))
    return { currentEvents: current, completedEvents: completed }
  }, [events])

  const visibleEvents = eventsTab === 'completed' ? completedEvents : currentEvents

  async function sendNow(id) {
    try {
      await axios.post(`/events/${id}/send_now`, null, { headers: bearerAuthHeaders() })
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
      await axios.delete(`/events/${id}`, { headers: bearerAuthHeaders() })
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

  async function createBackup() {
    if (!isAdmin) return
    if (!confirm('Создать бэкап базы данных сейчас? (хранятся только 2 последних файла)')) return
    setBackingUp(true)
    try {
      const res = await axios.post('/admin/backup', null, { headers: bearerAuthHeaders() })
      const name = res.data?.filename || 'готово'
      const kept = Array.isArray(res.data?.kept) ? res.data.kept.join(', ') : ''
      alert(`Бэкап создан: ${name}${kept ? `\nСейчас в папке: ${kept}` : ''}`)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      alert('Ошибка бэкапа: ' + (typeof msg === 'object' ? JSON.stringify(msg) : msg))
    } finally {
      setBackingUp(false)
    }
  }

  return (
    <div className="card">
      <div className="list-header">
        <h3>События</h3>
        <div className="list-header-actions">
          {isAdmin ? (
            <button className="btn" onClick={createBackup} disabled={backingUp}>
              {backingUp ? 'Бэкап…' : 'Бэкап 🤡'}
            </button>
          ) : null}
          <button className="btn" onClick={load}>Обновить</button>
        </div>
      </div>

      {loading && <div>Загрузка...</div>}
      {error && <div className="error">Ошибка: {error}</div>}

      {!loading && !events.length && <div>Событий нет.</div>}

      {!loading && events.length > 0 && (
        <div className="events-mode-tabs">
          <button
            type="button"
            className={eventsTab === 'current' ? 'tab active' : 'tab'}
            onClick={() => setEventsTab('current')}
          >
            Текущие ({currentEvents.length})
          </button>
          <button
            type="button"
            className={eventsTab === 'completed' ? 'tab active' : 'tab'}
            onClick={() => setEventsTab('completed')}
          >
            Завершенные ({completedEvents.length})
          </button>
        </div>
      )}

      {!loading && events.length > 0 && visibleEvents.length === 0 && (
        <div className="status">
          {eventsTab === 'completed' ? 'Завершенных событий нет.' : 'Текущих событий нет.'}
        </div>
      )}

      <div className="events-grid">
        {visibleEvents.map(ev => (
          <div key={ev.id} className={"event-card" + (highlightId===ev.id ? ' highlight':'' )}>
            <div className="event-row">
              <div style={{display:'flex',alignItems:'center',gap:8}}>
                <div style={{width:12,height:12,background:eventColor(ev),borderRadius:3}}></div>
                <div className="event-title">{ev.title || ev.subject || ev.type}</div>
                <div className="legend-label" style={{fontSize:12,opacity:0.8,marginLeft:8}}>{typeLabel(ev.type)}</div>
              </div>
              <div className="event-meta">{ev.date ? ev.date : ''} {ev.time ? ev.time : ''}</div>
            </div>
            <FormattedBody html={ev.body} className="event-body" />
            <div className="event-actions">
              {isAdmin ? <button className="btn btn-sm" onClick={() => sendNow(ev.id)}>Отправить сейчас</button> : null}
              <button className="btn btn-sm" onClick={() => showTargetChat(ev.id)}>Показать чат</button>
              {isAdmin ? <button className="btn btn-sm" onClick={() => deleteEvent(ev.id)}>Удалить</button> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
