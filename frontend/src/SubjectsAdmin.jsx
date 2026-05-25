import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

function countSummary(row) {
  const parts = []
  if (row.schedule_count) parts.push(`пары: ${row.schedule_count}`)
  if (row.homework_count) parts.push(`ДЗ: ${row.homework_count}`)
  if (row.exam_control_count) parts.push(`контроль: ${row.exam_control_count}`)
  if (row.transfer_count) parts.push(`переносы: ${row.transfer_count}`)
  if (row.announcement_count) parts.push(`объявления: ${row.announcement_count}`)
  return parts.join(' · ') || 'нет событий'
}

function variantKey(groupKey, rawName) {
  return `${groupKey}\0${rawName}`
}

export default function SubjectsAdmin() {
  const [subjects, setSubjects] = useState([])
  const [teachers, setTeachers] = useState([])
  const [drafts, setDrafts] = useState({})
  const [teacherDrafts, setTeacherDrafts] = useState({})
  const [variantDrafts, setVariantDrafts] = useState({})
  const [teacherVariantDrafts, setTeacherVariantDrafts] = useState({})
  const [query, setQuery] = useState('')
  const [teacherQuery, setTeacherQuery] = useState('')
  const [showHidden, setShowHidden] = useState(true)
  const [loading, setLoading] = useState(true)
  const [savingKey, setSavingKey] = useState(null)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setStatus('')
    try {
      const [subjectsRes, teachersRes] = await Promise.all([
        axios.get('/admin/subjects'),
        axios.get('/admin/teachers'),
      ])
      const subjectsList = Array.isArray(subjectsRes.data.subjects) ? subjectsRes.data.subjects : []
      const teachersList = Array.isArray(teachersRes.data.teachers) ? teachersRes.data.teachers : []
      setSubjects(subjectsList)
      setTeachers(teachersList)
      setDrafts(Object.fromEntries(subjectsList.map(s => [s.subject_key, s.display_name])))
      setTeacherDrafts(Object.fromEntries(teachersList.map(t => [t.teacher_key, t.display_name])))
      setVariantDrafts(Object.fromEntries(
        subjectsList.flatMap(s => (s.raw_names || []).map(name => [variantKey(s.subject_key, name), name])),
      ))
      setTeacherVariantDrafts(Object.fromEntries(
        teachersList.flatMap(t => (t.raw_names || []).map(name => [variantKey(t.teacher_key, name), name])),
      ))
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return subjects.filter(row => {
      if (!showHidden && !row.is_visible) return false
      if (!q) return true
      const haystack = [
        row.display_name,
        row.subject_key,
        ...(row.raw_names || []),
      ].join(' ').toLowerCase()
      return haystack.includes(q)
    })
  }, [subjects, query, showHidden])

  const visibleTeachers = useMemo(() => {
    const q = teacherQuery.trim().toLowerCase()
    return teachers.filter(row => {
      if (!showHidden && !row.is_visible) return false
      if (!q) return true
      const haystack = [
        row.display_name,
        row.teacher_key,
        ...(row.raw_names || []),
        ...(row.subjects || []),
      ].join(' ').toLowerCase()
      return haystack.includes(q)
    })
  }, [teachers, teacherQuery, showHidden])

  async function saveSubject(row, patch = {}) {
    const nextName = (drafts[row.subject_key] || '').trim()
    if (!nextName) {
      setStatus('Название предмета не может быть пустым')
      return
    }

    setSavingKey(row.subject_key)
    setStatus('')
    setError(null)
    try {
      const { data } = await axios.patch('/admin/subjects', {
        subject_key: row.subject_key,
        display_name: nextName,
        is_visible: row.is_visible,
        rename_events: true,
        ...patch,
      })
      const updated = data.subject
      setSubjects(prev => {
        const withoutOld = prev.filter(s => s.subject_key !== row.subject_key && s.subject_key !== updated.subject_key)
        return [...withoutOld, updated].sort((a, b) => {
          if (a.is_visible !== b.is_visible) return a.is_visible ? -1 : 1
          return a.display_name.localeCompare(b.display_name, 'ru')
        })
      })
      setDrafts(prev => {
        const next = { ...prev }
        delete next[row.subject_key]
        next[updated.subject_key] = updated.display_name
        return next
      })
      setStatus(
        data.updated_events > 0
          ? `Сохранено. Обновлено событий: ${data.updated_events}`
          : 'Сохранено',
      )
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setSavingKey(null)
    }
  }

  async function saveTeacher(row, patch = {}) {
    const nextName = (teacherDrafts[row.teacher_key] || '').trim()
    if (!nextName) {
      setStatus('Имя преподавателя не может быть пустым')
      return
    }

    setSavingKey(`teacher:${row.teacher_key}`)
    setStatus('')
    setError(null)
    try {
      const { data } = await axios.patch('/admin/teachers', {
        teacher_key: row.teacher_key,
        display_name: nextName,
        is_visible: row.is_visible,
        rename_events: true,
        ...patch,
      })
      const updated = data.teacher
      setTeachers(prev => {
        const withoutOld = prev.filter(t => t.teacher_key !== row.teacher_key && t.teacher_key !== updated.teacher_key)
        return [...withoutOld, updated].sort((a, b) => {
          if (a.is_visible !== b.is_visible) return a.is_visible ? -1 : 1
          return a.display_name.localeCompare(b.display_name, 'ru')
        })
      })
      setTeacherDrafts(prev => {
        const next = { ...prev }
        delete next[row.teacher_key]
        next[updated.teacher_key] = updated.display_name
        return next
      })
      setStatus(
        data.updated_events > 0
          ? `Сохранено. Обновлено событий: ${data.updated_events}`
          : 'Сохранено',
      )
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setSavingKey(null)
    }
  }

  async function saveSubjectVariant(row, rawName) {
    const key = variantKey(row.subject_key, rawName)
    const nextName = (variantDrafts[key] || '').trim()
    if (!nextName) {
      setStatus('Название варианта не может быть пустым')
      return
    }

    setSavingKey(`subject-variant:${key}`)
    setStatus('')
    setError(null)
    try {
      const { data } = await axios.patch('/admin/subjects/variant', {
        subject_key: row.subject_key,
        raw_name: rawName,
        display_name: nextName,
      })
      await load()
      setStatus(
        data.updated_events > 0
          ? `Вариант сохранён. Обновлено событий: ${data.updated_events}`
          : 'Вариант сохранён',
      )
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setSavingKey(null)
    }
  }

  async function saveTeacherVariant(row, rawName) {
    const key = variantKey(row.teacher_key, rawName)
    const nextName = (teacherVariantDrafts[key] || '').trim()
    if (!nextName) {
      setStatus('Имя варианта не может быть пустым')
      return
    }

    setSavingKey(`teacher-variant:${key}`)
    setStatus('')
    setError(null)
    try {
      const { data } = await axios.patch('/admin/teachers/variant', {
        teacher_key: row.teacher_key,
        raw_name: rawName,
        display_name: nextName,
      })
      await load()
      setStatus(
        data.updated_events > 0
          ? `Вариант сохранён. Обновлено событий: ${data.updated_events}`
          : 'Вариант сохранён',
      )
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setSavingKey(null)
    }
  }

  function changeDraft(key, value) {
    setDrafts(prev => ({ ...prev, [key]: value }))
  }

  function changeTeacherDraft(key, value) {
    setTeacherDrafts(prev => ({ ...prev, [key]: value }))
  }

  function changeVariantDraft(key, value) {
    setVariantDrafts(prev => ({ ...prev, [key]: value }))
  }

  function changeTeacherVariantDraft(key, value) {
    setTeacherVariantDrafts(prev => ({ ...prev, [key]: value }))
  }

  return (
    <div className="card subjects-admin-card">
      <div className="subjects-header">
        <div>
          <h2>Списки</h2>
          <p className="status" style={{ marginTop: 4 }}>
            Справочники собираются из событий календаря. Переименование обновляет все связанные события.
          </p>
        </div>
        <button type="button" className="btn btn-sm" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      <div className="subjects-toolbar">
        <label className="subjects-search">
          <span className="label">Поиск</span>
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Предмет, дубль или часть названия"
          />
        </label>
        <label className="subjects-toggle">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={e => setShowHidden(e.target.checked)}
          />
          Показывать скрытые
        </label>
      </div>

      {loading && <div style={{ marginTop: 16 }}>Загрузка...</div>}
      {error && <div className="error" style={{ marginTop: 16 }}>{String(error)}</div>}
      {status && <div className="status" style={{ marginTop: 16 }}>{status}</div>}

      {!loading && !error && (
        <h3 className="subjects-section-title">Предметы</h3>
      )}

      {!loading && !error && visibleRows.length === 0 && (
        <p className="status" style={{ marginTop: 16 }}>Предметы не найдены.</p>
      )}

      {!loading && !error && visibleRows.length > 0 && (
        <div className="subjects-table-wrap">
          <table className="subjects-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Видимость</th>
                <th>События</th>
                <th>Дубли / варианты</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map(row => {
                const draft = drafts[row.subject_key] ?? row.display_name
                const changed = draft.trim() !== row.display_name
                const busy = savingKey === row.subject_key
                return (
                  <tr key={row.subject_key} className={!row.is_visible ? 'subjects-row-hidden' : ''}>
                    <td>
                      <input
                        value={draft}
                        onChange={e => changeDraft(row.subject_key, e.target.value)}
                        disabled={busy}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className={row.is_visible ? 'subjects-visibility subjects-visible' : 'subjects-visibility subjects-hidden'}
                        disabled={busy}
                        onClick={() => saveSubject(row, { is_visible: !row.is_visible })}
                      >
                        {row.is_visible ? 'Показывается' : 'Скрыт'}
                      </button>
                    </td>
                    <td>
                      <strong>{row.events_total}</strong>
                      <div className="status subjects-count-summary">{countSummary(row)}</div>
                    </td>
                    <td>
                      <details>
                        <summary>
                          {(row.raw_names || []).length > 1
                            ? `${row.raw_names.length} вариантов`
                            : '1 вариант'}
                        </summary>
                        <div className="subjects-variant-edit-list">
                          {(row.raw_names || []).map(name => {
                            const key = variantKey(row.subject_key, name)
                            const value = variantDrafts[key] ?? name
                            const variantBusy = savingKey === `subject-variant:${key}`
                            return (
                              <div className="subjects-variant-edit-row" key={name}>
                                <span className="subjects-variant-original" title={name}>{name}</span>
                                <input
                                  value={value}
                                  onChange={e => changeVariantDraft(key, e.target.value)}
                                  disabled={variantBusy}
                                />
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  disabled={variantBusy || value.trim() === name}
                                  onClick={() => saveSubjectVariant(row, name)}
                                >
                                  {variantBusy ? '...' : 'Срастить'}
                                </button>
                              </div>
                            )
                          })}
                        </div>
                      </details>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        disabled={busy || !changed}
                        onClick={() => saveSubject(row)}
                      >
                        {busy ? 'Сохраняю...' : 'Сохранить'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && (
        <>
          <div className="subjects-section-head">
            <h3 className="subjects-section-title">Преподаватели</h3>
            <label className="subjects-search subjects-search-compact">
              <span className="label">Поиск преподавателя</span>
              <input
                type="search"
                value={teacherQuery}
                onChange={e => setTeacherQuery(e.target.value)}
                placeholder="ФИО, дубль или предмет"
              />
            </label>
          </div>

          {visibleTeachers.length === 0 ? (
            <p className="status" style={{ marginTop: 16 }}>Преподаватели не найдены.</p>
          ) : (
            <div className="subjects-table-wrap">
              <table className="subjects-table">
                <thead>
                  <tr>
                    <th>Имя</th>
                    <th>Видимость</th>
                    <th>События</th>
                    <th>Предметы</th>
                    <th>Дубли / варианты</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleTeachers.map(row => {
                    const draft = teacherDrafts[row.teacher_key] ?? row.display_name
                    const changed = draft.trim() !== row.display_name
                    const busy = savingKey === `teacher:${row.teacher_key}`
                    return (
                      <tr key={row.teacher_key} className={!row.is_visible ? 'subjects-row-hidden' : ''}>
                        <td>
                          <input
                            value={draft}
                            onChange={e => changeTeacherDraft(row.teacher_key, e.target.value)}
                            disabled={busy}
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className={row.is_visible ? 'subjects-visibility subjects-visible' : 'subjects-visibility subjects-hidden'}
                            disabled={busy}
                            onClick={() => saveTeacher(row, { is_visible: !row.is_visible })}
                          >
                            {row.is_visible ? 'Показывается' : 'Скрыт'}
                          </button>
                        </td>
                        <td>
                          <strong>{row.events_total}</strong>
                          <div className="status subjects-count-summary">
                            пары: {row.schedule_count} · контроль: {row.exam_control_count} · переносы: {row.transfer_count}
                          </div>
                        </td>
                        <td>
                          {(row.subjects || []).length > 0 ? (
                            <div className="subjects-tags">
                              {row.subjects.slice(0, 4).map(name => <span key={name}>{name}</span>)}
                              {row.subjects.length > 4 ? <span>+{row.subjects.length - 4}</span> : null}
                            </div>
                          ) : (
                            <span className="status">не указаны</span>
                          )}
                        </td>
                        <td>
                          <details>
                            <summary>
                              {(row.raw_names || []).length > 1
                                ? `${row.raw_names.length} вариантов`
                                : '1 вариант'}
                            </summary>
                            <div className="subjects-variant-edit-list">
                              {(row.raw_names || []).map(name => {
                                const key = variantKey(row.teacher_key, name)
                                const value = teacherVariantDrafts[key] ?? name
                                const variantBusy = savingKey === `teacher-variant:${key}`
                                return (
                                  <div className="subjects-variant-edit-row" key={name}>
                                    <span className="subjects-variant-original" title={name}>{name}</span>
                                    <input
                                      value={value}
                                      onChange={e => changeTeacherVariantDraft(key, e.target.value)}
                                      disabled={variantBusy}
                                    />
                                    <button
                                      type="button"
                                      className="btn btn-sm"
                                      disabled={variantBusy || value.trim() === name}
                                      onClick={() => saveTeacherVariant(row, name)}
                                    >
                                      {variantBusy ? '...' : 'Срастить'}
                                    </button>
                                  </div>
                                )
                              })}
                            </div>
                          </details>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            disabled={busy || !changed}
                            onClick={() => saveTeacher(row)}
                          >
                            {busy ? 'Сохраняю...' : 'Сохранить'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
