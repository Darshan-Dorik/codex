/**
 * LoomModel.jsx — the real machine
 *
 * Loads the decimated CAD export (public/loom.glb) produced from
 * loom-meshed.blend by tools/blender_decimate.py.
 *
 * WHY THE FITTING HAPPENS HERE
 * The source CAD is in millimetres and spans ~4.3 m, positioned
 * wherever the assembly happened to sit. Rather than fight Blender's
 * parent-inverse matrices to bake a transform, the model is measured
 * on load — real bounding box, real numbers — and fitted to the scene.
 * That also means the export stays a faithful dump of the CAD.
 *
 * The CAD carries a single flat material, which is what made the
 * original look like a toy. Every mesh is re-shaded here with one
 * industrial metal, so the geometry reads as machined parts.
 */

import { useGLTF } from '@react-three/drei'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'

export default function LoomModel({
    url = '/loom.glb',
    fit = 6,
    jam = false,
    running = true,
    onFitted,
}) {
    const { scene } = useGLTF(url, '/draco/')
    const group = useRef()

    // clone so hot-reload and multiple mounts don't mutate the cache
    const model = useMemo(() => scene.clone(true), [scene])

    const material = useMemo(
        () =>
            new THREE.MeshStandardMaterial({
                color: '#8d97a6',
                metalness: 0.82,
                roughness: 0.34,
            }),
        [],
    )

    useLayoutEffect(() => {
        const box = new THREE.Box3().setFromObject(model)
        const size = new THREE.Vector3()
        const centre = new THREE.Vector3()
        box.getSize(size)
        box.getCenter(centre)

        const span = Math.max(size.x, size.y, size.z) || 1
        const s = fit / span

        model.scale.setScalar(s)
        // centre on X/Z, sit on the floor in Y
        model.position.set(-centre.x * s, -box.min.y * s, -centre.z * s)

        let meshes = 0
        let tris = 0
        model.traverse((o) => {
            if (!o.isMesh) return
            meshes += 1
            const g = o.geometry
            if (g?.index) tris += g.index.count / 3
            else if (g?.attributes?.position) tris += g.attributes.position.count / 3
            o.castShadow = true
            o.receiveShadow = true
            o.material = material
        })

        onFitted?.({
            meshes,
            tris: Math.round(tris),
            spanMm: Math.round(span),
            scale: s,
        })
    }, [model, fit, material, onFitted])

    // Jam tints the whole machine; stopped desaturates it. Cheap, and
    // readable from across a room, which is what a plant dashboard is for.
    useLayoutEffect(() => {
        if (jam) {
            material.color.set('#b06a6a')
            material.emissive.set('#3b0d0d')
            material.emissiveIntensity = 0.55
        } else if (!running) {
            material.color.set('#6f7887')
            material.emissive.set('#000000')
            material.emissiveIntensity = 0
        } else {
            material.color.set('#8d97a6')
            material.emissive.set('#0b1622')
            material.emissiveIntensity = 0.18
        }
        material.needsUpdate = true
    }, [jam, running, material])

    return <primitive ref={group} object={model} />
}

useGLTF.preload('/loom.glb', '/draco/')
