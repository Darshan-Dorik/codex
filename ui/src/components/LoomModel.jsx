/**
 * LoomModel.jsx — the real machine
 *
 * Loads the voxel-remeshed CAD export (public/loom.glb) produced from
 * loom-meshed.blend by tools/build_loom_model.py.
 *
 * THIS MESH IS A VISUAL SHELL. IT CARRIES NO SIMULATION STATE.
 *
 * Nothing here is kinematic and nothing here is authoritative. The
 * geometry has been voxel-remeshed — rebuilt from a distance field at
 * 3-12 mm depending on the part — so its surfaces are an approximation
 * of the CAD, not the CAD, and there is no correspondence between a
 * vertex here and anything the twin models. The machine's moving parts
 * are not even separate objects in this file.
 *
 * The six shuttles are NOT in this mesh. The CAD contains no shuttle
 * geometry at all. They are synthesised in Shuttles.jsx and driven from
 * `shuttle_position`, which comes from the twin's CyclicShuttleModel via
 * the /state endpoint.
 *
 * So: do not derive positions, angles, collisions or sensor triggers
 * from this mesh. The twin is the source of truth for all of that, and
 * anything read off this geometry would be reading an artefact of the
 * remesh settings in tools/build_loom_model.py.
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

// The reed assembly keeps its CAD name through the glTF export, which is
// what makes it findable here. Renaming it in the source CAD, or
// filtering it out of the build, breaks shuttle placement — so if this
// ever stops matching, Scene.jsx hides the shuttles rather than drawing
// them somewhere wrong.
//
// MATCH ON A NORMALISED NAME, NOT THE RAW ONE. GLTFLoader passes every
// node name through PropertyBinding.sanitizeNodeName, which turns
// whitespace into underscores and strips []./: — so the CAD's
// "705 _ 001 FLAT STEEL REED WITH CAM ASSY (Meshed)" arrives as
// "705___001_FLAT_STEEL_REED_WITH_CAM_ASSY_(Meshed)". A regex written
// against the name as it appears in Blender silently never matches, and
// the failure is quiet: no reed, no anchor, shuttles hidden.
const REED_NODE = 'FLAT STEEL REED WITH CAM'
const normaliseName = (s) =>
    (s || '').replace(/[^A-Za-z0-9]+/g, ' ').trim().toUpperCase()

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

    // Jam tints the whole machine; stopped desaturates it. Cheap, and
    // readable from across a room, which is what a plant dashboard is
    // for.
    //
    // The tint is applied INSIDE the memo factory rather than by writing
    // to the material afterwards: mutating an object React is holding is
    // rejected by react-hooks/immutability, and it would not re-render.
    // metalness 0.55, not 0.82. A near-pure metal takes almost all its
    // colour from reflections, so against a light background it needs a
    // strong environment or it renders as a dark silhouette. Backing off
    // the metalness keeps the diffuse colour doing real work, and the
    // Environment in Scene.jsx supplies the rest.
    const material = useMemo(() => {
        const m = new THREE.MeshStandardMaterial({
            metalness: 0.55,
            roughness: 0.42,
            envMapIntensity: 1.0,
        })
        if (jam) {
            m.color.set('#b8564a')
        } else if (!running) {
            m.color.set('#a9b1ae')
        } else {
            m.color.set('#8b9491')
        }
        return m
    }, [jam, running])

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
        let reed = null
        model.traverse((o) => {
            if (!o.isMesh) return
            meshes += 1
            const g = o.geometry
            if (g?.index) tris += g.index.count / 3
            else if (g?.attributes?.position) tris += g.attributes.position.count / 3
            o.castShadow = true
            o.receiveShadow = true
            if (normaliseName(o.name).includes(REED_NODE)) reed = o
        })

        // WHERE THE SHUTTLES GO.
        //
        // The shuttle ring cannot use a hardcoded radius. This model is
        // the whole machine — 4.3 m from creel end to winder — and the
        // loom head is a ~1.2 m ring sitting off-centre within that, so
        // any fixed number puts the shuttles in mid-air beside the
        // machine. Measure the reed instead: it IS the shuttle track,
        // and it survives into the GLB under its CAD name.
        //
        // Falls back to null rather than to a guess. Scene.jsx hides
        // the shuttles when there is no anchor, which is honest — a
        // wrong position would misreport where the twin thinks the
        // shuttles are.
        let anchor = null
        if (reed) {
            model.updateMatrixWorld(true)
            const rb = new THREE.Box3().setFromObject(reed)
            const rc = new THREE.Vector3()
            const rs = new THREE.Vector3()
            rb.getCenter(rc)
            rb.getSize(rs)
            anchor = {
                x: rc.x,
                y: rc.y,
                z: rc.z,
                // Ring lies in XZ with Y as its axis (the export is
                // Y-up; see tools/build_loom_model.py on export_yup).
                radius: Math.max(rs.x, rs.z) / 2,
            }
        }

        onFitted?.({
            meshes,
            tris: Math.round(tris),
            spanMm: Math.round(span),
            scale: s,
            anchor,
        })
        // Deliberately NOT dependent on `material`. Measurement must run
        // once per model: if a jam re-ran it, onFitted would hand Scene a
        // fresh anchor object, OrbitControls would see a new target and
        // yank the camera every time the machine faulted.
    }, [model, fit, onFitted])

    // Shading is separate from measurement for that reason.
    useLayoutEffect(() => {
        model.traverse((o) => {
            if (o.isMesh) o.material = material
        })
    }, [model, material])

    return <primitive ref={group} object={model} />
}

useGLTF.preload('/loom.glb', '/draco/')
