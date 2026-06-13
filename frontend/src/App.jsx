import { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import ConvertPanel from './components/ConvertPanel'

const API = 'http://localhost:8000'

export default function App() {
  const [sampleJobs, setSampleJobs] = useState([])
  const [activeJob, setActiveJob] = useState(null)
  const [xmlContent, setXmlContent] = useState('')
  const [mode, setMode] = useState('deterministic')
  const [uploadFilename, setUploadFilename] = useState('')
  const [theme, setTheme] = useState('light')

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // Fetch sample jobs on mount
  useEffect(() => {
    fetch(`${API}/api/sample-jobs`)
      .then((r) => r.json())
      .then((data) => setSampleJobs(data.jobs || []))
      .catch(() => {})
  }, [])

  const handleSelectJob = (job) => {
    setActiveJob(job.filename)
    setXmlContent(job.xml_content || '')
    setUploadFilename(job.filename)
  }

  const toggleTheme = () => {
    setTheme(t => t === 'light' ? 'dark' : 'light')
  }

  return (
    <div className="app-layout">
      <Sidebar
        sampleJobs={sampleJobs}
        onSelectJob={handleSelectJob}
        activeJob={activeJob}
        mode={mode}
        onModeChange={setMode}
        theme={theme}
        onThemeChange={toggleTheme}
      />
      <main className="main-content">
        <ConvertPanel
          xmlContent={xmlContent}
          setXmlContent={setXmlContent}
          mode={mode}
          uploadFilename={uploadFilename}
          setUploadFilename={setUploadFilename}
        />
      </main>
    </div>
  )
}
