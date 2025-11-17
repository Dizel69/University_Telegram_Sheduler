import React, { useState } from 'react'
import axios from 'axios'

export default function EventForm({ onCreated }) {
  const [type, setType] = useState('schedule')
  const [subject, setSubject] = useState('')
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [reminder, setReminder] = useState(24)
  const [status, setStatus] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setStatus('Отправка...')
    // Простая клиентская валидация
    if (!message || !message.trim()) {
      setStatus('Ошибка: Текст сообщения обязателен')
      return
    }
    if (time && !date) {
      setStatus('Ошибка: если указано время, нужно указать дату')
      return
    }

    try {
      const payload = {
        type,
        subject: subject || null,
        title: title || null,
        body: message,
        reminder_offset_hours: Number.isFinite(Number(reminder)) ? Number(reminder) : 24,
      }
      if (date) payload.date = date
      if (time) payload.time = time

      const res = await axios.post('/events/send', payload)
      setStatus('Отправлено — id: ' + res.data.id)
      setSubject('')
      setTitle('')
      setMessage('')
      setDate('')
      setTime('')
      setReminder(24)
      if (onCreated) onCreated(res.data)
    } catch (err) {
      console.error(err)
      const serverData = err.response?.data
      const msg = serverData?.detail ?? serverData ?? err.message
      setStatus('Ошибка: ' + (typeof msg === 'object' ? JSON.stringify(msg) : msg))
    }
  }

  return (
    <form onSubmit={handleSubmit} className="form card">
      <div className="form-grid">
        <div>
          <label className="label">Тип</label>
          <select value={type} onChange={e => setType(e.target.value)}>
            <option value="transfer">Перенос</option>
            <option value="homework">Домашнее задание</option>
            <option value="announcement">Объявление</option>
          </select>
        </div>

        <div>
          <label className="label">Предмет / Тема</label>
          <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Например: Математика" />
        </div>

        <div>
          <label className="label">Короткий заголовок</label>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Краткий заголовок (опционально)" />
        </div>

        <div>
          <label className="label">Дата</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>

        {/* For homework type we don't show time */}
        {type !== 'homework' && (
          <div>
            <label className="label">Время</label>
            <input type="time" value={time} onChange={e => setTime(e.target.value)} />
          </div>
        )}

        <div>
          <label className="label">Напоминание (ч)</label>
          <input type="number" min="0" value={reminder} onChange={e => setReminder(Number(e.target.value))} />
        </div>
      </div>

      <label className="label">Сообщение</label>
      <textarea value={message} onChange={e => setMessage(e.target.value)} placeholder="Текст сообщения — можно использовать #хэштеги" />

      <div className="form-actions">
        <button className="btn btn-primary" type="submit">Отправить сейчас</button>
        <button type="button" className="btn" onClick={() => { setSubject(''); setTitle(''); setMessage(''); setDate(''); setTime(''); setReminder(24); setStatus('') }}>Сброс</button>
        <div className="status">{status}</div>
      </div>
    </form>
  )
}
