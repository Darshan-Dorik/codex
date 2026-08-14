/**
 * Scene.jsx — react-three-fiber scene root
 *
 * Renders the real machine (public/loom.glb, decimated from the CAD)
 * with synthetic shuttles driven by the live twin state.
 *
 * The GLB is a build artefact, not a source file. If it has not been
 * generated yet the scene falls back to the original primitive frame
 * rather than showing a blank canvas — see ModelBoundary. Build it
 * with:
 *
 *     python3 tools/build_loom_model.py
 */

import { Canvas } from '@react-three/fiber'
import { OrbitControls, Grid, ContactShadows, Html } from '@react-three/drei'
import { Component, Suspense, useState } from 'react'

import LoomModel from './components/LoomModel'
import Shuttles from './components/Shuttles'
import LoomFrame from './components/LoomFrame'
import ShuttleRing from './components/ShuttleRing'

/** Falls back to the primitive frame when loom.glb is missing. */
class ModelBoundary extends Component {
    constructor(props) {
        super(props)
        this.state = { failed: false }
    }
    static getDerivedStateFromError() {
        return { failed: true }
    }
    componentDidCatch(err) {
        // eslint-disable-next-line no-console
        console.warn('[Scene] loom.glb unavailable, using primitive frame:', err?.message)
        this.props.onFail?.()
    }
    render() {
        return this.state.failed ? this.props.fallback : this.props.children
    }
}

function Loading() {
    return (
        <Html center>
            <div style={{
                color: '#94a3b8', font: '500 13px ui-monospace, monospace',
                background: 'rgba(15,23,42,.85)', padding: '10px 16px',
                borderRadius: 6, whiteSpace: 'nowrap',
            }}>
                loading machine model…
            </div>
        </Html>
    )
}

export default function Scene({ state = {} }) {
    const [info, setInfo] = useState(null)
    const [usingCad, setUsingCad] = useState(true)

    const jam = !!state.jam_detected
    const running = !!state.motor_running
    const pos = state.shuttle_position ?? 0

    return (
        <Canvas
            camera={{ position: [7.5, 5.5, 9], fov: 42 }}
            style={{ width: '100%', height: '100%' }}
            shadows
            dpr={[1, 2]}
            gl={{ antialias: true }}
        >
            <color attach="background" args={['#0b1120']} />
            <fog attach="fog" args={['#0b1120', 18, 42]} />

            {/* Key / fill / rim — a studio setup rather than a flat lamp */}
            <ambientLight intensity={0.35} />
            <hemisphereLight args={['#93c5fd', '#0f172a', 0.5]} />
            <directionalLight
                position={[8, 14, 6]}
                intensity={2.0}
                castShadow
                shadow-mapSize={[2048, 2048]}
                shadow-camera-near={1}
                shadow-camera-far={45}
                shadow-camera-left={-10}
                shadow-camera-right={10}
                shadow-camera-top={10}
                shadow-camera-bottom={-10}
                shadow-bias={-0.0005}
            />
            <directionalLight position={[-9, 5, -7]} intensity={0.6} color="#60a5fa" />
            <pointLight position={[0, 7, 0]} intensity={0.5} color="#e2e8f0" />

            <Suspense fallback={<Loading />}>
                <ModelBoundary
                    onFail={() => setUsingCad(false)}
                    fallback={
                        <>
                            <LoomFrame />
                            <ShuttleRing />
                        </>
                    }
                >
                    <LoomModel jam={jam} running={running} onFitted={setInfo} />
                </ModelBoundary>
            </Suspense>

            {usingCad && (
                <Shuttles positionDeg={pos} running={running} jam={jam} />
            )}

            <ContactShadows
                position={[0, 0.001, 0]}
                opacity={0.55}
                scale={22}
                blur={2.4}
                far={9}
                color="#000000"
            />

            <Grid
                args={[24, 24]}
                position={[0, 0, 0]}
                cellColor="#16233b"
                sectionColor="#26385c"
                fadeDistance={34}
                infiniteGrid
            />

            <OrbitControls
                enablePan
                enableZoom
                enableRotate
                minDistance={3}
                maxDistance={40}
                target={[0, 1.6, 0]}
                maxPolarAngle={Math.PI / 2.05}
            />

            {info && (
                <Html position={[0, 0, 0]} wrapperClass="model-badge" prepend>
                    <div style={{
                        position: 'fixed', left: 14, bottom: 12,
                        color: '#64748b', font: '500 11px ui-monospace, monospace',
                        pointerEvents: 'none', whiteSpace: 'nowrap',
                    }}>
                        CAD {info.meshes} meshes · {info.tris.toLocaleString()} tris ·
                        {' '}source span {info.spanMm} mm
                    </div>
                </Html>
            )}
        </Canvas>
    )
}
