/**
 * LoomFrame.jsx — Static structural frame of the circular loom
 *
 * Geometry:
 *   - Circular base plate  (flat cylinder)
 *   - 6 vertical pillars   (thin cylinders, evenly spaced)
 *   - Top support ring     (torus)
 *
 * All measurements are in Three.js units (1 unit ≈ 10 cm real-world).
 */

import { useMemo } from 'react'

const PILLAR_COUNT = 6
const FRAME_RADIUS = 2.8    // radius of pillar circle
const PILLAR_HEIGHT = 3.0
const PILLAR_RADIUS = 0.08
const BASE_RADIUS = 3.2
const BASE_HEIGHT = 0.12
const RING_RADIUS = 2.8    // torus major radius
const RING_TUBE = 0.07   // torus tube radius
const FRAME_COLOR = '#475569'
const BASE_COLOR = '#334155'

// ── Single pillar ─────────────────────────────────────────────
function Pillar({ angle }) {
    const x = FRAME_RADIUS * Math.cos(angle)
    const z = FRAME_RADIUS * Math.sin(angle)
    return (
        <mesh
            position={[x, PILLAR_HEIGHT / 2, z]}
            castShadow
            receiveShadow
        >
            <cylinderGeometry args={[PILLAR_RADIUS, PILLAR_RADIUS, PILLAR_HEIGHT, 8]} />
            <meshStandardMaterial color={FRAME_COLOR} metalness={0.6} roughness={0.4} />
        </mesh>
    )
}

// ── Loom frame ────────────────────────────────────────────────
export default function LoomFrame() {
    const pillarAngles = useMemo(
        () => Array.from({ length: PILLAR_COUNT }, (_, i) =>
            (i / PILLAR_COUNT) * Math.PI * 2
        ),
        []
    )

    return (
        <group name="loom-frame">
            {/* Base plate */}
            <mesh position={[0, BASE_HEIGHT / 2, 0]} receiveShadow>
                <cylinderGeometry args={[BASE_RADIUS, BASE_RADIUS, BASE_HEIGHT, 48]} />
                <meshStandardMaterial color={BASE_COLOR} metalness={0.3} roughness={0.7} />
            </mesh>

            {/* Vertical pillars */}
            {pillarAngles.map((angle, i) => (
                <Pillar key={i} angle={angle} />
            ))}

            {/* Top support ring (torus) */}
            <mesh
                position={[0, PILLAR_HEIGHT, 0]}
                rotation={[Math.PI / 2, 0, 0]}
                castShadow
            >
                <torusGeometry args={[RING_RADIUS, RING_TUBE, 12, 64]} />
                <meshStandardMaterial color={FRAME_COLOR} metalness={0.7} roughness={0.3} />
            </mesh>
        </group>
    )
}
