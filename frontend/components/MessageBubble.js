export default function MessageBubble({ role, children }) {
  const isUser = role === 'user'
  
  return (
    <div className={`message ${isUser ? 'user' : 'agent'}`}>
      {children}
      <div className="message-time">
        {isUser ? 'You' : 'Agent'} • {new Date().toLocaleTimeString()}
      </div>
    </div>
  )
}
