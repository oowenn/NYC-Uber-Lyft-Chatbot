import axios from 'axios'
import type { ChatResponse } from '../types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
// If API_URL is a relative path like '/api', don't add '/api' again
const getApiPath = (endpoint: string) => {
  if (API_URL.startsWith('/')) {
    // Using Vite proxy, endpoint already includes /api
    return `${API_URL}${endpoint}`
  } else {
    // Direct connection, need to add /api
    return `${API_URL}/api${endpoint}`
  }
}

export async function sendMessage(message: string, turnstileToken: string): Promise<ChatResponse> {
  try {
    const response = await axios.post<ChatResponse>(
      getApiPath('/chat'),
      {
        message,
        turnstile_token: turnstileToken
      },
      {
        headers: {
          'Content-Type': 'application/json'
        },
        timeout: 300000 // 5 minutes - backend may run SQL + chart generation (multiple LLM calls)
      }
    )
    
    return response.data
  } catch (error: any) {
    // Extract meaningful error message
    if (error.response) {
      // Server responded with error status
      const errorMsg = error.response.data?.detail || error.response.data?.error || error.response.statusText
      throw new Error(errorMsg || 'Server error')
    } else if (error.request) {
      // Request was made but no response received
      throw new Error('Cannot connect to backend. Is the server running on ' + API_URL + '?')
    } else {
      // Something else happened
      throw new Error(error.message || 'Network error')
    }
  }
}

export async function sendMessageStream(
  message: string,
  turnstileToken: string,
  onStage: (stage: string) => void
): Promise<ChatResponse> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 300000)

  try {
    const response = await fetch(getApiPath('/chat/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        turnstile_token: turnstileToken,
      }),
      signal: controller.signal,
    })

    if (!response.ok) {
      let detail = `Server error (${response.status})`
      try {
        const errJson = await response.json()
        detail = errJson?.detail || errJson?.error || detail
      } catch {
        // no-op
      }
      throw new Error(detail)
    }

    if (!response.body) {
      throw new Error('Streaming response body is empty')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: ChatResponse | null = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''

      for (const eventBlock of events) {
        const parsed = parseSseEvent(eventBlock)
        if (!parsed) continue

        if (parsed.event === 'stage' && parsed.data?.stage) {
          onStage(parsed.data.stage)
        } else if (parsed.event === 'result') {
          finalResult = parsed.data as ChatResponse
        } else if (parsed.event === 'error') {
          throw new Error(parsed.data?.detail || parsed.data?.error || 'Streaming request failed')
        } else if (parsed.event === 'done') {
          break
        }
      }
    }

    if (!finalResult) {
      throw new Error('No final result received from streaming endpoint')
    }
    return finalResult
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new Error('Request timed out after 5 minutes')
    }
    throw new Error(error?.message || 'Network error')
  } finally {
    clearTimeout(timeout)
  }
}

function parseSseEvent(block: string): { event: string; data: any } | null {
  const lines = block.split('\n').map((line) => line.trim())
  let eventName = 'message'
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line) continue
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim())
    }
  }

  if (dataLines.length === 0) return null
  const raw = dataLines.join('\n')
  try {
    return { event: eventName, data: JSON.parse(raw) }
  } catch {
    return { event: eventName, data: raw }
  }
}

