import ChatInterface from './components/ChatInterface'
import './App.css'

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>NYC Uber/Lyft Data Agent</h1>
        <span className="header-badge">GPT-powered</span>
      </header>
      <main className="app-main">
        <ChatInterface />
      </main>
    </div>
  )
}

export default App


