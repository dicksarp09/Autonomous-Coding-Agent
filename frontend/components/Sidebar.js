import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'

export default function Sidebar({ onFileSelect, selectedFile }) {
  const [files, setFiles] = useState([
    { type: 'folder', name: 'workspace', expanded: true },
  ])
  const [generatedFiles, setGeneratedFiles] = useState([])

  useEffect(() => {
    // Poll for generated files from the backend
    const interval = setInterval(async () => {
      try {
        // Try to fetch from agent workspace
        const response = await fetch('http://127.0.0.1:8000/files')
        if (response.ok) {
          const data = await response.json()
          if (data.files) {
            setGeneratedFiles(data.files)
          }
        }
      } catch (e) {
        // Backend might not have this endpoint, that's ok
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  const allFiles = [
    { type: 'folder', name: 'workspace', expanded: true },
    ...generatedFiles.map(f => ({ type: 'file', name: f }))
  ]

  return (
    <motion.aside className="sidebar" initial={{ x: -20, opacity: 0 }} animate={{ x: 0, opacity: 1 }}>
      <div className="sidebar-header">
        📁 project/
      </div>
      <ul className="file-list">
        {allFiles.map((f, idx) => (
          <li 
            key={idx} 
            className={`file-row ${f.type} ${selectedFile === f.name ? 'selected' : ''}`}
            onClick={() => onFileSelect && onFileSelect(f.name)}
            style={{ cursor: onFileSelect ? 'pointer' : 'default' }}
          >
            <span className="file-icon">
              {f.type === 'folder' ? '📁' : '📄'}
            </span>
            <span className="file-name">{f.name}</span>
          </li>
        ))}
        
        {generatedFiles.length === 0 && (
          <li className="file-row" style={{ opacity: 0.5, fontStyle: 'italic' }}>
            <span className="file-icon">✨</span>
            <span className="file-name">No generated files yet</span>
          </li>
        )}
      </ul>
      
      <div style={{ 
        marginTop: 'auto', 
        padding: '10px', 
        borderTop: '1px solid #333',
        fontSize: '10px',
        color: '#666'
      }}>
        <div>Agent Status: Ready</div>
        <div>Groq API: Connected</div>
      </div>
    </motion.aside>
  )
}
