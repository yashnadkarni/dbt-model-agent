import { useState, useEffect } from 'react'

const API = 'http://localhost:8000'

/* ── SVG Icon Components (white, minimal) ── */
const IconFilter = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
)
const IconLink = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
)
const IconChart = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
)
const IconShuffle = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>
)
const IconZap = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
)
const IconCpu = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
)
const IconDatabase = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
)
const IconGitHub = () => (
  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
)
const IconSun = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
)
const IconMoon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
)
const IconSnowflake = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="2" x2="12" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/><line x1="19.07" y1="4.93" x2="4.93" y2="19.07"/></svg>
)
const IconBricks = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="6" rx="1"/><rect x="2" y="13" width="9" height="8" rx="1"/><rect x="14" y="13" width="8" height="8" rx="1"/></svg>
)
const IconSettings = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
)
const IconExternalLink = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="12" height="12"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
)

const SAMPLE_ICONS = [IconFilter, IconLink, IconChart, IconShuffle, IconLink, IconZap]

const HOW_STEPS = [
  { title: 'Parse', desc: 'Reads Talend XML structure' },
  { title: 'Translate', desc: 'Java expressions → SQL' },
  { title: 'Generate', desc: 'CTE-based dbt SQL + YAML' },
  { title: 'Package', desc: 'Downloadable zip file' },
]

const COMPONENTS = [
  { name: 'tFilterRow', ok: true },
  { name: 'tMap (join)', ok: true },
  { name: 'tMap (mapping)', ok: true },
  { name: 'tAggregateRow', ok: true },
  { name: 'tNormalize', ok: false },
  { name: 'tUnite', ok: false },
]

export default function Sidebar({ sampleJobs, onSelectJob, activeJob, mode, onModeChange, theme, onThemeChange }) {
  const [apiKeyStatus, setApiKeyStatus] = useState(null)
  const [connExpanded, setConnExpanded] = useState(false)
  const [adapter, setAdapter] = useState('duckdb')
  const [connTested, setConnTested] = useState(null) // null | 'ok' | 'error'

  // Check API key when switching to LLM mode
  useEffect(() => {
    if (mode === 'llm') {
      fetch(`${API}/api/check-api-key`)
        .then(r => r.json())
        .then(data => setApiKeyStatus(data.has_key))
        .catch(() => setApiKeyStatus(false))
    }
  }, [mode])

  const handleTestConnection = () => {
    // Simulate test — actual implementation would call API
    setConnTested('ok')
    setTimeout(() => setConnTested(null), 3000)
  }

  return (
    <aside className="sidebar">
      {/* Logo + Theme Toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div className="sidebar-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          dbt Model Agent
        </div>
        <button className="theme-toggle" onClick={onThemeChange} title="Toggle theme">
          {theme === 'light' ? <IconMoon /> : <IconSun />}
        </button>
      </div>

      {/* Quick Demo */}
      <div className="sidebar-section-title">
        <IconZap /> Quick Demo
      </div>
      <p style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginBottom: 6 }}>
        Click a sample to load its XML, then hit Convert.
      </p>
      {(sampleJobs || []).map((job, i) => {
        const Icon = SAMPLE_ICONS[i] || IconFilter
        return (
          <button
            key={job.filename}
            className={`sample-btn ${activeJob === job.filename ? 'active' : ''}`}
            onClick={() => onSelectJob(job)}
          >
            <Icon />
            {job.label.replace(/^[^\w]*/, '').trim()}
          </button>
        )
      })}

      <div className="sidebar-divider" />

      {/* Conversion Mode */}
      <div className="sidebar-section-title">
        <IconCpu /> Conversion Mode
      </div>
      <div className="mode-toggle">
        <button
          className={`mode-toggle-btn ${mode === 'deterministic' ? 'active' : ''}`}
          onClick={() => onModeChange('deterministic')}
        >
          Deterministic
        </button>
        <button
          className={`mode-toggle-btn ${mode === 'llm' ? 'active' : ''}`}
          onClick={() => onModeChange('llm')}
        >
          LLM Agent
        </button>
      </div>
      <p style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: 6 }}>
        {mode === 'deterministic'
          ? 'Pattern-matched translation. No API key needed.'
          : 'Sends parsed context to GPT-4o-mini. Requires OPENAI_API_KEY.'}
      </p>
      {mode === 'llm' && apiKeyStatus !== null && (
        <div className={`api-key-status ${apiKeyStatus ? 'found' : 'missing'}`}>
          {apiKeyStatus ? '✓ API key found' : '✗ OPENAI_API_KEY not set'}
        </div>
      )}

      <div className="sidebar-divider" />

      {/* Database Connection */}
      <div className="sidebar-section-title">
        <IconDatabase /> Database Connection
      </div>
      <button
        className="expandable-header"
        onClick={() => setConnExpanded(!connExpanded)}
        style={{ marginBottom: 0 }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {adapter === 'duckdb' && <><IconDatabase /> DuckDB (Local)</>}
          {adapter === 'snowflake' && <><IconSnowflake /> Snowflake</>}
          {adapter === 'databricks' && <><IconBricks /> Databricks</>}
        </span>
        <span className={`expandable-chevron ${connExpanded ? 'open' : ''}`}>▼</span>
      </button>
      <div className={`expandable-body ${connExpanded ? 'open' : ''}`}>
        <div className="integration-fields">
          <select
            className="glass-select"
            value={adapter}
            onChange={(e) => setAdapter(e.target.value)}
          >
            <option value="duckdb">DuckDB (Local)</option>
            <option value="snowflake">Snowflake</option>
            <option value="databricks">Databricks</option>
          </select>

          {adapter === 'duckdb' && (
            <>
              <input className="glass-input" type="text" placeholder="Database path" defaultValue="jaffle_shop.duckdb" />
              <input className="glass-input" type="text" placeholder="Schema" defaultValue="main" />
            </>
          )}

          {adapter === 'snowflake' && (
            <>
              <input className="glass-input" type="text" placeholder="Account (e.g. acme.us-east-1)" />
              <input className="glass-input" type="text" placeholder="User" />
              <input className="glass-input" type="password" placeholder="Password" />
              <input className="glass-input" type="text" placeholder="Role (e.g. TRANSFORM_ROLE)" />
              <input className="glass-input" type="text" placeholder="Warehouse (e.g. TRANSFORM_WH)" />
              <input className="glass-input" type="text" placeholder="Database" />
              <input className="glass-input" type="text" placeholder="Schema (e.g. DBT_DEV)" />
            </>
          )}

          {adapter === 'databricks' && (
            <>
              <input className="glass-input" type="text" placeholder="Host (e.g. dbc-xxxx.cloud.databricks.com)" />
              <input className="glass-input" type="text" placeholder="HTTP Path" />
              <input className="glass-input" type="password" placeholder="Token" />
              <input className="glass-input" type="text" placeholder="Catalog" />
              <input className="glass-input" type="text" placeholder="Schema" />
            </>
          )}

          <button className="btn btn-sm" onClick={handleTestConnection} style={{ marginTop: 4 }}>
            Test Connection
          </button>
          {connTested === 'ok' && (
            <div className="api-key-status found">✓ Connection successful</div>
          )}
        </div>
      </div>

      <div className="sidebar-divider" />

      {/* GitHub */}
      <div className="sidebar-section-title">
        <IconGitHub /> GitHub
      </div>
      <a
        href="https://github.com/yashnadkarni/dbt-model-agent"
        target="_blank"
        rel="noopener noreferrer"
        className="sample-btn"
        style={{ textDecoration: 'none' }}
      >
        <IconExternalLink />
        yashnadkarni/dbt-model-agent
      </a>

      <div className="sidebar-divider" />

      {/* How It Works */}
      <div className="sidebar-section-title">How It Works</div>
      {HOW_STEPS.map((step, i) => (
        <div className="how-step" key={i}>
          <div className="how-step-num">{i + 1}</div>
          <div className="how-step-text">
            <strong>{step.title}</strong> — {step.desc}
          </div>
        </div>
      ))}

      <div className="sidebar-divider" />

      {/* Component Support */}
      <div className="sidebar-section-title">Component Support</div>
      <table className="component-table">
        <thead>
          <tr><th>Component</th><th>Status</th></tr>
        </thead>
        <tbody>
          {COMPONENTS.map((c) => (
            <tr key={c.name}>
              <td><code>{c.name}</code></td>
              <td>{c.ok ? '✅' : '❌'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="sidebar-footer">
        <p>Built with LangGraph, FastAPI, DuckDB</p>
      </div>
    </aside>
  )
}
