import React from 'react'
import { createRoot } from 'react-dom/client'
import axios from 'axios'
import App from './App'
import './styles.css'

// Присоединяем токен администратора из localStorage к стандартному заголовку axios
const token = localStorage.getItem('admin_token')
if (token) {
  axios.defaults.headers.common['x-admin-token'] = token
}

// Наблюдаем за изменениями хранилища (вход/выход в других вкладках)
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
