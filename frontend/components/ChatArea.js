import MessageBubble from './MessageBubble'
import CodeBlock from './CodeBlock'
import { useState } from 'react'

export default function ChatArea({ messages = [], onSendMessage, status }) {
  const [input, setInput] = useState('')

  const handleSend = () => {
    if (input.trim() && onSendMessage) {
      onSendMessage(input)
      setInput('')
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Show loading state when agent is processing
  const isProcessing = status?.status === 'starting' || status?.status === 'running'

  // Determine if we should show welcome screen
  const showWelcome = messages.length === 0 && !isProcessing

  return (
    <main className="chat-area">
      <div className="chat-header">
        <span className="status-dot"></span>
        CHAT
      </div>
      <div className="chat-body">
        {showWelcome ? (
          <div className="welcome-container">
            <div className="welcome-emoji">🤖</div>
            <div className="welcome-title">Welcome to Coding Agent</div>
            <div className="welcome-subtitle">
              Your AI-powered developer assistant. Describe what you want to build.
            </div>
            <div className="welcome-example">
              "Create a linear regression with gradient descent"
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <MessageBubble key={idx} role={msg.role}>
              {msg.content}
              {msg.code && <CodeBlock code={msg.code} language="python" />}
            </MessageBubble>
          ))
        )}
        
        {isProcessing && (
          <MessageBubble role="agent">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>Analyzing and generating code</span>
              <span className="loading-dots">
                <span>.</span><span>.</span><span>.</span>
              </span>
            </div>
          </MessageBubble>
        )}
      </div>
      <div className="chat-input">
        <input 
          type="text" 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Describe what you want to build..."
          disabled={isProcessing}
        />
        <button 
          onClick={handleSend}
          disabled={isProcessing || !input.trim()}
        >
          {isProcessing ? 'Generating...' : 'Generate Code'}
        </button>
      </div>
    </main>
  )
}
