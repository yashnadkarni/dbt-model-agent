import { useState, useRef } from 'react'
import ValidationPanel from './ValidationPanel'

const API = 'http://localhost:8000'

/* ── SVG Icons (white, minimal) ── */
const IconClipboard = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>
)
const IconUpload = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
)
const IconRocket = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>
)
const IconRefresh = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
)
const IconDownload = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
)
const IconFileText = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
)
const IconPackage = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
)
const IconAlertTriangle = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
)

function Expandable({ title, icon, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="expandable">
      <button className="expandable-header" onClick={() => setOpen(!open)}>
        {icon} {title}
        <span className={`expandable-chevron ${open ? 'open' : ''}`}>▼</span>
      </button>
      <div className={`expandable-body ${open ? 'open' : ''}`}>
        {children}
      </div>
    </div>
  )
}

export default function ConvertPanel({ xmlContent, setXmlContent, mode, uploadFilename, setUploadFilename }) {
  const [activeTab, setActiveTab] = useState('paste')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [validationResult, setValidationResult] = useState(null)
  const [validating, setValidating] = useState(false)
  const fileInputRef = useRef(null)

  const handleConvert = async () => {
    if (!xmlContent || !xmlContent.trim()) return
    setLoading(true)
    setResult(null)
    setValidationResult(null)

    try {
      const resp = await fetch(`${API}/api/convert`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          xml_content: xmlContent,
          filename: uploadFilename || 'job.item',
          use_llm: mode === 'llm',
        }),
      })

      if (!resp.ok) {
        const err = await resp.json()
        setResult({ success: false, error: err.detail || 'Conversion failed' })
      } else {
        const data = await resp.json()
        setResult(data)
      }
    } catch (err) {
      setResult({ success: false, error: err.message })
    } finally {
      setLoading(false)
    }
  }

  const handleValidate = async () => {
    if (!result || !result.deterministic) return
    setValidating(true)
    setValidationResult(null)

    try {
      const d = result.deterministic
      const resp = await fetch(`${API}/api/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: d.model_name,
          source_name: d.source_name,
          sql_content: d.sql_content,
          schema_yaml: d.schema_yaml,
          source_yaml: d.source_yaml,
          label: 'Deterministic',
        }),
      })
      const data = await resp.json()
      setValidationResult(data)
    } catch (err) {
      setValidationResult({ all_passed: false, label: 'Deterministic', model_name: '?', steps: [{ name: 'Request', passed: false, output: err.message }] })
    } finally {
      setValidating(false)
    }
  }

  const handleDownload = async (source, label) => {
    try {
      const resp = await fetch(`${API}/api/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: source.model_name,
          source_name: source.source_name,
          sql_content: source.sql_content,
          schema_yaml: source.schema_yaml,
          source_yaml: source.source_yaml,
        }),
      })
      const blob = await resp.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${source.model_name}_${label}_dbt.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Download failed:', err)
    }
  }

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadFilename(file.name)
    const reader = new FileReader()
    reader.onload = (ev) => {
      setXmlContent(ev.target.result)
      setActiveTab('paste')
    }
    reader.readAsText(file)
  }

  const handleRefresh = () => {
    setResult(null)
    setValidationResult(null)
  }

  const det = result?.deterministic
  const llm = result?.llm
  const hasLlm = llm && llm.sql_content

  return (
    <div>
      {/* Header with glass title */}
      <div className="header">
        <h1>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          <span className="glass-title">dbt Model Agent</span>
        </h1>
        <p>Convert Talend ETL jobs into production-ready dbt models deterministically and via AI agents.</p>
      </div>

      {/* Input Panel */}
      <div className="glass-panel">
        <div className="tab-bar">
          <button
            className={`tab-btn ${activeTab === 'paste' ? 'active' : ''}`}
            onClick={() => setActiveTab('paste')}
          >
            <IconClipboard /> Paste XML
          </button>
          <button
            className={`tab-btn ${activeTab === 'upload' ? 'active' : ''}`}
            onClick={() => setActiveTab('upload')}
          >
            <IconUpload /> Upload File
          </button>
        </div>

        {activeTab === 'paste' ? (
          <textarea
            className="xml-textarea"
            value={xmlContent}
            onChange={(e) => setXmlContent(e.target.value)}
            placeholder={'<?xml version="1.0" encoding="UTF-8"?>\n<xmi:XMI ...>\n  ...\n</xmi:XMI>'}
          />
        ) : (
          <div className="file-upload" onClick={() => fileInputRef.current?.click()}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".item,.xml"
              onChange={handleFileUpload}
            />
            <div className="file-upload-label">
              <span className="icon">↑</span>
              {uploadFilename ? (
                <span>Loaded: <strong>{uploadFilename}</strong></span>
              ) : (
                <span>Drop a Talend .item file or click to browse</span>
              )}
            </div>
          </div>
        )}

        <div className="btn-row">
          <button
            className="btn btn-primary btn-convert"
            onClick={handleConvert}
            disabled={loading || !xmlContent?.trim()}
            style={{ flex: 1 }}
          >
            {loading ? (
              <>
                <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                Converting…
              </>
            ) : (
              <><IconRocket /> Convert to dbt</>
            )}
          </button>
          {result && (
            <button className="btn" onClick={handleRefresh}>
              <IconRefresh /> Refresh
            </button>
          )}
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="glass-panel fade-in" style={{ marginTop: 20 }}>
          <div className="spinner-overlay">
            <div className="spinner" />
            {mode === 'llm' ? 'Running LLM agent — this may take a moment…' : 'Converting…'}
          </div>
        </div>
      )}

      {/* Error */}
      {result && !result.success && !result.deterministic && (
        <div className="banner banner-error fade-in" style={{ marginTop: 20 }}>
          ❌ Conversion failed: {result.error}
        </div>
      )}

      {/* Results */}
      {det && (
        <div className="fade-in" style={{ marginTop: 24 }}>
          {/* Success Banner */}
          <div className="banner banner-success">
            ✅ Converted successfully → <code style={{ margin: '0 6px', background: 'var(--glass-bg)', padding: '2px 8px', borderRadius: 6 }}>{det.model_name}.sql</code>
            <span className="badge badge-deterministic">Deterministic</span>
            {hasLlm && <span className="badge badge-llm" style={{ marginLeft: 6 }}>LLM</span>}
          </div>

          {/* LLM Error */}
          {result.llm_error && (
            <div className="warning-item">
              <IconAlertTriangle /> LLM conversion failed: {result.llm_error}
            </div>
          )}

          {/* Metrics */}
          <div className="metrics-row">
            {[
              { value: result.metrics.sources, label: 'Sources' },
              { value: result.metrics.transforms, label: 'Transforms' },
              { value: result.metrics.targets, label: 'Targets' },
              { value: result.metrics.connections, label: 'Connections' },
            ].map((m) => (
              <div className="glass-panel metric-card" key={m.label}>
                <div className="metric-value">{m.value}</div>
                <div className="metric-label">{m.label}</div>
              </div>
            ))}
          </div>

          {/* Pipeline */}
          <div className="glass-panel pipeline-bar">
            <code>{det.source_tables.join(', ')}</code>
            <span className="pipeline-arrow">→</span>
            <span className="pipeline-converter">Converter</span>
            <span className="pipeline-arrow">→</span>
            <code>{det.model_name}.sql</code>
          </div>

          {/* Code Output */}
          {hasLlm ? (
            <div className="results-grid">
              <div className="code-section">
                <div className="code-section-title">
                  <IconFileText /> Deterministic Output
                  <span className="badge badge-deterministic" style={{ marginLeft: 6 }}>DET</span>
                </div>
                <div className="code-block">{det.sql_content}</div>
              </div>
              <div className="code-section">
                <div className="code-section-title">
                  <IconCpu /> LLM Output
                  <span className="badge badge-llm" style={{ marginLeft: 6 }}>LLM</span>
                </div>
                <div className="code-block">{llm.sql_content}</div>
              </div>
            </div>
          ) : (
            <div className="results-grid">
              <div className="code-section">
                <div className="code-section-title"><IconFileText /> {det.model_name}.sql</div>
                <div className="code-block">{det.sql_content}</div>
              </div>
              <div className="code-section">
                <div className="code-section-title"><IconFileText /> {det.model_name}_schema.yml</div>
                <div className="code-block">{det.schema_yaml}</div>
              </div>
            </div>
          )}

          {/* LLM YAML expandables */}
          {hasLlm && llm.schema_yaml && (
            <Expandable title="LLM Schema YAML" icon={<IconCpu />}>
              <div className="code-block">{llm.schema_yaml}</div>
            </Expandable>
          )}
          {hasLlm && llm.source_yaml && (
            <Expandable title="LLM Source YAML" icon={<IconCpu />}>
              <div className="code-block">{llm.source_yaml}</div>
            </Expandable>
          )}

          {hasLlm && (
            <Expandable title="Deterministic Schema YAML" icon={<IconFileText />}>
              <div className="code-block">{det.schema_yaml}</div>
            </Expandable>
          )}

          {/* Sources YAML */}
          <Expandable title={`${det.source_name}_sources.yml`} icon={<IconPackage />}>
            <div className="code-block">{det.source_yaml}</div>
          </Expandable>

          {/* Warnings */}
          {det.warnings && det.warnings.length > 0 && (
            <Expandable title="Warnings" icon={<IconAlertTriangle />} defaultOpen>
              {det.warnings.map((w, i) => (
                <div className="warning-item" key={i}><IconAlertTriangle /> {w}</div>
              ))}
            </Expandable>
          )}

          {/* Download Buttons */}
          <div className="btn-row" style={{ marginTop: 20 }}>
            <button className="btn btn-primary btn-download" onClick={() => handleDownload(det, 'deterministic')} style={{ flex: 1 }}>
              <IconDownload /> Download Deterministic Output
            </button>
            {hasLlm && (
              <button className="btn btn-download" onClick={() => handleDownload(llm, 'llm')} style={{ flex: 1 }}>
                <IconDownload /> Download LLM Output
              </button>
            )}
          </div>

          {/* Validation */}
          <ValidationPanel
            result={validationResult}
            onValidate={handleValidate}
            loading={validating}
          />
        </div>
      )}
    </div>
  )
}

/* Re-export the icon for use in other components */
const IconCpu = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
)
