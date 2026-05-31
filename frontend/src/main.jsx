import React from 'react'
import { createRoot } from 'react-dom/client'
import axios from 'axios'
import App from './App'
import './styles.css'
import { initTheme } from './theme'

initTheme()

const userTok = localStorage.getItem('user_token')
if (userTok) {
  axios.defaults.headers.common['Authorization'] = `Bearer ${userTok}`
}

window.addEventListener('storage', (e) => {
  if (e.key === 'user_token') {
    if (e.newValue) axios.defaults.headers.common['Authorization'] = `Bearer ${e.newValue}`
    else delete axios.defaults.headers.common['Authorization']
  }
})

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
