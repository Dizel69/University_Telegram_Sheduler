import React, { useEffect, useMemo, useRef, useState } from 'react'
import { FormattedBody } from './FormattedTextEditor'
import { eventTemporalClass, isOngoingEvent } from './eventTime'
import {
  eventColor,
  examKindIcon,
  filterVisibleEvents,
  formatAgendaDayLabel,
  formatTimeRange,
  isoFromUtcDate,
  isOutsideMonth,
  lessonIcon,
  localIsoDate,
  typeLabel,
  WEEKDAYS_NARROW,
  WEEKDAYS_SHORT,
} from './calendarUi'

function weekSlice(days, iso) {
  const idx = days.findIndex((d) => d && isoFromUtcDate(d) === iso)
  const start = idx >= 0 ? Math.floor(idx / 7) * 7 : 0
  const slice = days.slice(start, start + 7)
  while (slice.length < 7) slice.push(null)
  return slice
}

function uniqueEventDots(evs) {
  const seen = []
  for (const ev of evs) {
    const c = eventColor(ev)
    if (!seen.includes(c)) seen.push(c)
    if (seen.length >= 3) break
  }
  return seen
}

function AgendaEventCard({
  ev,
  nowMs,
  expanded,
  onToggle,
  isAdmin,
  onEdit,
  onTransfer,
  onDelete,
  onSendNow,
}) {
  const temporal = eventTemporalClass(ev, nowMs)
  const ongoing = isOngoingEvent(ev, nowMs)
  const color = eventColor(ev)
  const time = formatTimeRange(ev.time, ev.end_time)
  const title = ev.title || ev.subject || typeLabel(ev.type)
  const icon = ev.type === 'schedule'
    ? lessonIcon(ev.lesson_type)
    : ev.type === 'exam_control'
      ? examKindIcon(ev.lesson_type)
      : ''

  return (
    <article
      id={`agenda-ev-${ev.id}`}
      className={'agenda-ev' + (temporal ? ` ${temporal}` : '') + (expanded ? ' is-open' : '')}
    >
      <div className="agenda-ev-bar" style={{ background: color }} />
      <button type="button" className="agenda-ev-main" onClick={onToggle}>
        <div className="agenda-ev-top">
          <div className="agenda-ev-time-row">
            {time ? <span className="agenda-ev-time">{time}</span> : <span className="agenda-ev-time is-muted">Весь день</span>}
            {ongoing ? <span className="cal-ev-now">сейчас</span> : null}
          </div>
          <span className="agenda-ev-type" style={{ background: color, color: ev.type === 'birthday' ? '#713f12' : '#fff' }}>
            {typeLabel(ev.type)}
          </span>
        </div>
        <div className="agenda-ev-title">
          {icon ? <span className="agenda-ev-icon">{icon}</span> : null}
          {title}
        </div>
        {(ev.room || ev.teacher) ? (
          <div className="agenda-ev-meta">
            {ev.room ? <span>ауд. {ev.room}</span> : null}
            {ev.room && ev.teacher ? <span className="agenda-ev-dot">·</span> : null}
            {ev.teacher ? <span>{ev.teacher}</span> : null}
          </div>
        ) : null}
        {!expanded && ev.body ? (
          <FormattedBody html={ev.body} className="agenda-ev-preview" maxChars={90} />
        ) : null}
      </button>
      {expanded ? (
        <div className="agenda-ev-details">
          <FormattedBody html={ev.body} className="event-body agenda-ev-body" />
          {ev.teacher ? <div className="agenda-ev-teacher">Преподаватель: {ev.teacher}</div> : null}
          {isAdmin && ev.type !== 'birthday' ? (
            <div className="actions-wrap agenda-ev-actions">
              <button type="button" className="btn btn-sm" onClick={() => onSendNow(ev)}>Отправить сейчас</button>
              <button type="button" className="btn btn-sm" onClick={() => onEdit(ev)}>Редактировать</button>
              <button type="button" className="btn btn-sm" onClick={() => onTransfer(ev)}>Перенести</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={() => onDelete(ev)}>Удалить</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

export default function CalendarAgenda({
  year,
  month,
  days,
  events,
  showHomework,
  dayHighlightBg,
  nowMs,
  isAdmin,
  pin,
  onGoToDate,
  onEditEvent,
  onTransferEvent,
  onDeleteEvent,
  onSendNow,
}) {
  const todayIso = localIsoDate()
  const listRef = useRef(null)
  const barRef = useRef(null)
  const [activeDay, setActiveDay] = useState(todayIso)
  const [monthOpen, setMonthOpen] = useState(false)
  const [expandedId, setExpandedId] = useState(null)

  const monthDays = useMemo(
    () => days.filter((d) => d && !isOutsideMonth(d, month)),
    [days, month],
  )
  const isCurrentMonth = year === new Date().getFullYear() && month === new Date().getMonth()

  const weekDays = useMemo(
    () => weekSlice(days, activeDay),
    [days, activeDay],
  )

  useEffect(() => {
    const bar = barRef.current
    const root = bar?.parentElement
    if (!bar || !root) return undefined
    const apply = () => {
      root.style.setProperty('--agenda-sticky-top', `${bar.offsetHeight}px`)
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(bar)
    return () => ro.disconnect()
  }, [monthOpen, year, month])

  useEffect(() => {
    const nodes = listRef.current?.querySelectorAll('[data-agenda-day]')
    if (!nodes?.length) return undefined
    const io = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (!visible.length) return
      const iso = visible[0].target.getAttribute('data-agenda-day')
      if (iso) setActiveDay(iso)
    }, { root: null, rootMargin: '-96px 0px -62% 0px', threshold: 0.01 })
    nodes.forEach((n) => io.observe(n))
    return () => io.disconnect()
  }, [year, month, monthDays.length, showHomework])

  const hasPinEvent = Boolean(
    pin?.eventId &&
    Object.values(events).some((list) => (list || []).some((e) => e.id === pin.eventId))
  )

  useEffect(() => {
    const firstIso = monthDays[0] ? isoFromUtcDate(monthDays[0]) : null
    const target = pin?.day || (isCurrentMonth ? todayIso : firstIso)
    if (!target) return undefined
    setActiveDay(target)
    if (pin?.eventId) setExpandedId(pin.eventId)

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const behavior = pin?.nonce ? (reduce ? 'auto' : 'smooth') : 'auto'
    const t = window.setTimeout(() => {
      const eventEl = pin?.eventId ? document.getElementById(`agenda-ev-${pin.eventId}`) : null
      const dayEl = document.getElementById(`agenda-day-${target}`)
      const el = eventEl || dayEl
      el?.scrollIntoView({ behavior, block: 'start' })
    }, hasPinEvent || !pin?.eventId ? 40 : 0)
    return () => window.clearTimeout(t)
  }, [year, month, pin?.nonce, pin?.day, pin?.eventId, isCurrentMonth, todayIso, hasPinEvent])

  useEffect(() => {
    if (!monthOpen) return undefined
    const close = () => setMonthOpen(false)
    window.addEventListener('scroll', close, { passive: true })
    return () => window.removeEventListener('scroll', close)
  }, [monthOpen])

  function scrollToDay(iso) {
    setActiveDay(iso)
    setMonthOpen(false)
    const el = document.getElementById(`agenda-day-${iso}`)
    el?.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    })
  }

  function selectDay(iso, dt) {
    if (dt && isOutsideMonth(dt, month) && onGoToDate) {
      onGoToDate(iso)
      return
    }
    scrollToDay(iso)
  }

  return (
    <div className="calendar-agenda">
      <div className="agenda-weekbar" ref={barRef}>
        <div className="agenda-weekbar-main">
        <div className="agenda-weekbar-head">
          {WEEKDAYS_NARROW.map((w, i) => (
            <span key={`${w}-${i}`} className={'agenda-week-wd' + (i >= 5 ? ' is-weekend' : '')}>{w}</span>
          ))}
        </div>
        <div className="agenda-week-days">
          {weekDays.map((dt, i) => {
            if (!dt) return <span key={`e-${i}`} className="agenda-week-cell is-empty" />
            const iso = isoFromUtcDate(dt)
            const evs = filterVisibleEvents(events[iso], showHomework)
            const hlBg = dayHighlightBg(iso)
            const isToday = iso === todayIso
            const isActive = iso === activeDay
            const outside = isOutsideMonth(dt, month)
            return (
              <button
                key={iso}
                type="button"
                className={
                  'agenda-week-cell'
                  + (isToday ? ' is-today' : '')
                  + (isActive ? ' is-active' : '')
                  + (outside ? ' is-outside' : '')
                  + (i >= 5 ? ' is-weekend' : '')
                }
                style={hlBg ? { background: hlBg } : undefined}
                onClick={() => selectDay(iso, dt)}
              >
                <span className="agenda-week-num">{dt.getUTCDate()}</span>
                <span className="agenda-week-dots" aria-hidden="true">
                  {uniqueEventDots(evs).map((c) => (
                    <i key={c} style={{ background: c }} />
                  ))}
                </span>
              </button>
            )
          })}
        </div>
        </div>
        <button
          type="button"
          className={'agenda-month-toggle' + (monthOpen ? ' is-open' : '')}
          onClick={() => setMonthOpen((v) => !v)}
          aria-expanded={monthOpen}
          aria-label={monthOpen ? 'Скрыть месяц' : 'Показать месяц'}
        >
          {monthOpen ? '▴' : '▾'}
        </button>
      </div>

      {monthOpen ? (
        <div className="agenda-mini-month">
          <div className="agenda-mini-weekdays">
            {WEEKDAYS_SHORT.map((w, i) => (
              <span key={w} className={i >= 5 ? 'is-weekend' : ''}>{w}</span>
            ))}
          </div>
          <div className="agenda-mini-grid">
            {days.map((dt, idx) => {
              if (!dt) return <span key={`m-e-${idx}`} className="agenda-mini-cell is-empty" />
              const iso = isoFromUtcDate(dt)
              const evs = filterVisibleEvents(events[iso], showHomework)
              const hlBg = dayHighlightBg(iso)
              const isToday = iso === todayIso
              const isActive = iso === activeDay
              const outside = isOutsideMonth(dt, month)
              return (
                <button
                  key={iso}
                  type="button"
                  className={
                    'agenda-mini-cell'
                    + (isToday ? ' is-today' : '')
                    + (isActive ? ' is-active' : '')
                    + (outside ? ' is-outside' : '')
                  }
                  style={hlBg ? { background: hlBg } : undefined}
                  onClick={() => selectDay(iso, dt)}
                >
                  <span className="agenda-mini-num">{dt.getUTCDate()}</span>
                  <span className="agenda-week-dots" aria-hidden="true">
                    {uniqueEventDots(evs).map((c) => (
                      <i key={c} style={{ background: c }} />
                    ))}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      <div className="agenda-list" ref={listRef}>
        {monthDays.map((dt) => {
          const iso = isoFromUtcDate(dt)
          const label = formatAgendaDayLabel(dt, todayIso)
          const evs = filterVisibleEvents(events[iso], showHomework)
          const hlBg = dayHighlightBg(iso)
          const isToday = iso === todayIso
          const isPast = iso < todayIso
          return (
            <section
              key={iso}
              id={`agenda-day-${iso}`}
              data-agenda-day={iso}
              className={
                'agenda-day'
                + (isToday ? ' is-today' : '')
                + (isPast ? ' is-past-day' : '')
                + (label.isWeekend ? ' is-weekend' : '')
              }
            >
              <header className="agenda-day-head" style={hlBg ? { backgroundColor: 'var(--card)', backgroundImage: `linear-gradient(${hlBg}, ${hlBg})` } : undefined}>
                <div className={'agenda-day-num' + (isToday ? ' is-today' : '')}>{dt.getUTCDate()}</div>
                <div className="agenda-day-label">
                  {label.rel ? <div className="agenda-day-rel">{label.rel}</div> : null}
                  <div className="agenda-day-wd">{label.weekday}, {label.dateText}</div>
                </div>
                {evs.length ? <div className="agenda-day-count">{evs.length}</div> : null}
              </header>
              {evs.length ? (
                <div className="agenda-day-events">
                  {evs.map((ev) => (
                    <AgendaEventCard
                      key={ev.id}
                      ev={ev}
                      nowMs={nowMs}
                      expanded={expandedId === ev.id}
                      onToggle={() => setExpandedId((id) => (id === ev.id ? null : ev.id))}
                      isAdmin={isAdmin}
                      onEdit={onEditEvent}
                      onTransfer={onTransferEvent}
                      onDelete={onDeleteEvent}
                      onSendNow={onSendNow}
                    />
                  ))}
                </div>
              ) : (
                <div className="agenda-day-empty">Пар нет</div>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
