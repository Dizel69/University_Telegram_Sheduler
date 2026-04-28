import React, { useState, useEffect } from 'react'
import axios from 'axios'

export default function Login() {
  const [inputToken, setInputToken] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')

  // expose global opener for cases where header wants to trigger the modal
  useEffect(() => {
    function onOpen() { setShow(true) }
    window.addEventListener('open-admin-login', onOpen)
    // helper to trigger from other components
    window.openAdminLogin = () => window.dispatchEvent(new Event('open-admin-login'))
    return () => {
      window.removeEventListener('open-admin-login', onOpen)
      try { delete window.openAdminLogin } catch(e){}
    }
  }, [])

  // if there's no token on first load, open the modal so the admin sees the login immediately
  // NOTE: we do NOT auto-open the login modal on mount so anonymous users are not prompted.
  // The modal can be opened by other components via `window.openAdminLogin()` or by UI controls.

  useEffect(() => {
    if (show) {
      setInputToken(localStorage.getItem('admin_token') || '')
      setError('')
    }
  }, [show])

  async function submit() {
    const candidate = inputToken.trim()
    if (!candidate) {
      setError('Введите токен')
      return
    }
    try {
      await axios.get('/admin/validate', { headers: { 'x-admin-token': candidate } })
      localStorage.setItem('admin_token', candidate)
      axios.defaults.headers.common['x-admin-token'] = candidate
      setError('')
      setShow(false)
      window.dispatchEvent(new CustomEvent('admin-token-changed'))
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: candidate }))
    } catch {
      localStorage.removeItem('admin_token')
      delete axios.defaults.headers.common['x-admin-token']
      setError('Неверный пароль')
      window.dispatchEvent(new CustomEvent('admin-token-changed'))
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: null }))
    }
  }

  // This component intentionally does not render an inline button to avoid duplicates.
  // It only mounts the modal (when open) and registers the global opener.
  return (
    <>
      {show && (
        <div className="modal-overlay" onClick={() => setShow(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Вход администратора</h3>
            <div style={{marginTop:8}}>Кто ты воин? Введи ка пароль:</div>
            <div style={{marginTop:8}}>
              <input
                placeholder="Пароль"
                value={inputToken}
                onChange={e => setInputToken(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') submit()
                }}
                style={{width:'100%'}}
              />
            </div>
            {error ? (
              <div style={{marginTop:8,fontSize:13,color:'#dc2626'}}>{error}</div>
            ) : null}
            <div className="modal-actions" style={{marginTop:12}}>
              <button className="btn" onClick={submit}>Войти</button>
              <button className="btn" onClick={() => setShow(false)}>Отмена</button>
            </div>
            <div style={{marginTop:8,fontSize:12,color:'#6b7280'}}>Токен хранится локально в браузере.</div>
          </div>
        </div>
      )}
    </>
  )

}
