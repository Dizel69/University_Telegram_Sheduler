import React from 'react'
import { createRoot } from 'react-dom/client'
import axios from 'axios'
import App from './App'
import './styles.css'

// attach admin token from localStorage to axios default header
const token = localStorage.getItem('admin_token')
if (token) {
  axios.defaults.headers.common['x-admin-token'] = token
}

// watch storage changes (login/logout in other tabs)
window.addEventListener('storage', (e) => {
  if (e.key === 'admin_token') {
    const t = e.newValue
    if (t) axios.defaults.headers.common['x-admin-token'] = t
    else delete axios.defaults.headers.common['x-admin-token']
  }
})

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
