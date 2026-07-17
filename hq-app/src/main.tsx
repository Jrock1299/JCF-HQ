import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { EditModeProvider } from './edit/EditModeContext'
import './styles/globals.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <EditModeProvider>
        <App />
      </EditModeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
