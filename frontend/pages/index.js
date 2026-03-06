import Head from 'next/head'
import { useState, useEffect } from 'react'
import Sidebar from '../components/Sidebar'
import ChatArea from '../components/ChatArea'
import CodePreview from '../components/CodePreview'

export default function Home() {
  const [runId, setRunId] = useState(null)
  const [status, setStatus] = useState(null)
  const [generatedCode, setGeneratedCode] = useState('')
  const [messages, setMessages] = useState([])

  useEffect(() => {
    let interval
    if (runId) {
      interval = setInterval(async () => {
        try {
          const res = await fetch(`http://127.0.0.1:8000/status/${runId}`)
          const data = await res.json()
          setStatus(data)
          
          // Extract generated code from result
          if (data.result && data.result.includes('generated_code')) {
            try {
              const codeMatch = data.result.match(/generated_code='([^']+)'/s)
              if (codeMatch) {
                const code = codeMatch[1].replace(/\\n/g, '\n')
                setGeneratedCode(code)
                
                // Update the last agent message with the code
                setMessages(prev => {
                  const updated = [...prev]
                  const lastIdx = updated.length - 1
                  if (lastIdx >= 0 && updated[lastIdx].role === 'agent') {
                    updated[lastIdx] = { 
                      ...updated[lastIdx], 
                      content: 'Code generated successfully! Ready to use.',
                      code: code
                    }
                  }
                  return updated
                })
              }
            } catch (e) {
              console.log('Could not parse code from result')
            }
          }
          
          if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(interval)
            if (data.status === 'failed') {
              setMessages(prev => [...prev, { 
                role: 'agent', 
                content: `Something went wrong: ${data.error || 'Workflow failed'}`
              }])
            }
          }
        } catch (e) {
          setStatus({ status: 'error', error: String(e) })
        }
      }, 1500)
    }
    return () => clearInterval(interval)
  }, [runId])

  async function startRun(inputGoal) {
    if (!inputGoal.trim()) return
    
    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: inputGoal }])
    setStatus({ status: 'starting' })
    setGeneratedCode('')
    
    try {
      const res = await fetch('http://127.0.0.1:8000/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: inputGoal, max_iterations: 3 }),
      })
      const data = await res.json()
      setRunId(data.run_id)
      setStatus({ status: data.status })
      
      // Add agent message that we're processing
      setMessages(prev => [...prev, { role: 'agent', content: 'Analyzing your request and generating code...' }])
    } catch (e) {
      setStatus({ status: 'error', error: String(e) })
      setMessages(prev => [...prev, { 
        role: 'agent', 
        content: `Connection error: Unable to reach the backend. Please ensure it's running.`
      }])
    }
  }

  // Determine code preview content
  let previewContent = generatedCode
  if (!previewContent) {
    if (status?.status === 'running' || status?.status === 'starting') {
      previewContent = '// ⏳ Analyzing and generating code...\n// Please wait...'
    } else if (status?.status === 'error') {
      previewContent = `// ❌ Error: ${status.error || 'Unknown error'}\n\n// Ensure backend is running at http://127.0.0.1:8000`
    } else {
      previewContent = `// ⚡ Coding Agent\n// \n// Describe what you want to build in the chat,\n// and I'll generate the code for you.\n//\n// Example: "Create a linear regression with gradient descent"\n\ndef hello():\n    print("Hello, World!")`
    }
  }

  return (
    <>
      <Head>
        <title>CODING AGENT ⚡</title>
        <meta name="viewport" content="initial-scale=1.0, width=device-width" />
        <meta name="description" content="AI-powered autonomous coding agent" />
      </Head>
      <div className="layout">
        <Sidebar />
        <ChatArea 
          messages={messages} 
          onSendMessage={startRun}
          status={status}
        />
        <CodePreview content={previewContent} />
      </div>
    </>
  )
}
