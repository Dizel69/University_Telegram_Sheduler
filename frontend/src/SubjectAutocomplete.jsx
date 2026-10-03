import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import axios from 'axios'

export default function SubjectAutocomplete({ value, onChange, placeholder, id }) {
  const [subjects, setSubjects] = useState([])
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(-1)
  const [box, setBox] = useState(null)
  const wrapRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const antiAutofill = useRef('sac-' + Math.random().toString(36).slice(2, 10))

  useEffect(() => {
    let mounted = true
    axios
      .get('/subjects')
      .then(res => {
        if (mounted) setSubjects(Array.isArray(res.data) ? res.data : [])
      })
      .catch(() => {
        if (mounted) setSubjects([])
      })
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    function onDocClick(e) {
      const target = e.target
      if (wrapRef.current?.contains(target) || listRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const query = (value || '').trim().toLowerCase()
  const suggestions = subjects.filter(name => {
    if (!query) return true
    return name.toLowerCase().includes(query)
  })

  useLayoutEffect(() => {
    if (!open) return undefined
    function place() {
      const el = inputRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      setBox({ top: rect.bottom + 4, left: rect.left, width: rect.width })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, suggestions.length, value])

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

  const list = open && suggestions.length > 0 && box
    ? createPortal(
      <ul
        ref={listRef}
        className="subject-autocomplete-list"
        role="listbox"
        style={{ position: 'fixed', top: box.top, left: box.left, width: box.width, right: 'auto' }}
      >
        {suggestions.map((name, i) => (
          <li
            key={name}
            role="option"
            aria-selected={i === highlight}
            className={'subject-autocomplete-item' + (i === highlight ? ' is-active' : '')}
            onMouseDown={e => {
              e.preventDefault()
              pick(name)
            }}
            onMouseEnter={() => setHighlight(i)}
          >
            {name}
          </li>
        ))}
      </ul>,
      document.body,
    )
    : null

  return (
    <div className={'subject-autocomplete' + (open ? ' is-open' : '')} ref={wrapRef}>
      <input
        ref={inputRef}
        id={id}
        name={antiAutofill.current}
        value={value}
        autoComplete={antiAutofill.current}
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        data-lpignore="true"
        data-1p-ignore="true"
        data-form-type="other"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        placeholder={placeholder || 'Например: Математика'}
        onChange={e => {
          onChange(e.target.value)
          setOpen(true)
          setHighlight(-1)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {list}
    </div>
  )
}
