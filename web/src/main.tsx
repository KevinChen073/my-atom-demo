import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './design-tokens.css'
import './styles.css'
import './v3.css'
import './v7.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
