import React, { useState, useEffect } from 'react'
import axios from 'axios'
import PasswordField from './PasswordField'

export default function UserLogin() {
  const [show, setShow] = useState(false)
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    function onOpen() {
      setShow(true)
    }
    window.addEventListener('open-user-login', onOpen)
    return () => window.removeEventListener('open-user-login', onOpen)
  }, [])

  useEffect(() => {
    if (show) {
      setError('')
    }
  }, [show])

  async function submit(e) {
    e?.preventDefault?.()
    const L = login.trim()
    if (!L || !password) {
      setError('Введите логин и пароль')
      return
    }
    setError('')
    try {
      const { data } = await axios.post('/auth/login', { login: L, password })
      const token = data.access_token
      if (!token) {
        setError('Сервер не вернул токен')
        return
      }
      localStorage.setItem('user_token', token)
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
      setShow(false)
      setPassword('')
      window.dispatchEvent(new CustomEvent('user-auth-changed'))
    } catch (err) {
      const d = err.response?.data?.detail
      setError(typeof d === 'string' ? d : 'Неверный логин или пароль')
    }
  }

  if (!show) return null

  return (
    <div className="modal-overlay" onClick={() => setShow(false)}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Вход в аккаунт</h3>
        <p className="status" style={{ marginTop: 8, fontSize: 13 }}>
          После входа можно отмечать домашние задания как выполненные — отметки сохраняются на сервере в базе данных.
        </p>
        <form onSubmit={submit} style={{ marginTop: 12 }}>
          <label className="label">Логин</label>
          <input
            autoComplete="username"
            value={login}
            onChange={e => setLogin(e.target.value)}
          />
          <label className="label" style={{ marginTop: 10 }}>Пароль</label>
          <PasswordField
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') submit()
            }}
          />
          {error ? (
            <div style={{ marginTop: 8, fontSize: 13, color: '#dc2626' }}>{error}</div>
          ) : null}
          <div className="modal-actions" style={{ marginTop: 12 }}>
            <button type="submit" className="btn btn-primary">Войти</button>
            <button type="button" className="btn" onClick={() => setShow(false)}>Отмена</button>
          </div>
        </form>
      </div>
    </div>
  )
}
