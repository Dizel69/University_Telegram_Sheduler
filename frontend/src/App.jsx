import React, { useState } from 'react'
import EventForm from './EventForm'
import EventsList from './EventsList'

export default function App() {
  const [tab, setTab] = useState('create')
  const [lastCreated, setLastCreated] = useState(null)

  return (
    <div className="container">
      <header className="topbar">
        <h1>University Scheduler — Admin</h1>
        <nav>
          <button className={tab==='create'? 'tab active':'tab'} onClick={() => setTab('create')}>Создать</button>
          <button className={tab==='list'? 'tab active':'tab'} onClick={() => setTab('list')}>События</button>
          <button className={tab==='calendar'? 'tab':'tab'} onClick={() => setTab('calendar')}>Календарь</button>
        </nav>
      </header>

      <main>
        {tab === 'create' && <EventForm onCreated={d => { setLastCreated(d); setTab('list') }} />}
        {tab === 'list' && <EventsList highlightId={lastCreated?.id} />}
        {tab === 'calendar' && <div className="card">Раздел календаря (пока что заглушка)</div>}
      </main>
    </div>
  )
}
