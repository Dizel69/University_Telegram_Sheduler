import React, { useState } from 'react'
import axios from 'axios'

export default function EditEventModal({ ev, onClose, onSaved }) {
  if (!ev) return null
  const [type, setType] = useState(ev.type || 'schedule')
  const [title, setTitle] = useState(ev.title || '')
  const [body, setBody] = useState(ev.body || '')
  const [time, setTime] = useState(ev.time ? ev.time.slice(0,5) : '')
  const [endTime, setEndTime] = useState(ev.end_time ? ev.end_time.slice(0,5) : '')
  const [room, setRoom] = useState(ev.room || '')
  const [teacher, setTeacher] = useState(ev.teacher || '')
  const [applySeries, setApplySeries] = useState(false)
  const [saving, setSaving] = useState(false)

  async function doSave() {
    setSaving(true)
    try {
      const payload = {}
      if (type) payload.type = type
      payload.title = title || null
      payload.body = body || null
      // for homework, clear time fields
      if (type === 'homework') {
        payload.time = null
        payload.end_time = null
      } else {
        payload.time = time || null
        payload.end_time = endTime || null
      }
      payload.room = room || null
      payload.teacher = teacher || null

      const q = applySeries ? '?apply_to_series=true' : ''
      const res = await axios.put(`/events/${ev.id}${q}`, payload)
      if (res.status >= 200 && res.status < 300) {
        alert('Сохранено')
        if (onSaved) onSaved()
      } else {
        throw new Error('save failed: ' + res.status)
      }
    } catch (e) {
      console.error(e)
      alert('Ошибка сохранения: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{minWidth:360,maxWidth:680}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
          <h3>Редактировать событие</h3>
          <button className="btn" onClick={onClose}>Закрыть</button>
        </div>
        <div style={{marginTop:8}}>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
            <div>
              <label className="label">Тип</label>
              <select value={type} onChange={e => setType(e.target.value)}>
                <option value="schedule">Пара / Мероприятие</option>
                <option value="transfer">Перенос</option>
                <option value="homework">Домашнее задание</option>
                <option value="announcement">Объявление</option>
              </select>
            </div>
            <div>
              <label className="label">Короткий заголовок</label>
              <input value={title} onChange={e => setTitle(e.target.value)} />
            </div>
            <div>
              <label className="label">Аудитория</label>
              <input value={room} onChange={e => setRoom(e.target.value)} placeholder="Например: М101" />
            </div>
            <div>
              <label className="label">Преподаватель</label>
              <input value={teacher} onChange={e => setTeacher(e.target.value)} placeholder="Ф.И.О." />
            </div>
            {type !== 'homework' && (
              <>
                <div>
                  <label className="label">Время (начало)</label>
                  <input type="time" value={time} onChange={e => setTime(e.target.value)} />
                </div>
                <div>
                  <label className="label">Время (конец)</label>
                  <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} />
                </div>
              </>
            )}
          </div>

          <label className="label">Подробности</label>
          <textarea value={body} onChange={e => setBody(e.target.value)} />

          <div style={{marginTop:8,display:'flex',gap:8,alignItems:'center'}}>
            <label style={{display:'inline-flex', alignItems:'center', gap:8}}>
              <input type="checkbox" checked={applySeries} onChange={e => setApplySeries(e.target.checked)} />
              <span>Применить ко всей серии</span>
            </label>
          </div>

          <div style={{marginTop:8,display:'flex',gap:8}}>
            <button className="btn btn-primary" onClick={doSave} disabled={saving}>{saving ? 'Сохраняю...' : 'Сохранить'}</button>
            <button className="btn" onClick={onClose}>Отмена</button>
          </div>
        </div>
      </div>
    </div>
  )
}
