import React, { useState, useEffect } from 'react'
import axios from 'axios'
import EventForm from './EventForm'
import EventsList from './EventsList'
import Calendar from './Calendar'
import Login from './Login'

export default function App() {
  const [tab, setTab] = useState('create')
  const [lastCreated, setLastCreated] = useState(null)

  // Auth helper component: visible button that prompts for admin token
  function AuthButton() {
    const [isAdmin, setIsAdmin] = useState(!!localStorage.getItem('admin_token'))

    useEffect(() => {
      function onStorage(e) {
        if (e.key === 'admin_token') setIsAdmin(!!e.newValue)
      }
      window.addEventListener('storage', onStorage)
      return () => window.removeEventListener('storage', onStorage)
    }, [])

    function doPromptLogin() {
      const t = window.prompt('Введите admin token:')
      if (!t) return
      localStorage.setItem('admin_token', t)
      axios.defaults.headers.common['x-admin-token'] = t
      setIsAdmin(true)
      // notify other components
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: t }))
    }

    function doLogout() {
      localStorage.removeItem('admin_token')
      delete axios.defaults.headers.common['x-admin-token']
      setIsAdmin(false)
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: null }))
    }

    if (isAdmin) return (
      <div style={{display:'flex',alignItems:'center',gap:8}}>
        <span style={{fontSize:12,opacity:0.8}}>Admin</span>
        <button className="btn" onClick={doLogout}>Выйти</button>
      </div>
    )

    return (
      <button className="btn btn-primary" onClick={doPromptLogin}>Авторизоваться</button>
    )
  }

  return (
    <div className="container">
      <header className="topbar">
        <h1>University Scheduler — Admin</h1>
        <nav>
          <button className={tab==='create'? 'tab active':'tab'} onClick={() => setTab('create')}>Создать</button>
          <button className={tab==='list'? 'tab active':'tab'} onClick={() => setTab('list')}>События</button>
          <button className={tab==='calendar'? 'tab active':'tab'} onClick={() => setTab('calendar')}>Календарь</button>
        </nav>
        <div style={{marginLeft:12, display:'flex', alignItems:'center', gap:8}}>
          {/* Prominent auth helper button (single control) */}
          <AuthButton />
        </div>
      </header>

      <main>
        {tab === 'create' && <EventForm onCreated={d => { setLastCreated(d); setTab('list') }} />}
        {tab === 'list' && <EventsList highlightId={lastCreated?.id} />}
        {tab === 'calendar' && <Calendar />}
      </main>
      {/* Mount Login modal handler (modal will only render when triggered) */}
      <Login />
    </div>
  )
}
