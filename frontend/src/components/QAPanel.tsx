import React, { useState, useEffect, useRef } from 'react'
import { X, Send, Loader2, AlertCircle, Sparkles, Trash2, MessageSquare } from 'lucide-react'
import { useQAStore } from '../store/qaStore'
import { type FeedItem } from '../api/client'
import { motion, AnimatePresence } from 'framer-motion'

interface QAPanelProps {
  item: FeedItem
  onClose: () => void
}

const EMPTY_HISTORY: any[] = []

export function QAPanel({ item, onClose }: QAPanelProps) {
  const [inputStr, setInputStr] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [status, setStatus] = useState<any>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [budgetExceeded, setBudgetExceeded] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  
  const history = useQAStore(state => state.sessions[item.id]) ?? EMPTY_HISTORY
  const addMessage = useQAStore(state => state.addMessage)
  const updateLastMessage = useQAStore(state => state.updateLastMessage)
  const clearSession = useQAStore(state => state.clearSession)

  const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, isStreaming])

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await fetch(`${apiBase}/api/v1/items/${item.id}/qa/status`)
        const data = await res.json()
        setStatus(data)
      } catch (e) {
        console.error("Failed to fetch QA status", e)
      }
    }
    checkStatus()
  }, [item.id, apiBase])

  const handleSend = async () => {
    if (!inputStr.trim() || isStreaming) return
    const q = inputStr.trim()
    setInputStr("")
    setErrorMsg(null)
    setBudgetExceeded(false)
    
    addMessage(item.id, { role: 'user', content: q })
    setIsStreaming(true)
    addMessage(item.id, { role: 'assistant', content: '' })
    let currentAnswer = ""

    try {
      const res = await fetch(`${apiBase}/api/v1/items/${item.id}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, history })
      })

      if (!res.ok) {
        const errData = await res.json()
        if (res.status === 429) setBudgetExceeded(true)
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
            } catch(e) {}
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
    <AnimatePresence>
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="fixed inset-y-0 right-0 z-[60] w-full md:w-[450px] glass-opaque shadow-2xl flex flex-col border-l border-border-glow will-change-transform"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-border-subtle bg-white/5">
          <div className="flex flex-col gap-1 min-w-0">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-accent-primary" />
              <h2 className="text-sm font-display font-bold tracking-wide text-text-primary uppercase">Research Assistant</h2>
            </div>
            <p className="text-[11px] text-text-muted truncate max-w-[300px]">{item.title}</p>
          </div>
          <button 
            onClick={onClose} 
            className="p-2 -mr-2 text-text-muted hover:text-text-primary hover:bg-white/5 rounded-full transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Status Area */}
        <AnimatePresence>
          {status && (status.status === 'partial' || status.status === 'unavailable') && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              className="px-6 py-2 bg-accent-warning/10 border-b border-accent-warning/20 flex items-center justify-center"
            >
              <div className="flex items-center gap-2 text-[10px] uppercase font-bold text-accent-warning tracking-wider">
                <AlertCircle className="w-3.5 h-3.5" />
                {status.status === 'partial' ? 'Abstract-only grounding' : 'Article content unavailable'}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-8 space-y-8 custom-scrollbar">
          {history.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center px-8 opacity-40">
              <div className="w-16 h-16 rounded-3xl bg-accent-primary/10 border border-accent-primary/20 flex items-center justify-center mb-6">
                <MessageSquare className="w-8 h-8 text-accent-primary" />
              </div>
              <h3 className="font-display font-medium text-text-primary mb-2">Contextual Intelligence</h3>
              <p className="text-[13px] text-text-muted leading-relaxed">
                Ask specific questions about this article. Answers are grounded directly in the research corpus.
              </p>
            </div>
          )}
          
          {history.map((msg, idx) => (
            <motion.div 
              layout
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              key={idx} 
              className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
            >
              <div className={`
                max-w-[90%] rounded-2xl px-5 py-3.5 text-[14px] leading-relaxed relative
                ${msg.role === 'user' 
                  ? 'bg-accent-primary text-white font-medium rounded-tr-none shadow-glow-primary' 
                  : 'glass-void border border-border-subtle text-text-secondary rounded-tl-none font-mono'}
              `}>
                <div className="whitespace-pre-wrap">{msg.content}</div>
                {msg.role === 'assistant' && isStreaming && idx === history.length - 1 && (
                  <span className="inline-block w-1.5 h-4 ml-1 bg-accent-primary animate-pulse align-middle" />
                )}
              </div>
              <div className={`mt-2 text-[10px] font-display font-medium tracking-[0.05em] text-text-ghost uppercase`}>
                {msg.role === 'user' ? 'Direct Query' : 'Assistant Sync'}
              </div>
            </motion.div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Error Handling */}
        <AnimatePresence>
          {(errorMsg || budgetExceeded) && (
            <motion.div 
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              className="p-4 mx-6 mb-4 rounded-xl glass border-accent-critical/30 bg-accent-critical/5 shadow-lg"
            >
              <div className="flex items-start gap-3">
                <AlertCircle className="w-4 h-4 text-accent-critical flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-[13px] text-accent-critical font-medium mb-1">
                    {budgetExceeded ? 'Session limit reached' : 'Lumina stream interrupted'}
                  </p>
                  <p className="text-[11px] text-text-muted mb-3">
                    {budgetExceeded ? 'Frequent querying detected. Reset the session to continue.' : errorMsg}
                  </p>
                  <div className="flex gap-2">
                    {budgetExceeded ? (
                      <button
                        onClick={() => { clearSession(item.id); setBudgetExceeded(false); setErrorMsg(null) }}
                        className="px-3 py-1.5 rounded-md bg-accent-critical/20 hover:bg-accent-critical/30 text-accent-critical text-[11px] font-bold transition-all"
                      >
                        RESET SESSION
                      </button>
                    ) : (
                      <button
                        onClick={() => { setErrorMsg(null); handleSend() }}
                        className="px-3 py-1.5 rounded-md bg-accent-primary/20 hover:bg-accent-primary/30 text-accent-primary text-[11px] font-bold transition-all"
                      >
                        RETRY STREAM
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Input Area */}
        <div className="p-6 bg-white/3 border-t border-border-subtle backdrop-blur-md">
          <div className="relative">
            <textarea
               value={inputStr}
               onChange={e => setInputStr(e.target.value)}
               onKeyDown={handleKeyDown}
               placeholder="Enter your query..."
               className="w-full glass-void border border-border-subtle rounded-xl py-4 pl-5 pr-14 text-sm focus:outline-none focus:border-border-glow resize-none h-[80px] custom-scrollbar text-text-primary transition-all shadow-inner"
               disabled={isStreaming}
            />
            <div className="absolute right-3 bottom-3 flex items-center gap-2">
              <button
                onClick={() => clearSession(item.id)}
                title="Clear Session"
                className="p-2 text-text-ghost hover:text-accent-critical transition-all rounded-lg hover:bg-accent-critical/10"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              <button
                 onClick={handleSend}
                 disabled={!inputStr.trim() || isStreaming}
                 className="p-2 text-white bg-accent-primary rounded-lg shadow-glow-primary hover:scale-105 active:scale-95 disabled:opacity-50 disabled:scale-100 disabled:shadow-none transition-all"
              >
                 {isStreaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div className="mt-3 flex justify-between items-center px-1">
            <span className="text-[10px] font-display font-medium text-text-ghost uppercase tracking-widest">
              grounded in {item.source.name}
            </span>
            <span className="text-[10px] font-mono text-text-ghost">
              Shift + Enter for new line
            </span>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
