/**
 * PLC Digital Twin Dashboard
 *
 * Steps 2-10:
 *  2 - Polls /state every 100ms
 *  3 - Canvas shuttle circle with rotating marker
 *  4 - Motor indicator (green/red)
 *  5 - Sensor ON/OFF lights
 *  6 - Jam alert banner
 *  7 - Smooth animation via requestAnimationFrame interpolation
 *  8 - Timeline / simulation time display
 *  9 - Clean layout
 * 10 - Connects to real api_server.py
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import './App.css'

const API_URL = 'http://localhost:5174/state'
const POLL_MS = 100          // fetch interval
const CYCLE = 360          // shuttle track degrees

// ---------------------------------------------------------------------------
// Custom hook: poll backend state
// ---------------------------------------------------------------------------
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
        if (active) {
          setState(data)
          setConnected(true)
          setError(null)
        }
      } catch (e) {
        if (active) {
          setConnected(false)
          setError('Cannot reach API — is api_server.py running?')
        }
      }
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => { active = false; clearInterval(id) }
  }, [])

  return { state, connected, error }
}

// ---------------------------------------------------------------------------
// Step 3 + 7: Shuttle canvas with smooth interpolation
// ---------------------------------------------------------------------------
function ShuttleCanvas({ position, motorRunning, jamDetected }) {
  const canvasRef = useRef(null)
  const smoothPos = useRef(position)   // interpolated position
  const targetPos = useRef(position)
  const rafRef = useRef(null)

  // Update target whenever prop changes
  useEffect(() => {
    targetPos.current = position
  }, [position])

  // Animation loop — interpolates toward target
  const animate = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height
    const cx = W / 2
    const cy = H / 2
    const R = Math.min(W, H) / 2 - 20   // track radius

    // Step 7: smooth interpolation (lerp)
    const diff = targetPos.current - smoothPos.current
    // Handle wrap-around (e.g. 359 → 1)
    let delta = diff
    if (Math.abs(diff) > 180) {
      delta = diff > 0 ? diff - 360 : diff + 360
    }
    smoothPos.current += delta * 0.15   // lerp factor
    if (smoothPos.current < 0) smoothPos.current += 360
    if (smoothPos.current >= 360) smoothPos.current -= 360

    const angle = (smoothPos.current - 90) * (Math.PI / 180)

    // Clear
    ctx.clearRect(0, 0, W, H)

    // Track circle
    ctx.beginPath()
    ctx.arc(cx, cy, R, 0, Math.PI * 2)
    ctx.strokeStyle = jamDetected ? '#ef4444' : '#334155'
    ctx.lineWidth = jamDetected ? 3 : 2
    ctx.stroke()

    // Direction ticks (every 45°)
    for (let deg = 0; deg < 360; deg += 45) {
      const a = (deg - 90) * (Math.PI / 180)
      const x1 = cx + (R - 6) * Math.cos(a)
      const y1 = cy + (R - 6) * Math.sin(a)
      const x2 = cx + (R + 6) * Math.cos(a)
      const y2 = cy + (R + 6) * Math.sin(a)
      ctx.beginPath()
      ctx.moveTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.strokeStyle = '#475569'
      ctx.lineWidth = 1
      ctx.stroke()
    }

    // Sensor zone highlight (180°–200°)
    const sStart = (180 - 90) * (Math.PI / 180)
    const sEnd = (200 - 90) * (Math.PI / 180)
    ctx.beginPath()
    ctx.arc(cx, cy, R, sStart, sEnd)
    ctx.strokeStyle = '#f59e0b'
    ctx.lineWidth = 4
    ctx.stroke()

    // Shuttle marker
    const mx = cx + R * Math.cos(angle)
    const my = cy + R * Math.sin(angle)
    ctx.beginPath()
    ctx.arc(mx, my, 10, 0, Math.PI * 2)
    ctx.fillStyle = jamDetected ? '#ef4444'
      : motorRunning ? '#22c55e'
        : '#64748b'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()

    // Centre label
    ctx.fillStyle = '#94a3b8'
    ctx.font = '12px monospace'
    ctx.textAlign = 'center'
    ctx.fillText(`${Math.round(smoothPos.current)}°`, cx, cy + 4)

    rafRef.current = requestAnimationFrame(animate)
  }, [motorRunning, jamDetected])

  useEffect(() => {
    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [animate])

  return (
    <canvas
      ref={canvasRef}
      width={220}
      height={220}
      aria-label="Shuttle position"
    />
  )
}

// ---------------------------------------------------------------------------
// Step 4: Motor indicator
// ---------------------------------------------------------------------------
function MotorIndicator({ running }) {
  return (
    <div className={`motor-indicator ${running ? 'running' : 'stopped'}`}>
      <span className="motor-dot" />
      <span className="motor-label">
        Motor: {running ? 'RUNNING' : 'STOPPED'}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 5: Sensor lights
// ---------------------------------------------------------------------------
function SensorPanel({ sensors }) {
  const labels = {
    X0: 'Start (X0)',
    X1: 'Position (X1)',
    X2: 'Jam (X2)',
  }
  return (
    <div className="sensor-panel">
      <h3>Sensors</h3>
      {Object.entries(sensors).map(([key, val]) => (
        <div key={key} className="sensor-row">
          <span className={`sensor-light ${val ? 'on' : 'off'}`} />
          <span className="sensor-name">{labels[key] || key}</span>
          <span className={`sensor-value ${val ? 'on' : 'off'}`}>
            {val ? 'ON' : 'OFF'}
          </span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 6: Jam alert
// ---------------------------------------------------------------------------
function JamAlert({ active }) {
  if (!active) return null
  return (
    <div className="jam-alert" role="alert">
      ⚠ JAM DETECTED — Motor stopping
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 8: Timeline display
// ---------------------------------------------------------------------------
function Timeline({ timeMs }) {
  const secs = (timeMs / 1000).toFixed(1)
  const mins = Math.floor(timeMs / 60000)
  const s = ((timeMs % 60000) / 1000).toFixed(1).padStart(4, '0')
  return (
    <div className="timeline">
      <span className="timeline-label">Sim Time</span>
      <span className="timeline-value">
        {mins > 0 ? `${mins}m ` : ''}{s}s
      </span>
      <span className="timeline-ms">{timeMs} ms</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connection status
// ---------------------------------------------------------------------------
function ConnectionBadge({ connected, error }) {
  return (
    <div className={`conn-badge ${connected ? 'ok' : 'err'}`}>
      {connected ? '● Connected' : '○ Disconnected'}
      {error && <span className="conn-error"> — {error}</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 9: Main layout
// ---------------------------------------------------------------------------
export default function App() {
  const { state, connected, error } = useBackendState()

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dash-header">
        <h1>PLC Digital Twin</h1>
        <ConnectionBadge connected={connected} error={error} />
      </header>

      {/* Step 6: Jam alert — full width */}
      <JamAlert active={state.jam_detected} />

      {/* Main grid */}
      <div className="dash-grid">

        {/* Left: shuttle visualisation */}
        <section className="card shuttle-card">
          <h2>Circular Loom</h2>
          <ShuttleCanvas
            position={state.shuttle_position}
            motorRunning={state.motor_running}
            jamDetected={state.jam_detected}
          />
          <p className="shuttle-hint">
            Yellow arc = sensor zone (180°–200°)
          </p>
        </section>

        {/* Right: status panels */}
        <div className="status-col">

          {/* Step 4: motor */}
          <section className="card">
            <MotorIndicator running={state.motor_running} />
          </section>

          {/* Step 5: sensors */}
          <section className="card">
            <SensorPanel sensors={state.sensors} />
          </section>

          {/* Step 8: timeline */}
          <section className="card">
            <Timeline timeMs={state.time} />
          </section>

        </div>
      </div>

      {/* Raw state (dev aid) */}
      <details className="raw-state">
        <summary>Raw state (debug)</summary>
        <pre>{JSON.stringify(state, null, 2)}</pre>
      </details>
    </div>
  )
}
