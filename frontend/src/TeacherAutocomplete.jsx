import React, { useEffect, useRef, useState } from 'react'
import axios from 'axios'

// Кэш списка преподавателей, общий для всех экземпляров компонента,
// чтобы не дёргать бэкенд при каждом открытии формы.
let teachersCache = null
let teachersPromise = null

async function loadTeachers(force = false) {
  if (!force && teachersCache) return teachersCache
  if (!force && teachersPromise) return teachersPromise
  teachersPromise = axios
    .get('/teachers')
    .then(res => {
      teachersCache = Array.isArray(res.data) ? res.data : []
      return teachersCache
    })
    .catch(() => {
      teachersCache = teachersCache || []
      return teachersCache
    })
    .finally(() => {
      teachersPromise = null
    })
  return teachersPromise
}

// Локально добавить только что введённого преподавателя в кэш,
// чтобы он сразу предлагался в других формах без перезагрузки.
export function rememberTeacher(name) {
  const trimmed = (name || '').trim()
  if (!trimmed) return
  if (!teachersCache) teachersCache = []
  const exists = teachersCache.some(t => t.toLowerCase() === trimmed.toLowerCase())
  if (!exists) {
    teachersCache = [...teachersCache, trimmed].sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: 'base' })
    )
  }
}

export default function TeacherAutocomplete({ value, onChange, placeholder, id }) {
  const [teachers, setTeachers] = useState(teachersCache || [])
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const wrapRef = useRef(null)

  useEffect(() => {
    let mounted = true
    loadTeachers().then(list => {
      if (mounted) setTeachers(list)
    })
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    function onDocClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const query = (value || '').trim().toLowerCase()
  const suggestions = teachers.filter(t => {
    if (!query) return true
    return t.toLowerCase().includes(query)
  })

  function pick(name) {
    onChange(name)
    setOpen(false)
    setHighlight(-1)
  }

  function handleKeyDown(e) {
    if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      setOpen(true)
      return
    }
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight(h => Math.min(h + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight(h => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      if (highlight >= 0 && highlight < suggestions.length) {
        e.preventDefault()
        pick(suggestions[highlight])
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
      setHighlight(-1)
    }
  }

  return (
    <div className="teacher-autocomplete" ref={wrapRef}>
      <input
        id={id}
        value={value}
        autoComplete="off"
        placeholder={placeholder || 'Ф.И.О.'}
        onChange={e => {
          onChange(e.target.value)
          setOpen(true)
          setHighlight(-1)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {open && suggestions.length > 0 && (
        <ul className="teacher-autocomplete-list" role="listbox">
          {suggestions.map((t, i) => (
            <li
              key={t}
              role="option"
              aria-selected={i === highlight}
              className={'teacher-autocomplete-item' + (i === highlight ? ' is-active' : '')}
              onMouseDown={e => {
                e.preventDefault()
                pick(t)
              }}
              onMouseEnter={() => setHighlight(i)}
            >
              {t}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
