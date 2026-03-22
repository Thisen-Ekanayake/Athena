import React, { useState, useEffect, useRef } from 'react'
import { X, Send, Loader2, AlertCircle } from 'lucide-react'
import { useQAStore } from '../store/qaStore'
import { type FeedItem } from '../api/client'

interface QAPanelProps {
  item: FeedItem
  onClose: () => void
}

export function QAPanel({ item, onClose }: QAPanelProps) {
  const [inputStr, setInputStr] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [status, setStatus] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [budgetExceeded, setBudgetExceeded] = useState(false)
  const [lastQuestion, setLastQuestion] = useState<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  
  const history = useQAStore(state => state.sessions[item.id] || [])
  const addMessage = useQAStore(state => state.addMessage)
  const updateLastMessage = useQAStore(state => state.updateLastMessage)
  const clearSession = useQAStore(state => state.clearSession)

  // Scroll to bottom when history changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, isStreaming])

  // Fetch status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/items/${item.id}/qa/status`)
        const data = await res.json()
        setStatus(data)
      } catch (e) {
        console.error("Failed to fetch QA status", e)
      }
    }
    checkStatus()
  }, [item.id])

  const handleSend = async () => {
    if (!inputStr.trim() || isStreaming) return
    const q = inputStr.trim()
    setErrorMsg(null)
    setBudgetExceeded(false)
    setLastQuestion(q)
    
    // Add User message
    addMessage(item.id, { role: 'user', content: q })
    
    // Prepare for assistant streaming
    setIsStreaming(true)
    addMessage(item.id, { role: 'assistant', content: '' })
    let currentAnswer = ""

    try {
      const res = await fetch(`http://localhost:8000/api/v1/items/${item.id}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, history })
      })

      if (!res.ok) {
        const errData = await res.json()
        if (res.status === 429) {
          setBudgetExceeded(true)
        }
        throw new Error(errData.detail || 'Q&A request failed')
      }

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()

      if (reader) {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          
          const textChunk = decoder.decode(value)
          const lines = textChunk.split('\n')
          
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const payload = line.slice(6)
            if (payload === '[DONE]') break
            try {
              const { token, error } = JSON.parse(payload)
              if (error) {
                 currentAnswer += `\n[Error: ${error}]`
                 updateLastMessage(item.id, currentAnswer)
                 break
              }
              if (token) {
                 currentAnswer += token
                 updateLastMessage(item.id, currentAnswer)
              }
            } catch(e) { /* ignore parse error on partial chunks if any */ }
          }
        }
      }
    } catch (e: any) {
      setErrorMsg(e.message)
      currentAnswer += `\n(answer interrupted)`
      updateLastMessage(item.id, currentAnswer)
    } finally {
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="mt-4 border border-zinc-800 bg-zinc-950 rounded-md overflow-hidden flex flex-col animate-in fade-in slide-in-from-top-2 duration-300">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800">
        <div className="flex items-center gap-2">
           <span className="text-xs font-semibold text-zinc-300">Ask Athena</span>
           {status && status.status === 'partial' && (
             <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-orange-500/20 text-orange-400">
               Partial content (Abstract only)
             </span>
           )}
           {status && status.status === 'unavailable' && (
             <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-red-500/20 text-red-400">
               Article unavailable
             </span>
           )}
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={() => clearSession(item.id)} 
             className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
             Clear
          </button>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 max-h-80 overflow-y-auto p-4 space-y-4">
        {history.length === 0 && (
          <div className="text-sm text-zinc-500 text-center py-6">
            Ask any question about this article. The answer will be grounded entirely in the text.
          </div>
        )}
        
        {history.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-lg px-4 py-2 text-sm leading-relaxed ${
              msg.role === 'user' 
                ? 'bg-accentPrimary/20 text-accentPrimary border border-accentPrimary/30 rounded-br-none' 
                : 'bg-zinc-900 text-zinc-200 border border-zinc-800 rounded-bl-none'
            }`}>
              <div className="whitespace-pre-wrap">{msg.content}</div>
              {msg.role === 'assistant' && isStreaming && idx === history.length - 1 && (
                <span className="inline-block w-1.5 h-3 ml-1 bg-zinc-400 animate-pulse" />
              )}
              {msg.role === 'assistant' && (!isStreaming || idx !== history.length - 1) && (
                <div className="mt-2 pt-2 border-t border-zinc-700/50 text-[10px] text-zinc-500 opacity-80 flex items-center gap-1">
                  <span>Answer synthesized from:</span>
                  <span className="font-medium text-zinc-400">{item.source.name}</span>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {errorMsg && (
        <div className="px-4 py-2 bg-red-500/10 border-t border-red-500/20 flex items-center justify-between text-xs text-red-400">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-3 h-3" />
            {errorMsg}
          </div>
          {lastQuestion && !budgetExceeded && (
            <button
              onClick={() => { setErrorMsg(null); setInputStr(lastQuestion); handleSend() }}
              className="px-2.5 py-1 rounded bg-red-500/20 hover:bg-red-500/30 text-red-300 font-medium transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      )}

      {budgetExceeded && (
        <div className="px-4 py-3 bg-orange-500/10 border-t border-orange-500/20 text-xs text-orange-400 text-center">
          <p className="font-medium">Session limit reached for this article.</p>
          <button
            onClick={() => { clearSession(item.id); setBudgetExceeded(false); setErrorMsg(null) }}
            className="mt-1.5 px-3 py-1 rounded bg-orange-500/20 hover:bg-orange-500/30 text-orange-300 font-medium transition-colors"
          >
            Clear session & start fresh
          </button>
        </div>
      )}

      {/* Input */}
      <div className="p-3 bg-zinc-900/50 border-t border-zinc-800">
        <div className="relative flex items-center">
          <textarea
             value={inputStr}
             onChange={e => setInputStr(e.target.value)}
             onKeyDown={handleKeyDown}
             placeholder="Ask a question about this article..."
             className="w-full bg-zinc-900 border border-zinc-800 rounded-md py-2 pl-3 pr-10 text-sm focus:outline-none focus:border-accentPrimary/50 resize-none h-10"
             disabled={isStreaming}
          />
          <button
             onClick={handleSend}
             disabled={!inputStr.trim() || isStreaming}
             className="absolute right-2 p-1.5 text-zinc-400 hover:text-accentPrimary disabled:opacity-50 disabled:hover:text-zinc-400 transition-colors"
          >
             {isStreaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}
