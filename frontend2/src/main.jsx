import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
// Авторизация и продление токена для всех запросов к API — до первого рендера.
import './api/axios'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
