import React, { useState } from 'react'
import axios from 'axios'

export default function EventForm({ onCreated }) {
  const [type, setType] = useState('schedule')
  const [subject, setSubject] = useState('')
  const [title, setTitle] = useState('')
  const [room, setRoom] = useState('')
  const [teacher, setTeacher] = useState('')
  const [message, setMessage] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [repeat, setRepeat] = useState('none')
  const [repeatUntil, setRepeatUntil] = useState('')
  const [reminder, setReminder] = useState(24)
  const [status, setStatus] = useState('')
  const [saveOnly, setSaveOnly] = useState(false)
  const [lessonType, setLessonType] = useState('lecture')
  const [examKind, setExamKind] = useState('control')
  const semester = localStorage.getItem('semester') || ''

  async function handleSubmit(e) {
    e.preventDefault()
    setStatus('Отправка...')
    // Простая клиентская валидация
    // Для schedule текст не обязателен, для остальных нужен
    if (type !== 'schedule' && (!message || !message.trim())) {
      setStatus('Ошибка: Текст сообщения обязателен')
      return
    }
    if (time && !date) {
      setStatus('Ошибка: если указано время, нужно указать дату')
      return
    }
    if (repeat !== 'none' && !date) {
      setStatus('Ошибка: для повтора нужно указать начальную дату')
      return
    }
    if (repeat !== 'none' && !repeatUntil) {
      setStatus('Ошибка: укажите дату окончания повтора')
      return
    }

    try {
      // Handle repeat series
      if (repeat === 'none') {
        const payload = {
          type,
          subject: subject || null,
          title: title || null,
          body: message,
          reminder_offset_hours: Number.isFinite(Number(reminder)) ? Number(reminder) : 24,
        }
        // keep type as canonical token (english) so backend/frontend stay consistent
        if (date) payload.date = date
        if (time) payload.time = time
        if (endTime) payload.end_time = endTime
        if (room) payload.room = room
        if (teacher) payload.teacher = teacher
        if (type === 'schedule') payload.lesson_type = lessonType

        let res
        if (saveOnly) {
          // Сохраняем событие в БД не отправляя (бэкенд пометит source='manual')
          res = await axios.post('/events', payload)
          setStatus('Сохранено в календаре (ручная запись) — id: ' + res.data.id)
        } else {
          res = await axios.post('/events/send', payload)
          setStatus('Отправлено — id: ' + res.data.id)
        }
        setSubject('')
        setTitle('')
        setRoom('')
        setTeacher('')
        setMessage('')
        setDate('')
        setTime('')
        setEndTime('')
        setRepeat('none')
        setRepeatUntil('')
        setReminder(24)
        setLessonType('lecture')
        setExamKind('control')
        // Для schedule не переходить на вкладку События
        if (onCreated && type !== 'schedule') onCreated(res.data)
        return
      }

      // Repeat creation: create occurrences without sending immediately
      const occurrences = []
      const start = new Date(date)
      const until = new Date(repeatUntil)
      let cur = new Date(date)
      let step = 1
      if (repeat === 'daily') step = 1
      if (repeat === 'weekly') step = 7
      if (repeat === 'biweekly') step = 14
      let guard = 0
      while (cur <= until && guard < 500) {
        occurrences.push(cur.toISOString().slice(0,10))
        cur.setUTCDate(cur.getUTCDate() + step)
        guard++
      }

      const seriesId = (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : ('s-' + Date.now() + '-' + Math.random().toString(36).slice(2,7)))
      const created = []
      for (const d of occurrences) {
        const payload = {
          type,
          subject: subject || null,
          title: title || null,
          body: message || '',
          date: d,
          time: (type === 'homework' ? null : (time || null)),
          end_time: (type === 'homework' ? null : (endTime || null)),
          room: room || null,
          teacher: teacher || null,
          series_id: seriesId,
          reminder_offset_hours: Number.isFinite(Number(reminder)) ? Number(reminder) : 24,
        }
        if (type === 'schedule') payload.lesson_type = lessonType
        if (type === 'exam_control') payload.lesson_type = examKind
        payload.source = 'manual'
        const res = await axios.post('/events', payload)
        created.push(res.data)
      }
      setStatus('Создано: ' + created.length + ' событий (серия)')
      setSubject('')
      setTitle('')
      setRoom('')
      setTeacher('')
      setMessage('')
      setDate('')
      setTime('')
      setEndTime('')
      setRepeat('none')
      setRepeatUntil('')
      setReminder(24)
      setLessonType('lecture')
      setExamKind('control')
      // Для schedule не переходить на вкладку События
      if (onCreated && created.length && type !== 'schedule') onCreated(created[0])

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
            <option value="schedule">Пара / Мероприятие</option>
            <option value="exam_control">Контрольная / экзамен</option>
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

        {type !== 'homework' && (
          <div>
            <label className="label">Аудитория</label>
            <input value={room} onChange={e => setRoom(e.target.value)} placeholder="Например: М101" />
          </div>
        )}

        {type !== 'homework' && (
          <div>
            <label className="label">Преподаватель</label>
            <input value={teacher} onChange={e => setTeacher(e.target.value)} placeholder="Ф.И.О." />
          </div>
        )}

        {/* show semester control when creating homework */}
        {type === 'homework' && (
          <div style={{gridColumn:'1/-1', textAlign:'right', fontSize:12, opacity:0.6}}>
            {semester ? (
              <>Семестр: <b>{semester}</b>{' '}</>
            ) : (
              <>Семестр не настроен.{' '}</>
            )}
            <a href="#semester" style={{fontSize:12}}>{semester ? 'изменить' : 'настроить'}</a>
          </div>
        )}

        {type === 'schedule' && (
          <div>
            <label className="label">Тип пары</label>
            <div style={{display:'flex', gap:12, alignItems:'center'}}>
              <button 
                type="button"
                onClick={() => setLessonType('lecture')}
                style={{
                  padding:'8px 16px',
                  border: lessonType === 'lecture' ? '2px solid #2563eb' : '1px solid #ddd',
                  borderRadius:'4px',
                  backgroundColor: lessonType === 'lecture' ? '#dbeafe' : '#fff',
                  cursor:'pointer',
                  fontWeight: lessonType === 'lecture' ? 'bold' : 'normal'
                }}
              >
                🔊 Лекция
              </button>
              <button 
                type="button"
                onClick={() => setLessonType('practice')}
                style={{
                  padding:'8px 16px',
                  border: lessonType === 'practice' ? '2px solid #2563eb' : '1px solid #ddd',
                  borderRadius:'4px',
                  backgroundColor: lessonType === 'practice' ? '#dbeafe' : '#fff',
                  cursor:'pointer',
                  fontWeight: lessonType === 'practice' ? 'bold' : 'normal'
                }}
              >
                📓 Практика
              </button>
            </div>
          </div>
        )}

        {type === 'exam_control' && (
          <div>
            <label className="label">Вид</label>
            <div style={{display:'flex', gap:12, alignItems:'center'}}>
              <button
                type="button"
                onClick={() => setExamKind('control')}
                style={{
                  padding:'8px 16px',
                  border: examKind === 'control' ? '2px solid #ea580c' : '1px solid #ddd',
                  borderRadius:'4px',
                  backgroundColor: examKind === 'control' ? '#ffedd5' : '#fff',
                  cursor:'pointer',
                  fontWeight: examKind === 'control' ? 'bold' : 'normal'
                }}
              >
                📝 Контрольная
              </button>
              <button
                type="button"
                onClick={() => setExamKind('exam')}
                style={{
                  padding:'8px 16px',
                  border: examKind === 'exam' ? '2px solid #ea580c' : '1px solid #ddd',
                  borderRadius:'4px',
                  backgroundColor: examKind === 'exam' ? '#ffedd5' : '#fff',
                  cursor:'pointer',
                  fontWeight: examKind === 'exam' ? 'bold' : 'normal'
                }}
              >
                🎓 Экзамен
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="label">Дата</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>

        {/* For homework type we don't show time */}
        {type !== 'homework' && (
          <>
            <div>
              <label className="label">Время начала</label>
              <input type="time" value={time} onChange={e => setTime(e.target.value)} />
            </div>
            <div>
              <label className="label">Время окончания</label>
              <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)} />
            </div>
          </>
        )}

        {type !== 'homework' && (
          <div>
            <label className="label">Повтор</label>
            <select value={repeat} onChange={e => setRepeat(e.target.value)}>
              <option value="none">Не повторять</option>
              <option value="daily">Каждый день</option>
              <option value="weekly">Каждую неделю</option>
              <option value="biweekly">Каждые 2 недели</option>
            </select>
          </div>
        )}

        {type !== 'homework' && (
          <div>
            <label className="label">Повтор до</label>
            <input type="date" value={repeatUntil} onChange={e => setRepeatUntil(e.target.value)} />
          </div>
        )}

        <div>
          <label className="label">Напоминание (ч)</label>
          <input type="number" min="0" value={reminder} onChange={e => setReminder(Number(e.target.value))} />
        </div>
      </div>

      {type !== 'schedule' && (
        <>
          <div style={{marginTop:10}}>
            <label style={{display:'inline-flex', alignItems:'center', gap:8}}>
              <input type="checkbox" checked={saveOnly} onChange={e => setSaveOnly(e.target.checked)} />
              <span>Сохранить в календаре (без отправки) — скрыть во вкладке «События»</span>
            </label>
          </div>

          <label className="label">Сообщение</label>
          <textarea value={message} onChange={e => setMessage(e.target.value)} placeholder="Текст сообщения — можно использовать #хэштеги" />
        </>
      )}

      <div className="form-actions">
        <button className="btn btn-primary" type="submit">Отправить сейчас</button>
        <button type="button" className="btn" onClick={() => { setSubject(''); setTitle(''); setRoom(''); setTeacher(''); setMessage(''); setDate(''); setTime(''); setEndTime(''); setRepeat('none'); setRepeatUntil(''); setReminder(24); setLessonType('lecture'); setExamKind('control'); setStatus('') }}>Сброс</button>
        <div className="status">{status}</div>
      </div>
    </form>
  )
}
