import React, { useEffect, useState } from 'react'
import axios from 'axios'

const KINDS = [
  { id: 'bug', label: 'Баг', hint: 'Что-то сломалось или работает не так' },
  { id: 'suggestion', label: 'Предложение', hint: 'Идея, как сделать удобнее' },
]

export default function FeedbackFab({ accountUser }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('bug')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [contact, setContact] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!open) return undefined
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function resetForm() {
    setKind('bug')
    setTitle('')
    setBody('')
    setContact('')
    setError('')
    setDone(false)
    setSending(false)
  }

  function close() {
    setOpen(false)
  }

  function openModal() {
    resetForm()
    setOpen(true)
  }

  async function submit(e) {
    e?.preventDefault?.()
    const t = title.trim()
    const b = body.trim()
    if (t.length < 3) {
      setError('Напишите короткий заголовок')
      return
    }
    if (b.length < 10) {
      setError('Опишите подробнее — хотя бы пару предложений')
      return
    }
    setError('')
    setSending(true)
    try {
      await axios.post('/feedback', {
        kind,
        title: t,
        body: b,
        page: `${window.location.pathname}${window.location.hash || ''}`,
        contact: contact.trim() || null,
      })
      setDone(true)
    } catch (err) {
      const d = err.response?.data?.detail
      if (typeof d === 'string') setError(d)
      else if (Array.isArray(d) && d[0]?.msg) setError(d[0].msg)
      else setError('Не удалось отправить. Попробуйте ещё раз')
    } finally {
      setSending(false)
    }
  }

  const sender = accountUser
    ? `${accountUser.last_name} ${accountUser.first_name}`.trim()
    : ''

  return (
    <>
      <button type="button" className="feedback-fab" onClick={openModal}>
        <span className="feedback-fab-icon" aria-hidden="true">💬</span>
        <span className="feedback-fab-label">Обратная связь</span>
      </button>
      {open ? (
        <div className="modal-overlay" onClick={close}>
          <div className="modal feedback-modal" onClick={e => e.stopPropagation()} role="dialog" aria-labelledby="feedback-title">
            {done ? (
              <>
                <h3 id="feedback-title">Спасибо</h3>
                <p className="status" style={{ marginTop: 10 }}>
                  Сообщение ушло. Если это баг — посмотрим и поправим.
                </p>
                <div className="modal-actions" style={{ marginTop: 16 }}>
                  <button type="button" className="btn btn-primary" onClick={close}>Закрыть</button>
                </div>
              </>
            ) : (
              <>
                <h3 id="feedback-title">Обратная связь</h3>
                <p className="status" style={{ marginTop: 8, fontSize: 13 }}>
                  Баг или идея — напишите, уйдёт в личку бота, не в общую беседу.
                </p>
                <form onSubmit={submit} style={{ marginTop: 12 }}>
                  <div className="feedback-kind" role="radiogroup" aria-label="Тип сообщения">
                    {KINDS.map(item => (
                      <button
                        key={item.id}
                        type="button"
                        className={kind === item.id ? 'feedback-kind-btn is-active' : 'feedback-kind-btn'}
                        aria-pressed={kind === item.id}
                        onClick={() => setKind(item.id)}
                      >
                        <strong>{item.label}</strong>
                        <span>{item.hint}</span>
                      </button>
                    ))}
                  </div>
                  <label className="label" htmlFor="feedback-title-input">Заголовок</label>
                  <input
                    id="feedback-title-input"
                    value={title}
                    onChange={e => setTitle(e.target.value)}
                    maxLength={150}
                    placeholder={kind === 'bug' ? 'Например: не открывается карточка пары' : 'Например: фильтр по преподавателю'}
                  />
                  <label className="label" htmlFor="feedback-body-input" style={{ marginTop: 10 }}>Описание</label>
                  <textarea
                    id="feedback-body-input"
                    value={body}
                    onChange={e => setBody(e.target.value)}
                    maxLength={3500}
                    placeholder={kind === 'bug' ? 'Что сделали, что ожидали и что произошло' : 'Как это должно работать'}
                  />
                  {sender ? (
                    <p className="status" style={{ marginTop: 10, fontSize: 13 }}>
                      Отправитель: {sender}
                    </p>
                  ) : (
                    <>
                      <label className="label" htmlFor="feedback-contact-input" style={{ marginTop: 10 }}>
                        Контакт (необязательно)
                      </label>
                      <input
                        id="feedback-contact-input"
                        value={contact}
                        onChange={e => setContact(e.target.value)}
                        maxLength={120}
                        placeholder="Telegram, почта или имя"
                      />
                    </>
                  )}
                  {error ? (
                    <div className="error" style={{ marginTop: 10, fontSize: 13 }}>{error}</div>
                  ) : null}
                  <div className="modal-actions" style={{ marginTop: 14 }}>
                    <button type="button" className="btn" onClick={close} disabled={sending}>Отмена</button>
                    <button type="submit" className="btn btn-primary" disabled={sending}>
                      {sending ? 'Отправка…' : 'Отправить'}
                    </button>
                  </div>
                </form>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  )
}
