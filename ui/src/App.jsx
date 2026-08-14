/**
 * App.jsx — PLC Digital Twin Dashboard
 *
 * Layout:
 *   Top half  → 3D Scene (react-three-fiber)
 *   Bottom    → 2D status panels (motor, sensors, timeline)
 */

import { useEffect, useState } from 'react'
import Scene from './Scene'
import './App.css'

const API_URL = 'http://localhost:5174/state'
const POLL_MS = 100

// ── Backend state hook ────────────────────────────────────────
function useBackendState() {
  const [state, setState] = useState({
    time: 0,
    motor_running: false,
    shuttle_position: 0,
    sensors: { X0: false, X1: false, X2: false },
    jam_detected: false,
  })
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const res = await fetch(API_URL)
        const data = await res.json()
        if (active) { setState(data); setConnected(true); setError(null) }
      } catch {
        if (active) { setConnected(false); setError('API offline') }
      }
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => { active = false; clearInterval(id) }
  }, [])

  return { state, connected, error }
}

// ── Connection badge ──────────────────────────────────────────
function ConnBadge({ connected, error }) {
  return (
    <div className={`conn-badge ${connected ? 'ok' : 'err'}`}>
      {connected ? '● Connected' : `○ Disconnected${error ? ` — ${error}` : ''}`}
    </div>
  )
}

// ── Motor indicator ───────────────────────────────────────────
function MotorIndicator({ running }) {
  return (
    <div className={`motor-indicator ${running ? 'running' : 'stopped'}`}>
      <span className="motor-dot" />
      <span className="motor-label">Motor: {running ? 'RUNNING' : 'STOPPED'}</span>
    </div>
  )
}

// ── Sensor panel ──────────────────────────────────────────────
function SensorPanel({ sensors }) {
  const labels = { X0: 'Start (X0)', X1: 'Position (X1)', X2: 'Jam (X2)' }
  return (
    <div className="sensor-panel">
      <h3>Sensors</h3>
      {Object.entries(sensors).map(([k, v]) => (
        <div key={k} className="sensor-row">
          <span className={`sensor-light ${v ? 'on' : 'off'}`} />
          <span className="sensor-name">{labels[k] || k}</span>
          <span className={`sensor-value ${v ? 'on' : 'off'}`}>{v ? 'ON' : 'OFF'}</span>
        </div>
      ))}
    </div>
  )
}

// ── Timeline ──────────────────────────────────────────────────
function Timeline({ timeMs }) {
  const mins = Math.floor(timeMs / 60000)
  const s = ((timeMs % 60000) / 1000).toFixed(1).padStart(4, '0')
  return (
    <div className="timeline">
      <span className="timeline-label">Sim Time</span>
      <span className="timeline-value">{mins > 0 ? `${mins}m ` : ''}{s}s</span>
      <span className="timeline-ms">{timeMs} ms</span>
    </div>
  )
}

// ── Jam alert ─────────────────────────────────────────────────
function JamAlert({ active }) {
  if (!active) return null
  return <div className="jam-alert" role="alert">⚠ JAM DETECTED — Motor stopping</div>
}

// ── Main app ──────────────────────────────────────────────────
export default function App() {
  const { state, connected, error } = useBackendState()

  return (
    <div className="dashboard">
      <header className="dash-header">
        <h1>PLC Digital Twin — 3D View</h1>
        <ConnBadge connected={connected} error={error} />
      </header>

      <JamAlert active={state.jam_detected} />

      {/* 3D viewport */}
      <div className="viewport">
        <Scene state={state} />
      </div>

      {/* 2D status strip */}
      <div className="status-strip">
        <div className="card">
          <MotorIndicator running={state.motor_running} />
        </div>
        <div className="card">
          <SensorPanel sensors={state.sensors} />
        </div>
        <div className="card">
          <Timeline timeMs={state.time} />
        </div>
      </div>
    </div>
  )
}
