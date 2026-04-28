import React, { useState, useEffect } from 'react'
import axios from 'axios'
import EventForm from './EventForm'
import EventsList from './EventsList'
import Calendar from './Calendar'
import Login from './Login'
import Semester from './Semester'
import HomeworkList from './HomeworkList'

export default function App() {
  // По умолчанию показываем календарь анонимным пользователям. Когда админ входит, может переключать вкладки.
  const [tab, setTab] = useState('calendar')
  const [lastCreated, setLastCreated] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)

  async function validateAdminToken(token) {
    if (!token) return false
    try {
      await axios.get('/admin/validate', { headers: { 'x-admin-token': token } })
      return true
    } catch {
      return false
    }
  }

  useEffect(() => {
    let isCancelled = false
    async function syncAdminState() {
      const storedToken = localStorage.getItem('admin_token')
      if (!storedToken) {
        if (!isCancelled) setIsAdmin(false)
        return
      }

      const isValid = await validateAdminToken(storedToken)
      if (isCancelled) return

      if (isValid) {
        axios.defaults.headers.common['x-admin-token'] = storedToken
        setIsAdmin(true)
      } else {
        localStorage.removeItem('admin_token')
        delete axios.defaults.headers.common['x-admin-token']
        setIsAdmin(false)
      }
    }

    syncAdminState()
    function onAdminTokenChanged() { syncAdminState() }
    function onStorage(e) {
      if (e.key === 'admin_token') syncAdminState()
    }

    window.addEventListener('admin-token-changed', onAdminTokenChanged)
    window.addEventListener('storage', onStorage)
    return () => {
      isCancelled = true
      window.removeEventListener('admin-token-changed', onAdminTokenChanged)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  // Компонент кнопки авторизации: видимая кнопка, которая просит токен администратора
  function AuthButton() {
    async function doPromptLogin() {
      const t = window.prompt('Введите admin токен:')
      if (!t) return

      const isValid = await validateAdminToken(t)
      if (!isValid) {
        localStorage.removeItem('admin_token')
        delete axios.defaults.headers.common['x-admin-token']
        setIsAdmin(false)
        window.alert('Неверный пароль')
        window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: null }))
        window.dispatchEvent(new CustomEvent('admin-token-changed'))
        return
      }

      localStorage.setItem('admin_token', t)
      axios.defaults.headers.common['x-admin-token'] = t
      setIsAdmin(true)
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: t }))
      window.dispatchEvent(new CustomEvent('admin-token-changed'))
    }

    function doLogout() {
      localStorage.removeItem('admin_token')
      delete axios.defaults.headers.common['x-admin-token']
      setIsAdmin(false)
      window.dispatchEvent(new StorageEvent('storage', { key: 'admin_token', newValue: null }))
      window.dispatchEvent(new CustomEvent('admin-token-changed'))
    }

    if (isAdmin) return (
      <div className="login-auth">
        <span style={{fontSize:12,opacity:0.8}}>Администратор</span>
        <button className="btn" onClick={doLogout}>Выйти</button>
      </div>
    )

    return (
      <button className="btn btn-primary" onClick={doPromptLogin}>Авторизоваться</button>
    )
  }

  // состояние для скрытых параметров семестра (доступно через хеш)
  const [currentSemester, setCurrentSemester] = useState(localStorage.getItem('semester') || '')

  useEffect(() => {
    function onStorage(e) {
      if (e.key === 'semester') setCurrentSemester(e.newValue || '')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  // скрытый индикатор для скрытности параметра семестра

  // обработка скрытой навигации по семестру через URL хеш
  useEffect(() => {
    const h = window.location.hash.replace(/^#/, '')
    if (h === 'semester') setTab('semester')
  }, [])
  useEffect(() => {
    // синхронизируем хеш для закладок
    if (tab === 'semester') {
      window.location.hash = 'semester'
    } else if (window.location.hash === '#semester') {
      window.location.hash = ''
    }
  }, [tab])

  return (
    <div className="container">
      <header className="topbar">
        <h1>Планировщик Университета — Администратор</h1>
        <nav>
          {/* Показываем админ вкладки только если вошли */}
          { isAdmin ? (
            <>
              <button className={tab==='create'? 'tab active':'tab'} onClick={() => setTab('create')}>Создать</button>
              <button className={tab==='list'? 'tab active':'tab'} onClick={() => setTab('list')}>События</button>
            </>
          ) : null }
          <button className={tab==='calendar'? 'tab active':'tab'} onClick={() => setTab('calendar')}>Календарь</button>
          <button className={tab==='homework'? 'tab active':'tab'} onClick={() => setTab('homework')}>Домашняя работа</button>
        </nav>
        <div className="topbar-auth">
          {/* Видимая кнопка авторизации (единственный элемент управления) */}
          <AuthButton />
        </div>
      </header>

      <main>
        {tab === 'create' && <EventForm onCreated={d => { setLastCreated(d); setTab('list') }} />}
        {tab === 'list' && <EventsList highlightId={lastCreated?.id} />}
        {tab === 'calendar' && <Calendar />}
        {tab === 'homework' && <HomeworkList />}
        {tab === 'semester' && <Semester /> /* still reachable via hash or manual setTab */}
      </main>
      {/* Mount Login modal handler (modal will only render when triggered) */}
      <Login />
    </div>
  )
}
