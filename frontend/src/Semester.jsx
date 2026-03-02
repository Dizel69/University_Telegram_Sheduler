import React, { useState, useEffect } from 'react'

export default function Semester() {
  const [semester, setSemester] = useState(localStorage.getItem('semester') || '')

  useEffect(() => {
    function onStorage(e) {
      if (e.key === 'semester') setSemester(e.newValue || '')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  function save() {
    localStorage.setItem('semester', semester)
    alert('Текущий семестр сохранён')
  }

  return (
    <div className="card">
      <h2>Выберите текущий семестр</h2>
      <div className="form-grid">
        <div>
          <label className="label">Семестр</label>
          <input
            type="text"
            placeholder="Например: Весна 2026"
            value={semester}
            onChange={e => setSemester(e.target.value)}
          />
        </div>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={save}>Сохранить</button>
      </div>
      {semester && (
        <div style={{marginTop:12}}>
          Текущий семестр: <b>{semester}</b>
        </div>
      )}
    </div>
  )
}
