import { useState } from 'react'

const IconSearch = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
)

function ValidationStep({ step }) {
  const [open, setOpen] = useState(!step.passed)
  const icon = step.passed ? '✅' : '❌'

  return (
    <div className="validation-step" onClick={() => setOpen(!open)}>
      <div className="validation-step-header">
        <span>{icon}</span>
        <span>{step.name}</span>
        <span className="expandable-chevron" style={{ marginLeft: 'auto' }}>
          {open ? '▲' : '▼'}
        </span>
      </div>
      {open && (
        <div className="validation-step-output">{step.output}</div>
      )}
    </div>
  )
}

export default function ValidationPanel({ result, onValidate, loading }) {
  return (
    <div className="validation-section">
      <button
        className="btn btn-primary btn-validate"
        onClick={onValidate}
        disabled={loading}
        style={{ width: '100%', marginBottom: 18 }}
      >
        {loading ? (
          <>
            <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            Validating…
          </>
        ) : (
          <><IconSearch /> Validate with dbt</>
        )}
      </button>

      {result && (
        <div className="fade-in">
          <div className={`validation-result ${result.all_passed ? 'pass' : 'fail'}`}>
            {result.all_passed ? '✅ All checks passed' : '❌ Some checks failed'}
            {' — '}
            {result.label} ({result.model_name})
          </div>

          {result.steps.map((step, i) => (
            <ValidationStep key={i} step={step} />
          ))}

          <p style={{
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
            background: 'var(--warning-bg)',
            padding: '10px 14px',
            borderRadius: 12,
            marginTop: 12,
            border: '1px solid rgba(245, 158, 11, 0.15)',
          }}>
            ⚠️ Only sqlfluff lint and dbt compile are expected to pass.
            dbt run and dbt test need a connected database.
          </p>
        </div>
      )}
    </div>
  )
}
