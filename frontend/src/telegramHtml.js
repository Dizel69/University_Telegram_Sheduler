const MARKUP_RE = /<(b|strong|i|em|u|ins|s|strike|del|code|pre|a|blockquote|tg-spoiler|span)\b/i

export function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

export function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;')
}

export function htmlToPlainText(html) {
  if (!html) return ''
  const el = document.createElement('div')
  el.innerHTML = html
  return (el.textContent || '').replace(/\u200B/g, '')
}

export function isEmptyFormattedText(html) {
  return !htmlToPlainText(html).trim()
}

function isBoldEl(el) {
  if (el.tagName === 'B' || el.tagName === 'STRONG') return true
  const w = el.style && el.style.fontWeight
  return w === 'bold' || w === '700' || w === '800' || w === '900' || parseInt(w, 10) >= 600
}

function isItalicEl(el) {
  if (el.tagName === 'I' || el.tagName === 'EM') return true
  return el.style && el.style.fontStyle === 'italic'
}

function decoHas(el, name) {
  const deco = `${el.style?.textDecoration || ''} ${el.style?.textDecorationLine || ''}`.toLowerCase()
  return deco.includes(name)
}

function isUnderlineEl(el) {
  if (el.tagName === 'U' || el.tagName === 'INS') return true
  return decoHas(el, 'underline')
}

function isStrikeEl(el) {
  if (el.tagName === 'S' || el.tagName === 'STRIKE' || el.tagName === 'DEL') return true
  return decoHas(el, 'line-through')
}

function isSpoilerEl(el) {
  if (el.tagName === 'TG-SPOILER') return true
  return el.classList && el.classList.contains('tg-spoiler')
}

function wrapTag(inner, tag) {
  return `<${tag}>${inner}</${tag}>`
}

function serializeNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return escapeHtml((node.textContent || '').replace(/\u200B/g, ''))
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return ''

  const tag = node.tagName.toLowerCase()
  if (tag === 'br') return '\n'

  let inner = Array.from(node.childNodes).map(serializeNode).join('')

  if (tag === 'code') inner = wrapTag(inner, 'code')
  else if (tag === 'pre') inner = wrapTag(inner, 'pre')
  else if (isSpoilerEl(node)) inner = wrapTag(inner, 'tg-spoiler')

  if (tag === 'a') {
    const href = (node.getAttribute('href') || '').trim()
    if (/^(https?:\/\/|tg:\/\/)/i.test(href)) {
      inner = `<a href="${escapeAttr(href)}">${inner}</a>`
    }
  }

  if (tag === 'blockquote') {
    const expandable = node.hasAttribute('expandable')
    inner = expandable ? `<blockquote expandable>${inner}</blockquote>` : wrapTag(inner, 'blockquote')
  }

  if (isBoldEl(node)) inner = wrapTag(inner, 'b')
  if (isItalicEl(node)) inner = wrapTag(inner, 'i')
  if (isUnderlineEl(node)) inner = wrapTag(inner, 'u')
  if (isStrikeEl(node)) inner = wrapTag(inner, 's')

  if (tag === 'div' || tag === 'p' || tag === 'li') {
    if (!inner) return '\n'
    return inner.endsWith('\n') ? inner : `${inner}\n`
  }
  return inner
}

export function serializeTelegramHtml(root) {
  if (!root) return ''
  return Array.from(root.childNodes).map(serializeNode).join('').replace(/\n+$/, '')
}

export function toSafeDisplayHtml(html) {
  if (!html) return ''
  if (!MARKUP_RE.test(html)) return escapeHtml(html)
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const root = doc.body && doc.body.firstChild
  if (!root) return escapeHtml(html)
  return serializeTelegramHtml(root).replace(/<tg-spoiler>/g, '<span class="tg-spoiler">').replace(/<\/tg-spoiler>/g, '</span>')
}
