import React, { useEffect, useState } from 'react'
import axios from 'axios'
import PasswordField from './PasswordField'

const MAX_USERS = 8

function formatBirth(d) {
  if (!d) return '—'
  return d
}

export default function UsersAdmin() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')

  const [lastName, setLastName] = useState('')
  const [firstName, setFirstName] = useState('')
  const [middleName, setMiddleName] = useState('')
  const [birthDate, setBirthDate] = useState('')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [isAdminNew, setIsAdminNew] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const { data } = await axios.get('/owner/users')
      setUsers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e.response?.data?.detail || e.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function createUser(e) {
    e.preventDefault()
    setStatus('')
    if (!lastName.trim() || !firstName.trim() || !login.trim() || !password) {
      setStatus('Фамилия, имя, логин и пароль обязательны')
      return
    }
    try {
      await axios.post('/owner/users', {
        last_name: lastName.trim(),
        first_name: firstName.trim(),
        middle_name: middleName.trim() || null,
        birth_date: birthDate || null,
        login: login.trim(),
        password,
        is_admin: isAdminNew,
      })
      setLastName('')
      setFirstName('')
      setMiddleName('')
      setBirthDate('')
      setLogin('')
      setPassword('')
      setIsAdminNew(false)
      setStatus('Пользователь создан')
      await load()
    } catch (e) {
      setStatus(e.response?.data?.detail || e.message || String(e))
    }
  }

  async function toggleAdmin(u, next) {
    setStatus('')
    try {
      await axios.patch(`/owner/users/${u.id}`, { is_admin: next })
      await load()
    } catch (e) {
      setStatus(e.response?.data?.detail || e.message || String(e))
    }
  }

  async function changePassword(u, pwd) {
    if (!pwd.trim()) return
    setStatus('')
    try {
      await axios.patch(`/owner/users/${u.id}`, { password: pwd })
      await load()
      setStatus(`Пароль обновлён (${u.login})`)
    } catch (e) {
      setStatus(e.response?.data?.detail || e.message || String(e))
    }
  }

  async function removeUser(u) {
    if (!window.confirm(`Удалить пользователя «${u.login}»?`)) return
    setStatus('')
    try {
      await axios.delete(`/owner/users/${u.id}`)
      await load()
    } catch (e) {
      setStatus(e.response?.data?.detail || e.message || String(e))
    }
  }

  return (
    <div className="card">
      <h2>Пользователи</h2>
      <p className="status" style={{ marginTop: 4 }}>
        Не больше {MAX_USERS} учётных записей.         Удалять пользователей и выдавать права администратора может только владелец.
      </p>

      {loading && <div style={{ marginTop: 12 }}>Загрузка…</div>}
      {error && <div className="error" style={{ marginTop: 12 }}>{String(error)}</div>}
      {status && <div className="status" style={{ marginTop: 12 }}>{status}</div>}

      {!loading && !error && (
        <>
          <h3 style={{ marginTop: 20, fontSize: 16 }}>Создать пользователя</h3>
          <form onSubmit={createUser} className="form-grid" style={{ marginTop: 8 }}>
            <div>
              <label className="label">Фамилия</label>
              <input value={lastName} onChange={e => setLastName(e.target.value)} />
            </div>
            <div>
              <label className="label">Имя</label>
              <input value={firstName} onChange={e => setFirstName(e.target.value)} />
            </div>
            <div>
              <label className="label">Отчество</label>
              <input value={middleName} onChange={e => setMiddleName(e.target.value)} />
            </div>
            <div>
              <label className="label">Дата рождения</label>
              <input type="date" value={birthDate} onChange={e => setBirthDate(e.target.value)} />
            </div>
            <div>
              <label className="label">Логин</label>
              <input autoComplete="off" value={login} onChange={e => setLogin(e.target.value)} />
            </div>
            <div>
              <label className="label">Пароль</label>
              <PasswordField autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} />
            </div>
            <div className="form-choice-row" style={{ alignSelf: 'end' }}>
              <label>
                <input type="checkbox" checked={isAdminNew} onChange={e => setIsAdminNew(e.target.checked)} />
                {' '}Права администратора (создание событий и т.д.)
              </label>
            </div>
            <div className="form-actions" style={{ alignSelf: 'end' }}>
              <button type="submit" className="btn btn-primary" disabled={users.length >= MAX_USERS}>
                Добавить
              </button>
            </div>
          </form>

          <h3 style={{ marginTop: 24, fontSize: 16 }}>Список ({users.length}/{MAX_USERS})</h3>
          <div style={{ overflowX: 'auto', marginTop: 8 }}>
            <table className="users-table">
              <thead>
                <tr>
                  <th>ФИО</th>
                  <th>Дата рождения</th>
                  <th>Логин</th>
                  <th>Админ</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <UserRow
                    key={u.id}
                    u={u}
                    onToggleAdmin={toggleAdmin}
                    onChangePassword={changePassword}
                    onDelete={removeUser}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

function UserRow({ u, onToggleAdmin, onChangePassword, onDelete }) {
  const [pwd, setPwd] = useState('')
  const fio = [u.last_name, u.first_name, u.middle_name].filter(Boolean).join(' ')

  return (
    <tr>
      <td>
        {fio}
        {u.is_owner ? <span className="status"> (владелец)</span> : null}
      </td>
      <td>{formatBirth(u.birth_date)}</td>
      <td>{u.login}</td>
      <td>
        <input
          type="checkbox"
          checked={u.is_admin}
          disabled={u.is_owner}
          onChange={e => onToggleAdmin(u, e.target.checked)}
        />
      </td>
      <td>
        <div className="actions-wrap user-row-password-actions">
          <PasswordField
            placeholder="Новый пароль"
            autoComplete="new-password"
            value={pwd}
            onChange={e => setPwd(e.target.value)}
            className="user-row-password-field"
          />
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => { onChangePassword(u, pwd); setPwd('') }}
          >
            Сохранить пароль
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            disabled={u.is_owner}
            onClick={() => onDelete(u)}
          >
            Удалить
          </button>
        </div>
      </td>
    </tr>
  )
}
