import React, { useState, useEffect } from 'react'
import axios from 'axios'

export default function Login() {
  const [token, setToken] = useState(localStorage.getItem('admin_token') || '')
  const [show, setShow] = useState(false)

  useEffect(() => {
    if (token) {
      localStorage.setItem('admin_token', token)
      axios.defaults.headers.common['x-admin-token'] = token
    } else {
      localStorage.removeItem('admin_token')
      delete axios.defaults.headers.common['x-admin-token']
    }
  }, [token])

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
  useEffect(() => {
    if (!token) setShow(true)
    // only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function submit() {
    if (!token) return alert('Введите токен')
    // saved by effect
    setShow(false)
  }

  function logout() {
    setToken('')
  }

  // This component intentionally does not render an inline button to avoid duplicates.
  // It only mounts the modal (when open) and registers the global opener.
  return (
    <>
      {show && (
        <div className="modal-overlay" onClick={() => setShow(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Вход администратора</h3>
            <div style={{marginTop:8}}>
              <input placeholder="Admin token" value={token} onChange={e => setToken(e.target.value)} style={{width:'100%'}} />
            </div>
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
