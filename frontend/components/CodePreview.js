export default function CodePreview({ content = '', filename = 'generated.py' }) {
  return (
    <div className="code-preview">
      <div className="preview-header">
        <span>📄 {filename}</span>
        <span className="preview-badge">READY</span>
      </div>
      <div className="preview-body">
        <pre>{content}</pre>
      </div>
    </div>
  )
}
