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

