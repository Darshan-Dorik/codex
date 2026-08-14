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

import { Canvas, useThree } from '@react-three/fiber'
import {
    OrbitControls, Grid, ContactShadows, Html, Environment, Lightformer,
} from '@react-three/drei'
import { Component, Suspense, useEffect, useMemo, useState } from 'react'

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
        console.warn('[Scene] loom.glb unavailable, using primitive frame:', err?.message)
        this.props.onFail?.()
    }
    render() {
        return this.state.failed ? this.props.fallback : this.props.children
    }
}

/**
 * Pulls the camera in to frame the loom head once it has been measured.
 *
 * The Canvas camera prop is initial-only, and a fixed position cannot be
 * right here: the model is the whole 5.7 m machine but the loom head is
 * a ~0.63-unit ring within it, so a camera framed on the machine renders
 * the part the twin actually simulates about the size of a coin. Framing
 * off the anchor keeps the loom head the subject no matter how the
 * export's extents change.
 */
function FrameOnAnchor({ anchor }) {
    const { camera } = useThree()
    useEffect(() => {
        if (!anchor) return
        const d = anchor.radius * 6
        // Position only. The Canvas camera's default near/far already
        // bracket a scene fitted to 6 units, and assigning to `camera`
        // itself is a hook value mutation that react-hooks/immutability
        // rejects — writing through camera.position is not.
        camera.position.set(
            anchor.x + d * 0.80,
            anchor.y + d * 0.55,
            anchor.z + d * 0.95,
        )
    }, [anchor, camera])
    return null
}

function Loading() {
    return (
        <Html center>
            <div style={{
                color: '#5c6b68', font: '600 11px ui-monospace, monospace',
                letterSpacing: '1.4px', textTransform: 'uppercase',
                background: 'rgba(246,247,245,.92)', padding: '10px 16px',
                border: '1px solid #c7cdca', borderRadius: 3,
                whiteSpace: 'nowrap',
            }}>
                Loading machine model
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

    const a = info?.anchor
    const orbitTarget = useMemo(
        () => (a ? [a.x, a.y, a.z] : [0, 1.6, 0]),
        [a],
    )

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
        <Canvas
            camera={{ position: [7.5, 5.5, 9], fov: 42 }}
            style={{ width: '100%', height: '100%' }}
            shadows
            dpr={[1, 2]}
            gl={{ antialias: true }}
        >
            <color attach="background" args={['#e3e6e4']} />
            <fog attach="fog" args={['#e3e6e4', 6, 26]} />

            {/* Bright overcast, the light a plant floor actually has:
                a strong key from above, a cool bounce from the floor,
                and no coloured rim — tinted rims read as styling on a
                light ground and make the steel look plastic. */}
            {/* Fill is kept well below the key. Matching them lights
                every face equally, which erases the shading that tells
                you the machine has depth — it goes flat and ghostly
                against a pale floor. */}
            <ambientLight intensity={0.5} />
            <hemisphereLight args={['#ffffff', '#aab2af', 0.7]} />
            <directionalLight
                position={[8, 14, 6]}
                intensity={2.6}
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
            <directionalLight position={[-9, 6, -7]} intensity={0.75} />

            {/* Metal needs something to reflect. The machine material is
                metalness 0.55, and a metal with no environment reflects
                nothing and renders black — which is exactly how it
                looked before this was added. Environment builds its map
                from these Lightformers in-scene, so it needs no HDR file
                and no CDN, which the plant network could not reach
                anyway. */}
            <Environment resolution={128} frames={1}>
                <Lightformer
                    intensity={1.4}
                    form="rect"
                    scale={[20, 20, 1]}
                    position={[0, 12, 0]}
                    rotation={[-Math.PI / 2, 0, 0]}
                    color="#ffffff"
                />
                <Lightformer
                    intensity={0.5}
                    form="rect"
                    scale={[20, 8, 1]}
                    position={[-12, 3, 4]}
                    rotation={[0, Math.PI / 2, 0]}
                    color="#dfe4e2"
                />
                <Lightformer
                    intensity={0.5}
                    form="rect"
                    scale={[20, 8, 1]}
                    position={[12, 3, -4]}
                    rotation={[0, -Math.PI / 2, 0]}
                    color="#dfe4e2"
                />
            </Environment>

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

            <FrameOnAnchor anchor={info?.anchor} />

            {/* Only once LoomModel has measured the reed. Without an
                anchor the shuttles have no track to sit on, and drawing
                them at a guessed radius would put them beside the
                machine while implying they are on it. */}
            {usingCad && info?.anchor && (
                <Shuttles
                    positionDeg={pos}
                    anchor={info.anchor}
                    running={running}
                    jam={jam}
                />
            )}

            <ContactShadows
                position={[0, 0.001, 0]}
                opacity={0.5}
                scale={16}
                blur={2.0}
                far={7}
                color="#2b3634"
            />

            {/* Fade distance is tuned to the machine (~6 units), not to
                the old dark-scene default of 34 — on a light ground a
                grid that runs to the horizon competes with the subject
                instead of seating it. */}
            <Grid
                args={[24, 24]}
                position={[0, 0, 0]}
                cellColor="#cdd3d0"
                sectionColor="#aeb6b3"
                fadeDistance={22}
                fadeStrength={1.5}
                infiniteGrid
            />

            {/* Orbit about the loom head, not the scene origin. The
                model spans the whole 4.3 m machine, so its centre sits
                well off the loom and the default target framed mostly
                empty floor. */}
            <OrbitControls
                enablePan
                enableZoom
                enableRotate
                minDistance={1.5}
                maxDistance={40}
                target={orbitTarget}
                maxPolarAngle={Math.PI / 2.05}
            />

        </Canvas>

        {/* Plain DOM, deliberately OUTSIDE the Canvas.
            This was a drei <Html> with `position: fixed` on its inner
            div, which does not do what it looks like: a transformed
            ancestor becomes the containing block for fixed positioning,
            so the badge tracked the 3D origin instead of the viewport
            corner and sat in the middle of the scene. An overlay that
            never needs to follow a 3D point should not be in the scene
            graph at all. */}
        {info && (
            <div style={{
                position: 'absolute', left: 14, bottom: 12,
                color: '#8a9694', font: '500 10px ui-monospace, monospace',
                letterSpacing: '0.3px',
                pointerEvents: 'none', whiteSpace: 'nowrap',
            }}>
                CAD {info.meshes} meshes · {info.tris.toLocaleString()} tris ·
                {' '}source span {info.spanMm} mm ·
                {' '}{info.anchor
                    ? `reed r=${info.anchor.radius.toFixed(3)}`
                    : 'reed NOT FOUND — shuttles hidden'}
            </div>
        )}
        </div>
    )
}
