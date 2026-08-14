/**
 * ShuttleRing.jsx — The circular track the shuttle travels on
 *
 * Step 3: Static geometry (track, inner ring, spokes, hub)
 * Step 4: Animated — ring rotates based on shuttle_position (0–360°)
 *         Uses useFrame for smooth interpolation (no jitter).
 */

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'

const TRACK_RADIUS = 2.2
const TRACK_TUBE = 0.06
const INNER_RADIUS = 1.8
const INNER_TUBE = 0.03
const HUB_RADIUS = 0.18
const HUB_HEIGHT = 0.25
const SPOKE_COUNT = 12
const TRACK_Y = 2.0
const TRACK_COLOR = '#94a3b8'
const INNER_COLOR = '#64748b'
const HUB_COLOR = '#cbd5e1'
const LERP_FACTOR = 0.12   // smoothing — lower = smoother but laggier

// ── Single spoke ──────────────────────────────────────────────
function Spoke({ angle }) {
    const length = INNER_RADIUS - HUB_RADIUS
    const midX = ((HUB_RADIUS + INNER_RADIUS) / 2) * Math.cos(angle)
    const midZ = ((HUB_RADIUS + INNER_RADIUS) / 2) * Math.sin(angle)
    return (
        <mesh position={[midX, 0, midZ]} rotation={[0, -angle, Math.PI / 2]}>
            <cylinderGeometry args={[0.015, 0.015, length, 4]} />
            <meshStandardMaterial color={INNER_COLOR} metalness={0.5} roughness={0.5} />
        </mesh>
    )
}

// ── Shuttle ring ──────────────────────────────────────────────
export default function ShuttleRing({ shuttlePosition = 0 }) {
    const groupRef = useRef()
    const currentRot = useRef(0)   // smoothed Y-rotation in radians

    const spokeAngles = useMemo(
        () => Array.from({ length: SPOKE_COUNT }, (_, i) =>
            (i / SPOKE_COUNT) * Math.PI * 2
        ),
        []
    )

    // Step 4: smooth rotation driven by shuttle_position
    useFrame(() => {
        if (!groupRef.current) return

        // Convert 0–360° to radians
        const targetRad = (shuttlePosition / 360) * Math.PI * 2

        // Shortest-path lerp to avoid spinning backwards on wrap
        let diff = targetRad - currentRot.current
        if (diff > Math.PI) diff -= Math.PI * 2
        if (diff < -Math.PI) diff += Math.PI * 2

        currentRot.current += diff * LERP_FACTOR
        groupRef.current.rotation.y = currentRot.current
    })

    return (
        <group ref={groupRef} name="shuttle-ring" position={[0, TRACK_Y, 0]}>
            {/* Main track */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <torusGeometry args={[TRACK_RADIUS, TRACK_TUBE, 12, 96]} />
                <meshStandardMaterial
                    color={TRACK_COLOR}
                    metalness={0.8}
                    roughness={0.2}
                    emissive={TRACK_COLOR}
                    emissiveIntensity={0.05}
                />
            </mesh>

            {/* Inner guide ring */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <torusGeometry args={[INNER_RADIUS, INNER_TUBE, 8, 64]} />
                <meshStandardMaterial color={INNER_COLOR} metalness={0.6} roughness={0.4} />
            </mesh>

            {/* Spokes */}
            {spokeAngles.map((angle, i) => (
                <Spoke key={i} angle={angle} />
            ))}

            {/* Centre hub */}
            <mesh>
                <cylinderGeometry args={[HUB_RADIUS, HUB_RADIUS, HUB_HEIGHT, 16]} />
                <meshStandardMaterial color={HUB_COLOR} metalness={0.7} roughness={0.3} />
            </mesh>

            {/* Step 4: rotation marker — amber bar at 0° so rotation is visible */}
            <mesh position={[TRACK_RADIUS * 0.6, 0.04, 0]}>
                <boxGeometry args={[TRACK_RADIUS * 0.8, 0.04, 0.04]} />
                <meshStandardMaterial
                    color="#f59e0b"
                    emissive="#f59e0b"
                    emissiveIntensity={0.6}
                />
            </mesh>
        </group>
    )
}
