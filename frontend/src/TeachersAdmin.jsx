import React, { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

const EMPTY_FORM = {
  full_name: '',
  academic_degree: '',
  position: '',
  department: '',
  contact: '',
  bio: '',
}

function toForm(t) {
  return {
    full_name: t.full_name || '',
    academic_degree: t.academic_degree || '',
    position: t.position || '',
    department: t.department || '',
    contact: t.contact || '',
    bio: t.bio || '',
  }
}

function toPayload(form) {
  return {
    full_name: form.full_name.trim(),
    academic_degree: form.academic_degree.trim() || null,
    position: form.position.trim() || null,
    department: form.department.trim() || null,
    contact: form.contact.trim() || null,
    bio: form.bio.trim() || null,
  }
}

function TeacherEditor({ initial, busy, onSave, onCancel, submitLabel }) {
  const [form, setForm] = useState(initial)

  useEffect(() => {
    setForm(initial)
  }, [initial])

  function set(field, value) {
    setForm(prev => ({ ...prev, [field]: value }))
  }

  return (
    <div className="teacher-editor">
      <div className="teacher-editor-grid">
        <div className="teacher-editor-field">
          <label className="label">ФИО *</label>
          <input
            value={form.full_name}
            onChange={e => set('full_name', e.target.value)}
            placeholder="Иванов Иван Иванович"
          />
        </div>
        <div className="teacher-editor-field">
          <label className="label">Научная степень</label>
          <input
            value={form.academic_degree}
            onChange={e => set('academic_degree', e.target.value)}
            placeholder="к.ф.-м.н., д.т.н., PhD…"
          />
        </div>
        <div className="teacher-editor-field">
          <label className="label">Должность</label>
          <input
            value={form.position}
            onChange={e => set('position', e.target.value)}
            placeholder="Доцент, профессор, старший преподаватель…"
          />
        </div>
        <div className="teacher-editor-field">
          <label className="label">Кафедра</label>
          <input
            value={form.department}
            onChange={e => set('department', e.target.value)}
            placeholder="Например: Кафедра математики"
          />
        </div>
        <div className="teacher-editor-field">
          <label className="label">Связь</label>
          <input
            value={form.contact}
            onChange={e => set('contact', e.target.value)}
            placeholder="Телефон, email, кабинет…"
          />
        </div>
      </div>
      <div className="teacher-editor-field">
        <label className="label">О нём</label>
        <textarea
          className="teacher-bio-input"
          value={form.bio}
          onChange={e => set('bio', e.target.value)}
          placeholder="Биография, требования, особенности, заметки…"
        />
      </div>
      <div className="actions-wrap" style={{ marginTop: 8 }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !form.full_name.trim()}
          onClick={() => onSave(toPayload(form))}
        >
          {busy ? 'Сохраняю…' : (submitLabel || 'Сохранить')}
        </button>
        {onCancel && (
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Отмена
          </button>
        )}
      </div>
    </div>
  )
}

function TeacherCard({ t, isAdmin, onEdit, onDelete }) {
  return (
    <div className="teacher-card">
      <div className="teacher-card-head">
        <h3 className="teacher-card-name">{t.full_name}</h3>
        {isAdmin && (
          <div className="teacher-card-actions">
            <button type="button" className="btn btn-sm" onClick={() => onEdit(t)}>
              Редактировать
            </button>
            <button type="button" className="btn btn-sm btn-danger" onClick={() => onDelete(t)}>
              Удалить
            </button>
          </div>
        )}
      </div>
      <div className="teacher-card-meta">
        <div className="teacher-card-row">
          <span className="teacher-card-label">Степень</span>
          <span className="teacher-card-value">{t.academic_degree || '—'}</span>
        </div>
        <div className="teacher-card-row">
          <span className="teacher-card-label">Должность</span>
          <span className="teacher-card-value">{t.position || '—'}</span>
        </div>
        <div className="teacher-card-row">
          <span className="teacher-card-label">Кафедра</span>
          <span className="teacher-card-value">{t.department || '—'}</span>
        </div>
        <div className="teacher-card-row">
          <span className="teacher-card-label">Связь</span>
          <span className="teacher-card-value">{t.contact || '—'}</span>
        </div>
      </div>
      {t.bio ? (
        <div className="teacher-card-bio">
          <span className="teacher-card-label">О нём</span>
          <p>{t.bio}</p>
        </div>
      ) : null}
    </div>
  )
}

export default function TeachersAdmin({ isAdmin = false }) {
  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const { data } = await axios.get('/teacher-profiles')
      setTeachers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return teachers
    return teachers.filter(t => {
      const hay = [
        t.full_name,
        t.academic_degree,
        t.position,
        t.department,
        t.contact,
        t.bio,
      ].filter(Boolean).join(' ').toLowerCase()
      return hay.includes(q)
    })
  }, [teachers, query])

  async function createTeacher(payload) {
    setBusy(true)
    setStatus('')
    setError(null)
    try {
      await axios.post('/teacher-profiles', payload)
      setCreating(false)
      setStatus('Преподаватель добавлен')
      await load()
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function updateTeacher(id, payload) {
    setBusy(true)
    setStatus('')
    setError(null)
    try {
      await axios.put(`/teacher-profiles/${id}`, payload)
      setEditingId(null)
      setStatus('Изменения сохранены')
      await load()
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function syncFromEvents() {
    setSyncing(true)
    setStatus('')
    setError(null)
    try {
      const { data } = await axios.post('/teacher-profiles/sync')
      const created = data?.created || 0
      const updated = data?.updated || 0
      setStatus(
        created || updated
          ? `Готово: добавлено ${created}, дополнено ${updated}.`
          : 'Всё уже актуально — новых преподавателей не найдено.'
      )
      await load()
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setSyncing(false)
    }
  }

  async function deleteTeacher(t) {
    if (!window.confirm(`Удалить карточку преподавателя «${t.full_name}»?`)) return
    setStatus('')
    setError(null)
    try {
      await axios.delete(`/teacher-profiles/${t.id}`)
      setStatus('Карточка удалена')
      await load()
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    }
  }

  return (
    <div className="card teachers-admin-card">
      <div className="subjects-header">
        <div>
          <h2>Преподаватели</h2>
          <p className="status" style={{ marginTop: 4 }}>
            {isAdmin
              ? 'Карточки преподавателей: ФИО, научная степень, должность, кафедра, связь и описание. ФИО можно заполнить автоматически из расписания, остальное — вручную.'
              : 'Справочник преподавателей кафедры.'}
          </p>
        </div>
        <div className="actions-wrap">
          <button type="button" className="btn btn-sm" onClick={load} disabled={loading}>
            Обновить
          </button>
          {isAdmin && (
            <button
              type="button"
              className="btn btn-sm"
              onClick={syncFromEvents}
              disabled={syncing}
              title="Создать карточки для преподавателей из расписания"
            >
              {syncing ? 'Заполняю…' : 'Заполнить из расписания'}
            </button>
          )}
          {isAdmin && !creating && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => { setCreating(true); setEditingId(null) }}
            >
              + Добавить
            </button>
          )}
        </div>
      </div>

      <div className="subjects-toolbar">
        <label className="subjects-search">
          <span className="label">Поиск</span>
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="ФИО, степень, должность, кафедра…"
          />
        </label>
      </div>

      {error && <div className="error" style={{ marginTop: 12 }}>{String(error)}</div>}
      {status && <div className="status" style={{ marginTop: 12 }}>{status}</div>}

      {isAdmin && creating && (
        <div className="teacher-editor-wrap">
          <h3 className="subjects-section-title">Новый преподаватель</h3>
          <TeacherEditor
            initial={EMPTY_FORM}
            busy={busy}
            submitLabel="Добавить"
            onSave={createTeacher}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      {loading && <div style={{ marginTop: 16 }}>Загрузка…</div>}

      {!loading && !error && visible.length === 0 && (
        <p className="status" style={{ marginTop: 16 }}>
          {teachers.length === 0 ? 'Преподаватели ещё не добавлены.' : 'Ничего не найдено.'}
        </p>
      )}

      {!loading && visible.length > 0 && (
        <div className="teachers-grid">
          {visible.map(t => (
            editingId === t.id ? (
              <div className="teacher-editor-wrap" key={t.id}>
                <h3 className="subjects-section-title">Редактирование</h3>
                <TeacherEditor
                  initial={toForm(t)}
                  busy={busy}
                  submitLabel="Сохранить"
                  onSave={payload => updateTeacher(t.id, payload)}
                  onCancel={() => setEditingId(null)}
                />
              </div>
            ) : (
              <TeacherCard
                key={t.id}
                t={t}
                isAdmin={isAdmin}
                onEdit={tt => { setEditingId(tt.id); setCreating(false) }}
                onDelete={deleteTeacher}
              />
            )
          ))}
        </div>
      )}
    </div>
  )
}
