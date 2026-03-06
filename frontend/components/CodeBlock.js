import { useState } from 'react'
import { motion } from 'framer-motion'

export default function CodeBlock({ code, language = 'python' }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      // ignore
    }
  }

  return (
    <motion.div className="code-block" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="code-toolbar">
        <button className="copy-btn" onClick={copy}>{copied ? 'Copied' : 'Copy Code'}</button>
      </div>
      <pre>
        <code>
{code}
        </code>
      </pre>
    </motion.div>
  )
}
