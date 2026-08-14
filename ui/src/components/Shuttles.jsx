/**
 * Shuttles.jsx — the six shuttles, synthesised
 *
 * THE CAD DOES NOT CONTAIN SHUTTLES.
 *
 * loom-meshed.blend has 117 named assemblies — creel, compensator
 * holders, reeds with cams, loom bed, take-up, winders — and not one
 * of them is a shuttle or a bobbin. The shuttles that circulate the
 * track are simply not in the model.
 *
 * So the machine body is real CAD and the shuttles are synthetic
 * markers. That split is deliberate and worth keeping visible: the
 * shuttle position is the one thing the twin actually simulates
 * (`CyclicShuttleModel`), and it is driven here from the live
 * `shuttle_position` register rather than being decorative animation.
 *
 * If shuttle geometry is ever added to the CAD, this component is what
 * gets replaced — not the loader.
 */

import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'

const SHUTTLE_COUNT = 6

export default function Shuttles({
    positionDeg = 0,
    // Measured from the reed in LoomModel.jsx, not chosen. See the note
    // there: the model is the whole 4.3 m machine and the loom head sits
    // off-centre inside it, so a literal radius puts the shuttles beside
    // the machine rather than on its track.
    anchor,
    running = true,
    jam = false,
}) {
    const group = useRef()
    const target = useRef(0)

    const radius = anchor.radius
    // Shuttle size follows the track, so the markers stay proportionate
    // whatever `fit` the model was scaled to.
    const bodyR = radius * 0.036
    const bodyL = radius * 0.11

    const bodies = useMemo(
        () => Array.from({ length: SHUTTLE_COUNT }, (_, i) => i),
        [],
    )

    // Declared, not mutated. Building a THREE material in a useMemo and
    // then writing to it during render mutates a value React is holding
    // — react-hooks/immutability rejects it, and it would also skip the
    // re-render that is supposed to show the state change.
    const colour = jam ? '#ef4444' : running ? '#f59e0b' : '#64748b'
    const glow = jam ? 1.1 : running ? 0.7 : 0.15

    // The twin reports absolute position, so drive rotation from the
    // value rather than integrating locally — a dropped frame then
    // shows as a small jump, not permanent drift against the machine.
    useFrame((_, dt) => {
        if (!group.current) return
        target.current = THREE.MathUtils.degToRad(positionDeg)
        const cur = group.current.rotation.y
        let delta = target.current - cur
        // shortest way round the circle
        while (delta > Math.PI) delta -= Math.PI * 2
        while (delta < -Math.PI) delta += Math.PI * 2
        group.current.rotation.y = cur + delta * Math.min(1, dt * 12)
    })

    return (
        <group ref={group} position={[anchor.x, anchor.y, anchor.z]}>
            {bodies.map((i) => {
                const a = (i / SHUTTLE_COUNT) * Math.PI * 2
                return (
                    <group
                        key={i}
                        position={[Math.cos(a) * radius, 0, Math.sin(a) * radius]}
                        rotation={[0, -a, 0]}
                    >
                        <mesh castShadow>
                            <capsuleGeometry args={[bodyR, bodyL, 4, 12]} />
                            <meshStandardMaterial
                                color={colour}
                                metalness={0.35}
                                roughness={0.3}
                                emissive="#7c3d00"
                                emissiveIntensity={glow}
                            />
                        </mesh>
                        <pointLight
                            distance={radius * 0.6}
                            intensity={jam ? 2.2 : running ? 1.1 : 0.2}
                            color={jam ? '#ef4444' : '#f59e0b'}
                        />
                    </group>
                )
            })}
        </group>
    )
}
