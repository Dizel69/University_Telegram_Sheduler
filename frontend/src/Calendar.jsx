import React, { useEffect, useState } from 'react'
import axios from 'axios'

function monthBounds(year, month) {
  // month: 0-11. return first and last date objects in UTC
  const first = new Date(Date.UTC(year, month, 1))
  const last = new Date(Date.UTC(year, month + 1, 0))
  return { first, last }
}

function monthLabel(year, month) {
  return new Intl.DateTimeFormat('ru-RU', { year: 'numeric', month: 'long' }).format(new Date(Date.UTC(year, month, 1)))
}

export default function Calendar() {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [events, setEvents] = useState({})
  const [undated, setUndated] = useState([])
  const [editing, setEditing] = useState(false)
  const [addDate, setAddDate] = useState(null) // 'YYYY-MM-DD' for add-event modal
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const [importing, setImporting] = useState(false)
  const [preview, setPreview] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [openDay, setOpenDay] = useState(null) // 'YYYY-MM-DD' or null
  const [transferEvent, setTransferEvent] = useState(null)

  useEffect(() => { load() }, [year, month])

  function backendBase() {
    // prefer direct localhost:8000 to avoid Vite proxy DNS issues when developing locally
    const h = window.location.hostname
    if (h === 'localhost' || h === '127.0.0.1') return 'http://127.0.0.1:8000'
    return ''
  }

  function parserBase() {
    const h = window.location.hostname
    if (h === 'localhost' || h === '127.0.0.1') return 'http://127.0.0.1:8090'
    return 'http://localhost:8090'
  }

  async function load() {
    setLoading(true)
    setLoadError(null)
    try {
      const { first, last } = monthBounds(year, month)
      const start = first.toISOString().slice(0,10)
      const end = last.toISOString().slice(0,10)
  const base = backendBase()
  const url = (base || '') + `/calendar?start=${start}&end=${end}`
  const res = await axios.get(url)
      const map = {}
      const und = []
      for (const ev of res.data) {
        if (!ev.date) { und.push(ev); continue }
        if (!map[ev.date]) map[ev.date] = []
        map[ev.date].push(ev)
      }
      // sort events per day: homeworks always on top, then by time (nulls last)
      for (const k of Object.keys(map)) {
        map[k].sort((a,b) => {
          if (a.type === 'homework' && b.type !== 'homework') return -1
          if (b.type === 'homework' && a.type !== 'homework') return 1
          const ta = a.time || ''
          const tb = b.time || ''
          if (!ta && !tb) return 0
          if (!ta) return 1
          if (!tb) return -1
          return ta.localeCompare(tb)
        })
      }
      setEvents(map)
      setUndated(und)
    } catch (e) {
      console.error(e)
      const msg = e.response?.data?.detail || e.message || String(e)
      setLoadError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleFile(file) {
    if (!file) return
    setImporting(true)
    setPreview([])
    try {
      const fd = new FormData()
      fd.append('file', file, file.name)
      // parser service is exposed on host:8090
  const pbase = parserBase()
  const res = await fetch(pbase + '/upload_pdf', { method: 'POST', body: fd })
      if (!res.ok) throw new Error('parser error: ' + res.status)
      const data = await res.json()
      setPreview(data.preview || [])
      setSelected(new Set())
    } catch (e) {
      console.error(e)
      alert('Ошибка парсинга PDF: ' + e.message)
    } finally {
      setImporting(false)
    }
  }

  function toggleSelect(idx) {
    const s = new Set(selected)
    if (s.has(idx)) s.delete(idx)
    else s.add(idx)
    setSelected(s)
  }

  async function importSelected() {
    if (!preview.length) return
    const items = []
    for (const idx of Array.from(selected)) {
      const it = preview[idx]
      items.push({ page: it.page, raw: it.raw, type: it.type, start: it.start, end: it.end, date: it.date, images: it.images })
    }
    if (!items.length) { alert('Ничего не выбрано'); return }
    try {
      const resp = await fetch('/events/import', { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(items) })
      if (!resp.ok) throw new Error('import failed: ' + resp.status)
      const j = await resp.json()
      alert('Импортировано: ' + j.count)
      setPreview([])
      setSelected(new Set())
      load()
    } catch (e) {
      console.error(e)
      alert('Ошибка импорта: ' + e.message)
    }
  }

  function prev() {
    const d = new Date(Date.UTC(year, month-1, 1))
    setYear(d.getUTCFullYear())
    setMonth(d.getUTCMonth())
  }
  function next() {
    const d = new Date(Date.UTC(year, month+1, 1))
    setYear(d.getUTCFullYear())
    setMonth(d.getUTCMonth())
  }

  function goToday() {
    const t = new Date()
    setYear(t.getFullYear())
    setMonth(t.getMonth())
  }

  // build days array with Monday-first week (Mon..Sun)
  const days = []
  const d0 = new Date(Date.UTC(year, month, 1))
  const startWeekday = d0.getUTCDay() // 0 Sun, 1 Mon ...
  // convert to Monday-first offset: make Monday=0 ... Sunday=6
  const offset = (startWeekday + 6) % 7
  const daysInMonth = new Date(Date.UTC(year, month+1, 0)).getUTCDate()

  for (let i=0;i<offset;i++) days.push(null)
  for (let d=1; d<=daysInMonth; d++) days.push(new Date(Date.UTC(year, month, d)))

  async function deleteEventsForDay(day) {
    if (!confirm('Удалить все события за день? Это действие нельзя отменить.')) return
    try {
      const resp = await fetch(`/events/day?date=${day}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('delete failed: ' + resp.status)
      const j = await resp.json()
      alert('Удалено: ' + j.deleted)
      setOpenDay(null)
      load()
    } catch (e) {
      console.error(e)
      alert('Ошибка удаления: ' + e.message)
    }
  }

  async function deleteEventsForMonth() {
    if (!confirm('Удалить все события за отображаемый месяц? Это действие нельзя отменить.')) return
    try {
      const resp = await fetch(`/events/month?year=${year}&month=${month+1}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('delete failed: ' + resp.status)
      const j = await resp.json()
      alert('Удалено: ' + j.deleted)
      // refresh calendar
      load()
    } catch (e) {
      console.error(e)
      alert('Ошибка удаления: ' + e.message)
    }
  }

  return (
    <div className="card">
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        <div>
          <button className="btn" onClick={prev}>◀</button>
          <button className="btn" onClick={goToday}>Today</button>
          <button className="btn" onClick={next}>▶</button>
        </div>
        <div style={{display:'flex',gap:8,alignItems:'center'}}>
          {/* Временно показываем кнопку редактирования всегда для удобства локальной разработки */}
          <button className={editing? 'btn btn-danger':'btn'} onClick={() => setEditing(!editing)}>{editing? 'Выход из ред.' : 'Редактировать'}</button>
          {editing && localStorage.getItem('admin_token') ? (
            <button className="btn btn-danger" onClick={deleteEventsForMonth}>Удалить все события за месяц</button>
          ) : null}
        </div>
        <h3>{monthLabel(year, month)}</h3>
        <div>{loading ? 'Загрузка...' : ''}</div>
      </div>
      {/* Legend explaining colors */}
      <div style={{display:'flex',justifyContent:'flex-end',gap:12,marginTop:8,marginBottom:6}}>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{width:12,height:12,background:'#ef4444',borderRadius:3,display:'inline-block'}}></span>
          <span style={{fontSize:13,color:'#374151'}}>Перенос</span>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{width:12,height:12,background:'#a78bfa',borderRadius:3,display:'inline-block'}}></span>
          <span style={{fontSize:13,color:'#374151'}}>Домашняя работа</span>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{width:12,height:12,background:'#60a5fa',borderRadius:3,display:'inline-block'}}></span>
          <span style={{fontSize:13,color:'#374151'}}>Расписание</span>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <span style={{width:12,height:12,background:'#34d399',borderRadius:3,display:'inline-block'}}></span>
          <span style={{fontSize:13,color:'#374151'}}>Объявление</span>
        </div>
      </div>
      {loadError && (
        <div className="card" style={{marginTop:12,borderLeft:'4px solid #ef4444',padding:12,background:'#fff8f8'}}>
          <div style={{fontWeight:700,color:'#b91c1c'}}>Не удалось загрузить события</div>
          <div style={{marginTop:6,color:'#374151',fontSize:13}}>Причина: {loadError}</div>
          <div style={{marginTop:8,fontSize:13,color:'#374151'}}>Проверьте доступность бэкенда или временно отключите VPN.</div>
          <div style={{marginTop:8,display:'flex',gap:8}}>
            <button className="btn" onClick={() => load()}>Повторить</button>
            <button className="btn" onClick={() => window.open('http://localhost:8000/calendar','_blank')}>Открыть /calendar</button>
          </div>
        </div>
      )}

      <div className="calendar-grid">
  <div className="weekday">Пн</div>
  <div className="weekday">Вт</div>
  <div className="weekday">Ср</div>
  <div className="weekday">Чт</div>
  <div className="weekday">Пт</div>
  <div className="weekday">Сб</div>
  <div className="weekday">Вс</div>

        {days.map((dt, idx) => {
          if (!dt) return <div key={idx} className="day empty"></div>
          const ds = dt.toISOString().slice(0,10)
          const evs = events[ds] || []
          return (
            <div key={idx} className="day" onClick={() => { if (editing) setAddDate(ds); else setOpenDay(ds) }} style={{cursor:'pointer'}}>
              <div className="date-num">{dt.getUTCDate()}</div>
              {evs.slice(0,3).map(ev => (
                <div key={ev.id} className="cal-ev" style={{display:'flex',gap:8,alignItems:'center',padding:4,marginTop:6,background: eventColor(ev),borderRadius:6,color:'#fff'}}>
                  <div style={{fontSize:11,opacity:0.9}}>{ev.time ? ev.time.slice(0,5) : ''}</div>
                  <div style={{flex:1,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{ev.title || ev.subject || ev.type}</div>
                  {/* delete button on mini-card (visible in edit mode) */}
                  {editing && (
                    <button className="btn btn-sm" onClick={async (e) => {
                      e.stopPropagation()
                      if (!confirm('Удалить событие? Это действие нельзя отменить.')) return
                      try {
                        await axios.delete(`/events/${ev.id}`)
                        // refresh calendar
                        await load()
                      } catch (err) {
                        console.error(err)
                        alert('Ошибка удаления: ' + (err.response?.data?.detail || err.message))
                      }
                    }} style={{marginLeft:8,background:'rgba(255,255,255,0.15)',border:'none',color:'#fff',padding:'2px 6px',borderRadius:4}}>✖</button>
                  )}
                </div>
              ))}
              {evs.length > 3 && <div style={{fontSize:12,color:'#6b7280'}}>+{evs.length-3} ещё</div>}
            </div>
          )
        })}
      </div>
      {/* Day detail modal/panel */}
      {openDay && (
        <div className="modal-overlay" onClick={() => setOpenDay(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{minWidth:360,maxWidth:680}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <h3>События за {openDay}</h3>
                <div style={{display:'flex',gap:8}}>
                  {localStorage.getItem('admin_token') ? (
                    <button className="btn btn-danger" onClick={() => deleteEventsForDay(openDay)}>Удалить все за день</button>
                  ) : null}
                  <button className="btn" onClick={() => setOpenDay(null)}>Закрыть</button>
                </div>
            </div>
            <div style={{marginTop:8}}>
              {(events[openDay] || []).length === 0 && <div>Событий нет.</div>}
              {(events[openDay] || []).map(ev => (
                <div key={ev.id} style={{padding:8,borderBottom:'1px solid #eef2ff'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:8}}>
                    <div style={{display:'flex',alignItems:'center',gap:8}}>
                      <div style={{background: eventColor(ev), color:'#fff', padding:'2px 8px', borderRadius:6, fontSize:12, fontWeight:700}}>{typeLabel(ev.type)}</div>
                      <div style={{fontWeight:700}}>{ev.title || ev.subject || ''}</div>
                    </div>
                    <div style={{fontSize:12,color:'#6b7280'}}>{ev.time ? ev.time.slice(0,5) : ''}</div>
                  </div>
                  <div style={{marginTop:6}}>{ev.body}</div>
                  <div style={{marginTop:8,display:'flex',gap:8}}>
                    {localStorage.getItem('admin_token') ? (
                      <button className="btn btn-sm" onClick={async () => {
                        try { await axios.post(`/events/${ev.id}/send_now`); alert('Отправлено'); load(); }
                        catch(e){ alert('Ошибка: ' + (e.response?.data?.detail || e.message)) }
                      }}>Отправить сейчас</button>
                    ) : null}
                    <button className="btn btn-sm" onClick={() => alert('Показать в календаре: ' + ev.id)}>Открыть</button>
                    <button className="btn btn-sm" onClick={() => setTransferEvent(ev)}>Перенести</button>
                    <button className="btn btn-sm" onClick={async () => {
                      if (!confirm('Удалить событие? Это действие нельзя отменить.')) return
                      try {
                        await axios.delete(`/events/${ev.id}`)
                        alert('Событие удалено')
                        // refresh calendar and close day view if no events remain
                        await load()
                        // if the day has no events afterwards, close the panel
                        if (!((events[openDay] || []).length)) setOpenDay(null)
                      } catch (e) {
                        console.error(e)
                        alert('Ошибка удаления: ' + (e.response?.data?.detail || e.message))
                      }
                    }}>Удалить</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
        {/* Undated events (imported but without date) */}
        {undated.length > 0 && (
          <div className="card" style={{marginTop:12}}>
            <h4>События без даты ({undated.length})</h4>
            <div style={{display:'grid',gap:8}}>
              {undated.map(ev => (
                <div key={ev.id} style={{padding:8,border:'1px solid #eef2ff',borderRadius:6,display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:700}}>{ev.title || ev.subject || ev.type}</div>
                    <div style={{fontSize:13,color:'#374151',marginTop:6}}>{(ev.body || '').slice(0,240)}</div>
                  </div>
                  <div style={{marginLeft:12,display:'flex',flexDirection:'column',gap:6}}>
                    <button className="btn btn-sm" onClick={() => window.open(`${window.location.origin}/calendar/m15/event/${ev.id}`,'_blank')}>Открыть</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      <div style={{marginTop:12}}>
        {localStorage.getItem('admin_token') ? (
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <label className="btn">Импорт PDF<input type="file" accept=".pdf" style={{display:'none'}} onChange={e => handleFile(e.target.files[0])} /></label>
            {importing && <span>Парсинг...</span>}
            {preview.length > 0 && <button className="btn" onClick={importSelected}>Импортировать выбранные ({selected.size})</button>}
          </div>
        ) : (
          <div style={{color:'#6b7280',fontSize:13}}>Войдите как староста, чтобы импортировать PDF</div>
        )}
      </div>

      {preview.length > 0 && (
        <div style={{marginTop:12}} className="card">
          <h4>Предпросмотр парсинга ({preview.length})</h4>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:8}}>
            {preview.map((p, idx) => (
              <div key={idx} style={{border:'1px solid #eef2ff',padding:8,borderRadius:8}}>
                <div style={{display:'flex',justifyContent:'space-between'}}>
                  <div style={{fontSize:12,color:'#6b7280'}}>Стр. {p.page} • {p.type || '—'}</div>
                  <input type="checkbox" checked={selected.has(idx)} onChange={() => toggleSelect(idx)} />
                </div>
                <div style={{fontWeight:700,marginTop:6}}>{p.raw.split('\n')[0]}</div>
                <div style={{fontSize:13,marginTop:6,color:'#374151'}}>{p.raw}</div>
                <div style={{fontSize:12,color:'#6b7280',marginTop:6}}>Дата: {p.date || '—'} Время: {p.start || '—'}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Add event modal (shown when editing and a date selected) */}
      {addDate && (
        <AddEventModal date={addDate} onClose={() => { setAddDate(null) }} onSaved={() => { setAddDate(null); load() }} />
      )}
      {transferEvent && (
        <TransferModal ev={transferEvent} onClose={() => setTransferEvent(null)} onSaved={() => { setTransferEvent(null); load() }} />
      )}
    </div>
  )
}

  function typeColor(t) {
    // normalize and map to consistent colors
    if (!t) return '#6b7280'
    const n = String(t).toLowerCase().trim()
    if (n.includes('schedule') || n.includes('расписание')) return '#60a5fa'
    if (n.includes('homework') || n.includes('домаш') || n.includes('домашнее_задание') || n.includes('домашняя_работа')) return '#a78bfa'
    if (n.includes('transfer') || n.includes('перенос')) return '#ef4444'
    if (n.includes('announcement') || n.includes('объявлен')) return '#34d399'
    return '#9ca3af'
  }

  // eventColor: defensive color decision using event fields (type, body, title)
  function eventColor(ev) {
    try {
      if (!ev) return typeColor(ev?.type)
      const body = (ev.body || '').toString().toLowerCase()
      const title = (ev.title || '').toString().toLowerCase()
      // if body/title mention перенос — force transfer color
      if (body.includes('перенос') || title.includes('перенос') || body.includes('перенес')) return '#ef4444'
      return typeColor(ev.type)
    } catch (e) {
      return typeColor(ev?.type)
    }
  }

  function typeLabel(t) {
    if (!t) return ''
    const n = String(t).toLowerCase().trim()
    if (n.includes('transfer') || n.includes('перенос')) return 'Перенос'
    if (n.includes('homework') || n.startsWith('home') || n.includes('домаш')) return 'Домашняя работа'
    if (n.includes('schedule') || n.includes('расписание')) return 'Расписание'
    if (n.includes('announcement') || n.includes('объявлен')) return 'Объявление'
    return t
  }

  function AddEventModal({ date, onClose, onSaved }) {
    const [type, setType] = useState('schedule')
    const [title, setTitle] = useState('')
    const [body, setBody] = useState('')
    const [time, setTime] = useState('')
    const [endTime, setEndTime] = useState('')
    const [repeat, setRepeat] = useState('none')
    const [repeatUntil, setRepeatUntil] = useState('')
    const [saving, setSaving] = useState(false)

    useEffect(() => { setTitle(''); setBody(''); setTime(''); setRepeat('none'); setRepeatUntil('') }, [date])

    async function handleSave() {
      if (!date) return
      setSaving(true)
      try {
        const start = new Date(date)
        const occurrences = []
        if (repeat === 'none') occurrences.push(date)
        else {
          if (!repeatUntil) throw new Error('Укажите дату окончания повтора')
          const until = new Date(repeatUntil)
          let cur = new Date(date)
          let step = 1
          if (repeat === 'daily') step = 1
          if (repeat === 'weekly') step = 7
          if (repeat === 'biweekly') step = 14
          // push dates until <= until (safety max 500)
          let guard = 0
          while (cur <= until && guard < 500) {
            occurrences.push(cur.toISOString().slice(0,10))
            cur.setUTCDate(cur.getUTCDate() + step)
            guard++
          }

          function TransferModal({ ev, onClose, onSaved }) {
            const [targetDate, setTargetDate] = useState(ev.date || '')
            const [targetTime, setTargetTime] = useState(ev.time ? ev.time.slice(0,5) : '')
            const [targetEnd, setTargetEnd] = useState(ev.end_time ? ev.end_time.slice(0,5) : '')
            const [saving, setSaving] = useState(false)

            async function doTransfer() {
              setSaving(true)
              try {
                const payload = { date: targetDate }
                if (targetTime) payload.time = targetTime
                else payload.time = null
                if (targetEnd) payload.end_time = targetEnd
                const res = await fetch(`/events/${ev.id}`, { method: 'PUT', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload) })
                if (!res.ok) throw new Error('transfer failed: ' + res.status)
                alert('Перенесено')
                if (onSaved) onSaved()
              } catch (e) {
                console.error(e)
                alert('Ошибка переноса: ' + e.message)
              } finally {
                setSaving(false)
              }
            }

            return (
              <div className="modal-overlay" onClick={onClose}>
                <div className="modal" onClick={e => e.stopPropagation()} style={{minWidth:360,maxWidth:560}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                    <h3>Перенести событие</h3>
                    <button className="btn" onClick={onClose}>Закрыть</button>
                  </div>
                  <div style={{marginTop:8}}>
                    <div style={{fontWeight:700}}>{ev.title || ev.subject || ev.type}</div>
                    <div style={{marginTop:8,display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                      <div>
                        <label className="label">Новая дата</label>
                        <input type="date" value={targetDate} onChange={e => setTargetDate(e.target.value)} />
                      </div>
                      <div>
                        <label className="label">Новое время (начало)</label>
                        <input type="time" value={targetTime} onChange={e => setTargetTime(e.target.value)} />
                      </div>
                      <div>
                        <label className="label">Новое время (конец)</label>
                        <input type="time" value={targetEnd} onChange={e => setTargetEnd(e.target.value)} />
                      </div>
                    </div>
                    <div style={{marginTop:8,display:'flex',gap:8}}>
                      <button className="btn btn-primary" onClick={doTransfer} disabled={saving}>{saving ? 'Переношу...' : 'Перенести'}</button>
                      <button className="btn" onClick={onClose}>Отмена</button>
                    </div>
                  </div>
                </div>
              </div>
            )
          }
        }

        const created = []
        for (const d of occurrences) {
          // if homework, do not send time
          const payload = { type, title: title || null, body: body || '', date: d, time: (type === 'homework' ? null : (time || null)), end_time: (type === 'homework' ? null : (endTime || null)), reminder_offset_hours: 24 }
          // mark manual source and disable reminders on server side; include source for clarity
          payload.source = 'manual'
          const res = await fetch('/events', { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload) })
          if (!res.ok) throw new Error('save failed: ' + res.status)
          const j = await res.json()
          created.push(j)
        }
        alert('Создано: ' + created.length)
        if (onSaved) onSaved()
      } catch (e) {
        console.error(e)
        alert('Ошибка создания: ' + e.message)
      } finally {
        setSaving(false)
      }
    }

    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={e => e.stopPropagation()} style={{minWidth:360,maxWidth:680}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <h3>Добавить событие на {date}</h3>
            <button className="btn" onClick={onClose}>Закрыть</button>
          </div>
          <div style={{marginTop:8}}>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
              <div>
                <label className="label">Тип</label>
                <select value={type} onChange={e => setType(e.target.value)}>
                  <option value="schedule">Пара / Мероприятие</option>
                  <option value="homework">Домашнее задание</option>
                  <option value="transfer">Перенос</option>
                  <option value="announcement">Объявление</option>
                </select>
              </div>
              <div>
                <label className="label">Короткий заголовок</label>
                <input value={title} onChange={e => setTitle(e.target.value)} />
              </div>
              <div>
                <label className="label">Дата (начало)</label>
                <input type="date" value={date} onChange={e => {/* no-op: modal tied to date param */}} />
              </div>
              {/* For homework don't show time; otherwise allow start and end */}
              {type !== 'homework' && (
                <div>
                  <label className="label">Время начала</label>
                  <input type="time" value={time} onChange={e => setTime(e.target.value)} />
                </div>
              )}
              {type !== 'homework' && (
                <div>
                  <label className="label">Время окончания</label>
                  <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} />
                </div>
              )}
              <div>
                <label className="label">Повтор</label>
                <select value={repeat} onChange={e => setRepeat(e.target.value)}>
                  <option value="none">Не повторять</option>
                  <option value="daily">Каждый день</option>
                  <option value="weekly">Каждую неделю</option>
                  <option value="biweekly">Каждые 2 недели</option>
                </select>
              </div>
              <div>
                <label className="label">Повтор до</label>
                <input type="date" value={repeatUntil} onChange={e => setRepeatUntil(e.target.value)} />
              </div>
            </div>

            <label className="label">Подробности</label>
            <textarea value={body} onChange={e => setBody(e.target.value)} />

            <div style={{marginTop:8,display:'flex',gap:8,alignItems:'center'}}>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>{saving? 'Сохраняю...':'Сохранить'}</button>
              <button className="btn" onClick={onClose}>Отмена</button>
            </div>
          </div>
        </div>
      </div>
    )
  }
