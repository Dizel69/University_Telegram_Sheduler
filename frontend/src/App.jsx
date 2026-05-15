import React, { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import EventForm from './EventForm'
import EventsList from './EventsList'
import Calendar from './Calendar'
import UserLogin from './UserLogin'
import Semester from './Semester'
import HomeworkList from './HomeworkList'
import UsersAdmin from './UsersAdmin'

export default function App() {
  const [tab, setTab] = useState('calendar')
  const [lastCreated, setLastCreated] = useState(null)
  const [accountUser, setAccountUser] = useState(null)

  const showAdminTabs = Boolean(accountUser?.is_admin)
  const showUsersTab = Boolean(accountUser?.is_owner)

  useEffect(() => {
    let isCancelled = false
    async function syncAccount() {
      const t = localStorage.getItem('user_token')
      if (!t) {
        if (!isCancelled) {
          setAccountUser(null)
          delete axios.defaults.headers.common['Authorization']
        }
        return
      }
      axios.defaults.headers.common['Authorization'] = `Bearer ${t}`
      try {
        const { data } = await axios.get('/auth/me')
        if (isCancelled) return
        setAccountUser(data)
      } catch {
        if (!isCancelled) {
          localStorage.removeItem('user_token')
          delete axios.defaults.headers.common['Authorization']
          setAccountUser(null)
        }
      }
    }

    syncAccount()
    function onAcc() { syncAccount() }
    window.addEventListener('user-auth-changed', onAcc)
    function onStorage(e) {
      if (e.key === 'user_token') syncAccount()
    }
    window.addEventListener('storage', onStorage)
    return () => {
      isCancelled = true
      window.removeEventListener('user-auth-changed', onAcc)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  function logoutAccount() {
    localStorage.removeItem('user_token')
    delete axios.defaults.headers.common['Authorization']
    setAccountUser(null)
    window.dispatchEvent(new CustomEvent('user-auth-changed'))
    window.dispatchEvent(new StorageEvent('storage', { key: 'user_token', newValue: null }))
  }

  function openUserLoginModal() {
    window.dispatchEvent(new Event('open-user-login'))
  }

  const [currentSemester, setCurrentSemester] = useState(localStorage.getItem('semester') || '')

  useEffect(() => {
    function onStorage(e) {
      if (e.key === 'semester') setCurrentSemester(e.newValue || '')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    const h = window.location.hash.replace(/^#/, '')
    if (h === 'semester') setTab('semester')
  }, [])
  useEffect(() => {
    if (tab === 'semester') {
      window.location.hash = 'semester'
    } else if (window.location.hash === '#semester') {
      window.location.hash = ''
    }
  }, [tab])

  useEffect(() => {
    if (tab === 'users' && !showUsersTab) setTab('calendar')
    if ((tab === 'create' || tab === 'list') && !showAdminTabs) setTab('calendar')
  }, [tab, showUsersTab, showAdminTabs])

  const calendarIsAdmin = useMemo(() => Boolean(accountUser?.is_admin), [accountUser])

  return (
    <div className="container">
      <header className="topbar">
        <h1>Планировщик университета</h1>
        <nav>
          {showAdminTabs ? (
            <>
              <button type="button" className={tab === 'create' ? 'tab active' : 'tab'} onClick={() => setTab('create')}>Создать</button>
              <button type="button" className={tab === 'list' ? 'tab active' : 'tab'} onClick={() => setTab('list')}>События</button>
            </>
          ) : null}
          {showUsersTab ? (
            <button type="button" className={tab === 'users' ? 'tab active' : 'tab'} onClick={() => setTab('users')}>Пользователи</button>
          ) : null}
          <button type="button" className={tab === 'calendar' ? 'tab active' : 'tab'} onClick={() => setTab('calendar')}>Календарь</button>
          <button type="button" className={tab === 'homework' ? 'tab active' : 'tab'} onClick={() => setTab('homework')}>Домашняя работа</button>
        </nav>
        <div className="topbar-auth">
          {accountUser ? (
            <div className="login-auth">
              <span style={{ fontSize: 12, opacity: 0.85 }}>
                {accountUser.last_name}
                {' '}
                {(accountUser.first_name || '').charAt(0).toUpperCase()}.
              </span>
              <button type="button" className="btn btn-sm" onClick={logoutAccount}>Выйти</button>
            </div>
          ) : (
            <button type="button" className="btn btn-primary btn-sm" onClick={openUserLoginModal}>Войти</button>
          )}
        </div>
      </header>

      <main>
        {tab === 'create' && showAdminTabs && (
          <EventForm onCreated={d => { setLastCreated(d); setTab('list') }} />
        )}
        {tab === 'list' && showAdminTabs && (
          <EventsList highlightId={lastCreated?.id} isAdmin={Boolean(accountUser?.is_admin)} />
        )}
        {tab === 'calendar' && <Calendar isAdmin={calendarIsAdmin} />}
        {tab === 'homework' && <HomeworkList accountUser={accountUser} />}
        {tab === 'users' && showUsersTab && <UsersAdmin />}
        {tab === 'semester' && <Semester />}
      </main>
      <UserLogin />
    </div>
  )
}
