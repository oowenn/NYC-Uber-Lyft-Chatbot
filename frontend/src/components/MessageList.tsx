import { useState } from 'react'
import ChartRenderer from './ChartRenderer'
import DataTable from './DataTable'
import type { LoadingStage } from './ChatInterface'
import './MessageList.css'

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

const STAGE_LABELS: Record<LoadingStage, string> = {
  idle: '',
  'generating-sql': 'Generating SQL',
  'running-query': 'Executing SQL',
  'generating-chart': 'Generating chart spec',
  rendering: 'Rendering chart',
}

interface MessageListProps {
  messages: Message[]
  loading: boolean
  loadingStage?: LoadingStage
  onShowSQL: (message: Message) => void
  previewData?: any
  previewLoading?: boolean
  onExampleClick?: (prompt: string) => void
}

export default function MessageList({ messages, loading, loadingStage = 'idle', previewData, previewLoading, onExampleClick }: MessageListProps) {
  const [expandedSQL, setExpandedSQL] = useState<Set<string>>(new Set())
  const [expandedData, setExpandedData] = useState<Set<string>>(new Set())
  const [expandedPreview, setExpandedPreview] = useState(false)

  const toggleSQL = (id: string) => {
    setExpandedSQL(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleData = (id: string) => {
    setExpandedData(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="message-list">
      {messages.map((message) => (
        <div key={message.id} className={`msg msg-${message.role}`}>
          {/* Avatar */}
          <div className="msg-avatar">
            {message.role === 'assistant' ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
            )}
          </div>

          {/* Body */}
          <div className="msg-body">
            <div className="msg-role">
              {message.role === 'assistant' ? 'Agent' : 'You'}
              {message.cached && <span className="badge badge-cached">cached</span>}
              {message.mode === 'error' && <span className="badge badge-error">error</span>}
            </div>

            <div className="msg-text">{message.content}</div>

            {/* Example prompts in welcome message */}
            {message.id === 'welcome' && onExampleClick && (
              <div className="example-chips">
                {['Top 10 pickup zones', 'What is the percentage of base passenger fares held by each company?', 'Show hourly trips by company for the first 3 days of Jan 2023'].map((q, i) => (
                  <button key={i} className="chip" onClick={() => onExampleClick(q)}>{q}</button>
                ))}
              </div>
            )}

            {/* Data preview for welcome */}
            {message.id === 'welcome' && previewData && !previewLoading && (
              <div className="preview-section">
                <button className="pill-btn" onClick={() => setExpandedPreview(!expandedPreview)}>
                  {expandedPreview ? 'Hide' : 'Preview'} data
                </button>
                {expandedPreview && (
                  <div className="preview-table-wrap">
                    <div className="preview-label">Sample rows from <code>fhv_with_company</code></div>
                    <div className="table-scroll">
                      <table className="preview-table">
                        <thead>
                          <tr>
                            {previewData.columns.map((col: string) => (
                              <th key={col}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {previewData.data.map((row: any, idx: number) => (
                            <tr key={idx}>
                              {previewData.columns.map((col: string) => (
                                <td key={col}>{String(row[col] ?? '')}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="preview-footer">
                      Showing {previewData.row_count} sample rows.
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Sources */}
            {message.sources && message.sources.length > 0 && (
              <div className="msg-sources">Sources: {message.sources.join(', ')}</div>
            )}

            {/* Chart image */}
            {message.chart_image_url && (
              <div className="msg-chart">
                <img src={message.chart_image_url} alt={message.chart?.title || 'Chart'} />
              </div>
            )}

            {/* Client-side chart renderer */}
            {message.chart && !message.chart_image_url && (
              <div className="msg-chart">
                <ChartRenderer config={message.chart} data={message.data || []} />
              </div>
            )}

            {/* Action pills */}
            {(message.sql || hasData(message)) && (
              <div className="action-pills">
                {message.sql && (
                  <button className="pill-btn pill-sql" onClick={() => toggleSQL(message.id)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                    {expandedSQL.has(message.id) ? 'Hide' : 'Show'} SQL
                  </button>
                )}
                {hasData(message) && (
                  <button className="pill-btn pill-data" onClick={() => toggleData(message.id)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                    {expandedData.has(message.id) ? 'Hide' : 'Show'} Data
                  </button>
                )}
              </div>
            )}

            {/* Expanded SQL */}
            {message.sql && expandedSQL.has(message.id) && (
              <div className="code-block">
                <pre>{message.sql}</pre>
              </div>
            )}

            {/* Expanded data table */}
            {hasData(message) && expandedData.has(message.id) && (
              <div className="data-block">
                <DataTable data={message.data_preview || message.data || []} fullData={message.data} />
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Thinking / loading indicator */}
      {loading && loadingStage !== 'idle' && (
        <div className="msg msg-assistant">
          <div className="msg-avatar">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div className="msg-body">
            <div className="msg-role">Agent</div>
            <div className="thinking-indicator">
              <div className="thinking-dots">
                <span /><span /><span />
              </div>
              <span className="thinking-label">{STAGE_LABELS[loadingStage]}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function hasData(message: Message): boolean {
  return (
    (Array.isArray(message.data_preview) && message.data_preview.length > 0) ||
    (Array.isArray(message.data) && message.data.length > 0)
  )
}
