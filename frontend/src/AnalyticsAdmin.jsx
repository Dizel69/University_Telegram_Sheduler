import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

function ymdFromDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function mondayOfWeekContaining(ymdOrDate) {
  let d
  if (typeof ymdOrDate === 'string') {
    const [y, m, day] = ymdOrDate.split('-').map(Number)
    d = new Date(y, m - 1, day)
  } else {
    d = new Date(ymdOrDate)
  }
  const fromMon = (d.getDay() + 6) % 7
  const mon = new Date(d)
  mon.setDate(d.getDate() - fromMon)
  return mon
}

function ymdToday() {
  return ymdFromDate(new Date())
}

function formatDdMm(ymd) {
  if (!ymd) return ''
  const s = String(ymd).slice(0, 10)
  const [y, m, d] = s.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  return `${String(dt.getDate()).padStart(2, '0')}.${String(dt.getMonth() + 1).padStart(2, '0')}`
}

function addDaysYmd(ymd, delta) {
  const [y, m, d] = ymd.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + delta)
  return ymdFromDate(dt)
}

function pct(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${Number(n).toFixed(1)}%`
}

function KpiCard({ label, value, hint, tone }) {
  return (
    <div className={`analytics-kpi-card${tone ? ` analytics-kpi-${tone}` : ''}`}>
      <div className="analytics-kpi-value">{value}</div>
      <div className="analytics-kpi-label">{label}</div>
      {hint ? <div className="analytics-kpi-hint">{hint}</div> : null}
    </div>
  )
}

function MiniBarChart({ points, field, color, max = 100 }) {
  if (!points?.length) {
    return <p className="status">Нет данных за выбранный период</p>
  }
  const peak = Math.max(max, ...points.map(p => p[field] || 0), 1)
  return (
    <div className="analytics-bars" role="img" aria-label="График по неделям">
      {points.map(p => {
        const v = p[field] || 0
        const h = Math.round((v / peak) * 100)
        const ws = String(p.week_start).slice(0, 10)
        return (
          <div key={ws} className="analytics-bar-col" title={`${formatDdMm(ws)}: ${pct(v)}`}>
            <div className="analytics-bar-value">{pct(v)}</div>
            <div className="analytics-bar-track">
              <div
                className="analytics-bar-fill"
                style={{ height: `${h}%`, background: color }}
              />
            </div>
            <div className="analytics-bar-label">{formatDdMm(ws)}</div>
          </div>
        )
      })}
    </div>
  )
}

export default function AnalyticsAdmin({ currentSemester }) {
  const [period, setPeriod] = useState('week')
  const [weekMonday, setWeekMonday] = useState(() => ymdFromDate(mondayOfWeekContaining(ymdToday())))
  const [monthYear, setMonthYear] = useState(() => {
    const t = new Date()
    return { year: t.getFullYear(), month: t.getMonth() + 1 }
  })
  const [useSemesterFilter, setUseSemesterFilter] = useState(false)
  const [filterUserId, setFilterUserId] = useState('')
  const [filterSubject, setFilterSubject] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const hasActiveFilters = Boolean(filterUserId || filterSubject)

  const periodLabel = useMemo(() => {
    if (!data) return ''
    if (data.period === 'month') {
      const [y, m] = String(data.period_start).slice(0, 10).split('-')
      const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
      return `${months[Number(m) - 1]} ${y}`
    }
    if (data.period === 'all') return 'всё время'
    return `${formatDdMm(data.period_start)}–${formatDdMm(data.period_end)}`
  }, [data])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    const params = { period }
    if (period === 'week') params.week_start = weekMonday
    if (period === 'month') {
      params.year = monthYear.year
      params.month = monthYear.month
    }
    if (useSemesterFilter && currentSemester) params.semester = currentSemester
    if (filterUserId) params.user_id = Number(filterUserId)
    if (filterSubject) params.subject = filterSubject
    try {
      const { data: res } = await axios.get('/admin/analytics', { params })
      setData(res)
    } catch (e) {
      setData(null)
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [period, weekMonday, monthYear, useSemesterFilter, currentSemester, filterUserId, filterSubject])

  const filterUserLabel = useMemo(() => {
    if (!filterUserId || !data?.users) return null
    const u = data.users.find(x => String(x.id) === String(filterUserId))
    if (!u) return null
    return [u.last_name, u.first_name, u.middle_name].filter(Boolean).join(' ')
  }, [filterUserId, data?.users])

  const subjectOptions = useMemo(() => {
    const fromApi = data?.available_subjects || []
    if (filterSubject && !fromApi.includes(filterSubject)) {
      return [filterSubject, ...fromApi].sort((a, b) => a.localeCompare(b, 'ru'))
    }
    return fromApi
  }, [data?.available_subjects, filterSubject])

  function resetFilters() {
    setFilterUserId('')
    setFilterSubject('')
  }

  useEffect(() => {
    load()
  }, [load])

  function goPrevWeek() {
    setWeekMonday(w => addDaysYmd(w, -7))
  }

  function goNextWeek() {
    setWeekMonday(w => addDaysYmd(w, 7))
  }

  function shiftMonth(delta) {
    setMonthYear(prev => {
      let m = prev.month + delta
      let y = prev.year
      while (m < 1) { m += 12; y -= 1 }
      while (m > 12) { m -= 12; y += 1 }
      return { year: y, month: m }
    })
  }

  const kpi = data?.kpi
  const students = data?.students || []
  const subjAtt = data?.subjects_attendance || []
  const subjHw = data?.subjects_homework || []
  const trend = data?.weekly_trend || []
  const tg = data?.telegram

  return (
    <div className="card analytics-card">
      <h2>Аналитика</h2>
      <p className="status" style={{ marginTop: 4 }}>
        Сводка по посещаемости, домашним заданиям и активности группы. Владелец в расчётах не участвует.
      </p>

      <div className="analytics-toolbar">
        <div className="analytics-period-tabs" role="tablist" aria-label="Период">
          {[
            ['week', 'Неделя'],
            ['month', 'Месяц'],
            ['all', 'Всё время'],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={period === id}
              className={period === id ? 'tab active' : 'tab'}
              onClick={() => setPeriod(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {period === 'week' && (
          <div className="attendance-week-nav" role="group" aria-label="Неделя">
            <button type="button" className="btn attendance-week-arrow" onClick={goPrevWeek} disabled={loading}>
              ←
            </button>
            <span className="attendance-week-range">
              {formatDdMm(weekMonday)}–{formatDdMm(addDaysYmd(weekMonday, 6))}
            </span>
            <button type="button" className="btn attendance-week-arrow" onClick={goNextWeek} disabled={loading}>
              →
            </button>
          </div>
        )}

        {period === 'month' && (
          <div className="analytics-month-nav">
            <button type="button" className="btn attendance-week-arrow" onClick={() => shiftMonth(-1)} disabled={loading}>
              ←
            </button>
            <span className="attendance-week-range">
              {String(monthYear.month).padStart(2, '0')}.{monthYear.year}
            </span>
            <button type="button" className="btn attendance-week-arrow" onClick={() => shiftMonth(1)} disabled={loading}>
              →
            </button>
          </div>
        )}

        {currentSemester ? (
          <label className="analytics-semester-filter">
            <input
              type="checkbox"
              checked={useSemesterFilter}
              onChange={e => setUseSemesterFilter(e.target.checked)}
            />
            ДЗ только: {currentSemester}
          </label>
        ) : null}

        <button type="button" className="btn btn-sm" onClick={load} disabled={loading}>
          Обновить
        </button>
      </div>

      <div className="analytics-filters-panel">
        <h3 className="analytics-filters-title">Фильтры</h3>
        <div className="analytics-filters-grid">
          <label className="analytics-filter-field">
            <span className="label">Студент</span>
            <select
              value={filterUserId}
              onChange={e => setFilterUserId(e.target.value)}
              disabled={loading && !data}
            >
              <option value="">Вся группа</option>
              {(data?.users || []).map(u => (
                <option key={u.id} value={String(u.id)}>
                  {[u.last_name, u.first_name, u.middle_name].filter(Boolean).join(' ')}
                </option>
              ))}
            </select>
          </label>
          <label className="analytics-filter-field">
            <span className="label">Предмет</span>
            <select
              value={filterSubject}
              onChange={e => setFilterSubject(e.target.value)}
              disabled={loading && !data}
            >
              <option value="">Все предметы</option>
              {subjectOptions.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          {hasActiveFilters ? (
            <div className="analytics-filter-actions">
              <button type="button" className="btn btn-sm" onClick={resetFilters} disabled={loading}>
                Сбросить фильтры
              </button>
            </div>
          ) : null}
        </div>
        <p className="status analytics-filters-hint">
          KPI, графики и топы пересчитываются по выбранным фильтрам. Таблица студентов показывает всех для сравнения.
        </p>
      </div>

      {loading && <div style={{ marginTop: 16 }}>Загрузка…</div>}
      {error && <div className="error" style={{ marginTop: 16 }}>{String(error)}</div>}

      {!loading && !error && data && (
        <>
          <p className="analytics-period-caption">
            Период: <strong>{periodLabel}</strong>
            {data.semester_filter ? (
              <> · фильтр ДЗ: <strong>{data.semester_filter}</strong></>
            ) : null}
            {filterUserLabel ? (
              <> · студент: <strong>{filterUserLabel}</strong></>
            ) : null}
            {data.subject_filter ? (
              <> · предмет: <strong>{data.subject_filter}</strong></>
            ) : null}
          </p>

          <div className="analytics-kpi-grid">
            <KpiCard
              label="Посещаемость"
              value={pct(kpi?.attendance_rate)}
              hint={kpi?.attendance_slots ? `${kpi.attendance_slots} ячеек` : 'нет пар'}
              tone="blue"
            />
            <KpiCard
              label="Выполнение ДЗ"
              value={pct(kpi?.homework_completion_rate)}
              hint={
                filterUserLabel
                  ? filterUserLabel
                  : data.subject_filter
                    ? data.subject_filter
                    : 'по группе'
              }
              tone="green"
            />
            <KpiCard
              label="Просрочено ДЗ"
              value={kpi?.overdue_homework ?? 0}
              hint="студент × задание"
              tone={kpi?.overdue_homework > 0 ? 'warn' : undefined}
            />
            <KpiCard
              label="Пропуски (Н)"
              value={kpi?.absent_marks ?? 0}
              hint={`болеет (Б): ${kpi?.sick_marks ?? 0}`}
            />
            <KpiCard
              label="Пар в периоде"
              value={kpi?.lessons_in_period ?? 0}
              hint={`переносов: ${kpi?.transfers ?? 0}`}
            />
            <KpiCard
              label="Посты в Telegram"
              value={pct(tg?.posts_sent_rate)}
              hint={`${tg?.posts_sent ?? 0} / ${tg?.posts_attempted ?? 0}`}
            />
          </div>

          <section className="analytics-section">
            <h3>Динамика за 8 недель</h3>
            <div className="analytics-charts-row">
              <div className="analytics-chart-block">
                <h4>Посещаемость</h4>
                <MiniBarChart points={trend} field="attendance_rate" color="#3b82f6" />
              </div>
              <div className="analytics-chart-block">
                <h4>Домашние задания</h4>
                <MiniBarChart points={trend} field="homework_rate" color="#10b981" />
              </div>
            </div>
          </section>

          <section className="analytics-section">
            <h3>Студенты</h3>
            {students.length === 0 ? (
              <p className="status">Нет пользователей для статистики.</p>
            ) : (
              <div className="analytics-table-wrap">
                <table className="analytics-table">
                  <thead>
                    <tr>
                      <th>ФИО</th>
                      <th>Посещаемость</th>
                      <th>ДЗ</th>
                      <th>Н</th>
                      <th>Б</th>
                    </tr>
                  </thead>
                  <tbody>
                    {students.map(s => (
                      <tr
                        key={s.user_id}
                        className={
                          filterUserId && String(s.user_id) === String(filterUserId)
                            ? 'analytics-row-highlight'
                            : ''
                        }
                      >
                        <th scope="row">{s.name}</th>
                        <td>
                          <span className="analytics-pill analytics-pill-blue">{pct(s.attendance_rate)}</span>
                        </td>
                        <td>
                          <span className="analytics-pill analytics-pill-green">
                            {s.homework_done}/{s.homework_total} ({pct(s.homework_rate)})
                          </span>
                        </td>
                        <td>{s.absent}</td>
                        <td>{s.sick}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="analytics-two-cols">
            <section className="analytics-section">
              <h3>Топ пропусков по предметам</h3>
              {subjAtt.length === 0 ? (
                <p className="status">Нет отметок Н/Б за период.</p>
              ) : (
                <ul className="analytics-rank-list">
                  {subjAtt.map((row, i) => (
                    <li key={row.subject}>
                      <span className="analytics-rank-num">{i + 1}</span>
                      <span className="analytics-rank-subj">{row.subject}</span>
                      <span className="analytics-rank-stats">
                        Н: {row.absent} · Б: {row.sick}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="analytics-section">
              <h3>ДЗ: больше всего не сдано</h3>
              {subjHw.length === 0 ? (
                <p className="status">Нет домашних заданий за период.</p>
              ) : (
                <ul className="analytics-rank-list">
                  {subjHw.map((row, i) => {
                    const open = row.homework_total - row.homework_done
                    return (
                      <li key={row.subject}>
                        <span className="analytics-rank-num">{i + 1}</span>
                        <span className="analytics-rank-subj">{row.subject}</span>
                        <span className="analytics-rank-stats">
                          не сдано: {open} / {row.homework_total}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </div>

          <section className="analytics-section analytics-telegram-block">
            <h3>Telegram</h3>
            <div className="analytics-telegram-grid">
              <div>
                <strong>Публикации</strong>
                <p className="status">
                  Отправлено {tg?.posts_sent ?? 0} из {tg?.posts_attempted ?? 0} ({pct(tg?.posts_sent_rate)})
                </p>
              </div>
              <div>
                <strong>Напоминания</strong>
                <p className="status">
                  Отправлено: {tg?.reminders_sent ?? 0}, ожидают: {tg?.reminders_pending ?? 0} ({pct(tg?.reminders_sent_rate)})
                </p>
              </div>
            </div>
            <p className="status" style={{ marginTop: 8, fontSize: 12 }}>
              Учитываются события с датой в периоде и source=admin (посты через «Создать» / send).
            </p>
          </section>
        </>
      )}
    </div>
  )
}
