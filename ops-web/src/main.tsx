import React from 'react'
import { createRoot } from 'react-dom/client'
import { OperationsApp } from './OperationsApp'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <OperationsApp />
  </React.StrictMode>,
)
