import { useState, useRef, useEffect } from 'react'
import { Turnstile } from '@marsidev/react-turnstile'
import MessageList from './MessageList'
import { sendMessageStream } from '../api/chat'
import './ChatInterface.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || ''

const getApiPath = (endpoint: string) => {
  if (API_URL.startsWith('/')) {
    return `${API_URL}${endpoint}`
  } else {
    return `${API_URL}/api${endpoint}`
  }
}
const isDevMode = API_URL.includes('localhost') || API_URL.includes('127.0.0.1') || API_URL === '/api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql?: string
  data?: any[]
  data_preview?: any[]
  chart?: any
  chart_image_url?: string
  sources?: string[]
  mode?: string
  cached?: boolean
}

export type LoadingStage =
  | 'idle'
  | 'generating-sql'
  | 'running-query'
  | 'generating-chart'
  | 'rendering'

const STREAM_STAGES: LoadingStage[] = [
  'generating-sql',
  'running-query',
  'generating-chart',
  'rendering',
]

function isLoadingStage(value: string): value is LoadingStage {
  return value === 'idle' || STREAM_STAGES.includes(value as LoadingStage)
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: 'Welcome! Ask me anything about NYC Uber & Lyft trip data (Jan–Mar 2023), or\ntry one of these:'
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState<LoadingStage>('idle')
  const [turnstileToken, setTurnstileToken] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [previewData, setPreviewData] = useState<any>(null)
  const [previewLoading, setPreviewLoading] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Fetch preview data on mount
  useEffect(() => {
    const fetchPreview = async () => {
      try {
        const response = await fetch(getApiPath('/data-preview'))
        if (response.ok) {
          const data = await response.json()
          setPreviewData(data)
        }
      } catch {
        // Silently fail
      } finally {
        setPreviewLoading(false)
      }
    }
    fetchPreview()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loadingStage])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading || (!turnstileToken && !isDevMode)) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim()
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)
    setError('')
    setLoadingStage('generating-sql')

    try {
      const token = turnstileToken || (isDevMode ? 'dev-token' : '')
      const response = await sendMessageStream(
        input.trim(),
        token,
        (stage) => {
          if (isLoadingStage(stage)) {
            setLoadingStage(stage)
          }
        }
      )

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.answer,
        sql: response.sql,
        data: response.data,
        data_preview: response.data_preview,
        chart: response.chart,
        chart_image_url: response.chart_image_url,
        sources: response.sources,
        mode: response.mode,
        cached: response.cached
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (err: any) {
      setError(err.message || 'Failed to send message')
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${err.message || 'Failed to process your request'}`,
        mode: 'error'
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
      setLoadingStage('idle')
      setTurnstileToken('')
    }
  }

  const handleExampleClick = (prompt: string) => {
    setInput(prompt)
  }

  return (
    <div className="chat-interface">
      <div className="chat-messages-area">
        <MessageList
          messages={messages}
          loading={loading}
          loadingStage={loadingStage}
          onShowSQL={(message) => console.log('SQL:', message.sql)}
          previewData={previewData}
          previewLoading={previewLoading}
          onExampleClick={handleExampleClick}
        />
        <div ref={messagesEndRef} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <form onSubmit={handleSubmit} className="chat-input-form">
        {!isDevMode && (
          <div className="turnstile-container">
            <Turnstile
              siteKey={TURNSTILE_SITE_KEY || '1x00000000000000000000AA'}
              onSuccess={(token) => { setTurnstileToken(token); setError('') }}
              onError={() => { setError('Turnstile verification failed') }}
              options={{ theme: 'dark', size: 'normal' }}
            />
          </div>
        )}

        <div className="input-row">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about NYC Uber/Lyft trip data..."
            disabled={loading}
            className="chat-input"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="send-btn"
          >
            {loading ? (
              <span className="send-spinner" />
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}
