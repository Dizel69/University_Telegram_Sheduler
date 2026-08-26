import React, { useEffect, useRef, useState } from 'react'
import { isEmptyFormattedText, serializeTelegramHtml, toSafeDisplayHtml } from './telegramHtml'

function FormatBtn({ title, active, onClick, children }) {
  return (
    <button
      type="button"
      className={'format-btn' + (active ? ' is-active' : '')}
      title={title}
      aria-label={title}
      aria-pressed={active ? 'true' : 'false'}
      onMouseDown={e => e.preventDefault()}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function IconSpoiler() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <rect x="1.5" y="3.5" width="13" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 1.5" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" />
    </svg>
  )
}

function IconCode() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <path d="M6.2 3.2 2.4 8l3.8 4.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9.8 3.2 13.6 8l-3.8 4.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconPre() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <path d="M3 4h10M3 8h7M3 12h10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function IconQuote() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <path d="M3 6.5c0-1.7 1.2-3 3-3v2.2c-.7 0-1.3.6-1.3 1.3H7V13H3V6.5zm6.5 0c0-1.7 1.2-3 3-3v2.2c-.7 0-1.3.6-1.3 1.3H14V13H10V6.5z" fill="currentColor" />
    </svg>
  )
}

function IconLink() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <path d="M7 9.2a3 3 0 0 0 4.2.2l1.8-1.8a3 3 0 0 0-4.2-4.2L7.6 4.6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M9 6.8a3 3 0 0 0-4.2-.2L3 8.4a3 3 0 0 0 4.2 4.2l1.2-1.2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function closestInEditor(editor, node, predicate) {
  let el = node && node.nodeType === Node.TEXT_NODE ? node.parentElement : node
  while (el && el !== editor) {
    if (el.nodeType === Node.ELEMENT_NODE && predicate(el)) return el
    el = el.parentElement
  }
  return null
}

function unwrap(el) {
  const parent = el.parentNode
  if (!parent) return
  while (el.firstChild) parent.insertBefore(el.firstChild, el)
  parent.removeChild(el)
}

function placeCaretInside(el) {
  const sel = window.getSelection()
  const range = document.createRange()
  if (!el.childNodes.length) el.appendChild(document.createTextNode('\u200B'))
  const target = el.firstChild
  if (target.nodeType === Node.TEXT_NODE) {
    range.setStart(target, Math.min(1, target.textContent.length))
  } else {
    range.selectNodeContents(el)
  }
  range.collapse(true)
  sel.removeAllRanges()
  sel.addRange(range)
}

function wrapSelection(createEl) {
  const sel = window.getSelection()
  if (!sel.rangeCount) return null
  const range = sel.getRangeAt(0)
  const el = createEl()
  if (range.collapsed) {
    el.appendChild(document.createTextNode('\u200B'))
    range.insertNode(el)
    placeCaretInside(el)
    return el
  }
  try {
    range.surroundContents(el)
  } catch {
    el.appendChild(range.extractContents())
    range.insertNode(el)
  }
  const after = document.createRange()
  after.selectNodeContents(el)
  sel.removeAllRanges()
  sel.addRange(after)
  return el
}

function normalizeHref(raw) {
  const href = String(raw || '').trim()
  if (!href) return ''
  if (/^(https?:\/\/|tg:\/\/)/i.test(href)) return href
  return `https://${href}`
}

export function FormattedBody({ html, className = '', style, maxChars }) {
  if (maxChars) {
    const plain = (html ? html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ') : '').replace(/\u200B/g, '').trim()
    if (plain.length > maxChars) {
      return <div className={className} style={style}>{plain.slice(0, maxChars)}…</div>
    }
  }
  const safe = toSafeDisplayHtml(html)
  if (!safe) return <div className={className} style={style} />
  return (
    <div
      className={['formatted-body', className].filter(Boolean).join(' ')}
      style={style}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  )
}

const EditorSurface = React.memo(function EditorSurface({
  editorRef,
  placeholder,
  initialHtml,
  handlersRef,
}) {
  return (
    <div
      ref={editorRef}
      className={'format-editor' + (isEmptyFormattedText(initialHtml) ? ' is-empty' : '')}
      contentEditable
      role="textbox"
      aria-multiline="true"
      data-placeholder={placeholder || ''}
      suppressContentEditableWarning
      dangerouslySetInnerHTML={{ __html: initialHtml }}
      onInput={() => handlersRef.current.emit()}
      onKeyDown={e => handlersRef.current.onKeyDown(e)}
      onPaste={e => handlersRef.current.onPaste(e)}
      onMouseUp={() => handlersRef.current.syncActive()}
      onKeyUp={() => handlersRef.current.syncActive()}
    />
  )
}, () => true)

export default function FormattedTextEditor({ value, onChange, placeholder }) {
  const editorRef = useRef(null)
  const initialHtmlRef = useRef(value || '')
  const onChangeRef = useRef(onChange)
  const handlersRef = useRef({})
  const [active, setActive] = useState({})
  onChangeRef.current = onChange

  function emit() {
    const el = editorRef.current
    if (!el) return
    const html = serializeTelegramHtml(el)
    el.classList.toggle('is-empty', isEmptyFormattedText(html))
    if (onChangeRef.current) onChangeRef.current(html)
    syncActive()
  }

  function syncActive() {
    const editor = editorRef.current
    const sel = window.getSelection()
    if (!editor || !sel || !sel.anchorNode || !editor.contains(sel.anchorNode)) return
    const next = {}
    try {
      next.bold = document.queryCommandState('bold')
      next.italic = document.queryCommandState('italic')
      next.underline = document.queryCommandState('underline')
      next.strike = document.queryCommandState('strikeThrough')
    } catch {
      /* ignore */
    }
    next.spoiler = !!closestInEditor(editor, sel.anchorNode, n => n.tagName === 'TG-SPOILER' || n.classList.contains('tg-spoiler'))
    next.code = !!closestInEditor(editor, sel.anchorNode, n => n.tagName === 'CODE' && n.parentElement?.tagName !== 'PRE')
    next.pre = !!closestInEditor(editor, sel.anchorNode, n => n.tagName === 'PRE')
    next.quote = !!closestInEditor(editor, sel.anchorNode, n => n.tagName === 'BLOCKQUOTE')
    next.link = !!closestInEditor(editor, sel.anchorNode, n => n.tagName === 'A')
    setActive(next)
  }

  function focusEditor() {
    const el = editorRef.current
    if (!el) return
    el.focus()
    try {
      document.execCommand('styleWithCSS', false, false)
    } catch {
      /* ignore */
    }
  }

  function runCommand(cmd) {
    focusEditor()
    document.execCommand(cmd, false, null)
    emit()
  }

  function toggleInline(tagName, className, isMatch) {
    focusEditor()
    const editor = editorRef.current
    const sel = window.getSelection()
    if (!editor || !sel || !sel.rangeCount) return
    const existing = closestInEditor(editor, sel.anchorNode, isMatch)
    if (existing) {
      unwrap(existing)
      emit()
      return
    }
    wrapSelection(() => {
      const el = document.createElement(tagName)
      if (className) el.className = className
      return el
    })
    emit()
  }

  function toggleSpoiler() {
    toggleInline('span', 'tg-spoiler', n => n.tagName === 'TG-SPOILER' || n.classList.contains('tg-spoiler'))
  }

  function toggleCode() {
    toggleInline('code', null, n => n.tagName === 'CODE' && n.parentElement?.tagName !== 'PRE')
  }

  function togglePre() {
    toggleInline('pre', null, n => n.tagName === 'PRE')
  }

  function toggleQuote() {
    toggleInline('blockquote', null, n => n.tagName === 'BLOCKQUOTE')
  }

  function toggleLink() {
    focusEditor()
    const editor = editorRef.current
    const sel = window.getSelection()
    if (!editor || !sel || !sel.rangeCount) return
    const existing = closestInEditor(editor, sel.anchorNode, n => n.tagName === 'A')
    if (existing) {
      unwrap(existing)
      emit()
      return
    }
    const raw = window.prompt('Адрес ссылки', 'https://')
    if (raw == null) return
    const href = normalizeHref(raw)
    if (!href) return
    const range = sel.getRangeAt(0)
    if (range.collapsed) {
      const a = document.createElement('a')
      a.setAttribute('href', href)
      a.textContent = href
      range.insertNode(a)
    } else {
      document.execCommand('createLink', false, href)
    }
    emit()
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      document.execCommand('insertLineBreak')
      emit()
      return
    }
    const mod = e.ctrlKey || e.metaKey
    if (!mod) return
    const key = e.key.toLowerCase()
    if (key === 'b') {
      e.preventDefault()
      runCommand('bold')
    } else if (key === 'i') {
      e.preventDefault()
      runCommand('italic')
    } else if (key === 'u') {
      e.preventDefault()
      runCommand('underline')
    } else if (key === 'x' && e.shiftKey) {
      e.preventDefault()
      runCommand('strikeThrough')
    } else if (key === 'k') {
      e.preventDefault()
      toggleLink()
    }
  }

  function onPaste(e) {
    e.preventDefault()
    const html = e.clipboardData.getData('text/html')
    const text = e.clipboardData.getData('text/plain')
    focusEditor()
    if (html) {
      const safe = toSafeDisplayHtml(html)
      document.execCommand('insertHTML', false, safe || escapePlain(text))
    } else {
      document.execCommand('insertText', false, text)
    }
    emit()
  }

  function escapePlain(text) {
    return String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
  }

  useEffect(() => {
    const el = editorRef.current
    if (!el) return
    const current = serializeTelegramHtml(el)
    if (current === (value || '')) return
    el.innerHTML = value || ''
    el.classList.toggle('is-empty', isEmptyFormattedText(value))
  }, [value])

  useEffect(() => {
    const onSel = () => handlersRef.current.syncActive()
    document.addEventListener('selectionchange', onSel)
    return () => document.removeEventListener('selectionchange', onSel)
  }, [])

  handlersRef.current = { emit, onKeyDown, onPaste, syncActive }

  return (
    <div className="format-editor-wrap">
      <div className="format-toolbar" role="toolbar" aria-label="Форматирование текста">
        <FormatBtn title="Жирный (Ctrl+B)" active={active.bold} onClick={() => runCommand('bold')}>
          <span className="format-letter format-letter-b">Ж</span>
        </FormatBtn>
        <FormatBtn title="Курсив (Ctrl+I)" active={active.italic} onClick={() => runCommand('italic')}>
          <span className="format-letter format-letter-i">К</span>
        </FormatBtn>
        <FormatBtn title="Подчёркнутый (Ctrl+U)" active={active.underline} onClick={() => runCommand('underline')}>
          <span className="format-letter format-letter-u">Ч</span>
        </FormatBtn>
        <FormatBtn title="Зачёркнутый (Ctrl+Shift+X)" active={active.strike} onClick={() => runCommand('strikeThrough')}>
          <span className="format-letter format-letter-s">abc</span>
        </FormatBtn>
        <span className="format-sep" />
        <FormatBtn title="Спойлер" active={active.spoiler} onClick={toggleSpoiler}>
          <IconSpoiler />
        </FormatBtn>
        <FormatBtn title="Моноширинный (код)" active={active.code} onClick={toggleCode}>
          <IconCode />
        </FormatBtn>
        <FormatBtn title="Блок кода" active={active.pre} onClick={togglePre}>
          <IconPre />
        </FormatBtn>
        <FormatBtn title="Цитата" active={active.quote} onClick={toggleQuote}>
          <IconQuote />
        </FormatBtn>
        <FormatBtn title="Ссылка (Ctrl+K)" active={active.link} onClick={toggleLink}>
          <IconLink />
        </FormatBtn>
      </div>
      <EditorSurface
        editorRef={editorRef}
        placeholder={placeholder}
        initialHtml={initialHtmlRef.current}
        handlersRef={handlersRef}
      />
    </div>
  )
}
