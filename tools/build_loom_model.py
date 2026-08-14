"""
tools/build_loom_model.py — CAD → web model build step

Turns loom-meshed.blend (1.3 GB, 117 assemblies, 53 M polygons) into
ui/public/loom.glb, a few megabytes the browser can actually render.

Run it with Blender, headless:

    /Applications/Blender.app/Contents/MacOS/Blender \\
        loom-meshed.blend --background --python tools/build_loom_model.py

This is a BUILD STEP, not part of the stdlib-only engine. It needs
Blender; nothing else in the repo does, and the engine never imports
it. The output GLB is a build artefact.

TWO THINGS THAT MAKE THIS NON-OBVIOUS
-------------------------------------
1. WELD BEFORE DECIMATE, AND WELD WIDE ENOUGH. CAD tessellation is
   unwelded triangle soup — adjacent triangles do not share vertices —
   and Decimate collapses edges, so it cannot collapse across an island
   boundary. Measured here: a 14.2 M-polygon assembly asked for 30 k
   came out at 381 k, 12x over target.

   Welding at 0.01 mm (exactly-coincident vertices only) did NOT fix
   it: the same assembly still floored at 380,614. That threshold
   repairs the soup within each solid but leaves every bolt, bracket
   and pin its own island, so the floor is the part count, not the
   tessellation. 0.5 mm bridges neighbouring parts into connected
   surfaces and collapse finally reaches target. On a 4.3 m machine
   drawn a few hundred pixels wide, 0.5 mm of merging is invisible.

2. NO bpy.ops FOR THE MESH WORK. In background mode there is no screen
   context: bpy.ops.object.select_all fails poll() outright, and
   modifier_apply leaks an Edit-mode context that makes the NEXT
   object fail with "not allowed from Edit mode". Both modifiers are
   therefore evaluated through the depsgraph and the result swapped in
   as mesh data directly, which needs no context at all.

Centring and scaling are deliberately NOT done here — they happen in
LoomModel.jsx on load, where the bounding box is measured directly
rather than baked through Blender's parent-inverse matrices.
"""

import os
import sys
import time

import bpy

TRIANGLE_CAP = 30_000      # per assembly
# 0.01 mm only merges exactly-coincident CAD vertices, which leaves each
# bolt and bracket its own island — and Decimate cannot collapse across
# an island, so an assembly of ~95k separate solids has a hard floor of
# ~380k triangles no matter what ratio is asked for. 0.5 mm bridges
# neighbouring parts into connected surfaces so collapse can actually
# reach target. On a 4.3 m machine drawn a few hundred pixels wide,
# 0.5 mm of merging is invisible.
WELD_MM      = 2.0
# One dirname, not two: bpy.data.filepath is <repo>/loom-meshed.blend,
# so a single dirname already gives the repo root. Two silently wrote
# 103 MB to ~/Desktop/ui/public/.
_REPO = os.path.dirname(os.path.abspath(bpy.data.filepath)) \
    if bpy.data.filepath else os.getcwd()
OUT = os.path.join(_REPO, "ui", "public", "loom.glb")


def evaluated_face_count(obj):
    """Face count of obj's evaluated mesh, WITHOUT swapping anything."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return len(obj.evaluated_get(depsgraph).data.polygons)


def bake_modifiers(obj):
    """
    Bake obj's whole modifier stack into its mesh, once.

    ONE swap, at the end, and no mesh is ever removed. Both matter:

      - Swapping mid-stack (weld, swap, decimate, swap) re-evaluated
        stale geometry on the second pass and handed back the ORIGINAL
        mesh — a 14.2M assembly "decimated" from 3,360,763 straight
        back up to 14,221,114. Building the full stack and evaluating
        once removes the failure mode rather than working around it.
      - bpy.data.meshes.remove() on a mesh the depsgraph still holds
        CRASHED Blender outright, and these assemblies share mesh data
        between duplicates so "unused" was not a safe reading of
        users == 0. The process exports and exits; leaked datablocks
        cost nothing.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    new_mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    obj.modifiers.clear()
    obj.data = new_mesh
    return len(new_mesh.polygons)


def main():
    t0 = time.time()
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    before = sum(len(o.data.polygons) for o in meshes)
    print(f"[build] {len(meshes)} assemblies, {before:,} polys, "
          f"cap {TRIANGLE_CAP:,}/assembly", flush=True)

    for i, obj in enumerate(sorted(meshes,
                                   key=lambda o: -len(o.data.polygons))):
        start = len(obj.data.polygons)
        if start <= TRIANGLE_CAP:
            continue

        try:
            # SINGLE-USER THE MESH FIRST. Duplicated assemblies share
            # one mesh datablock (COMPENSATOR HOLDER ASSY appears twice,
            # as does CREEL and the reeds). Baking a modifier onto a
            # shared mesh meant the second object evaluated geometry the
            # first had already replaced — it "decimated" 447,048 to
            # 447,048, i.e. did nothing — and repeatedly crashed Blender
            # outright. Copying makes each object's mesh its own.
            if obj.data.users > 1:
                obj.data = obj.data.copy()

            # Weld the CAD soup into connected surfaces, then measure
            # the welded result WITHOUT baking it — the decimate ratio
            # has to be computed against the post-weld face count.
            weld = obj.modifiers.new(name="weld", type="WELD")
            weld.merge_threshold = WELD_MM
            welded = evaluated_face_count(obj)

            # Stack decimate on top and bake the whole thing once.
            if welded > TRIANGLE_CAP:
                dec = obj.modifiers.new(name="dec", type="DECIMATE")
                dec.decimate_type = "COLLAPSE"
                dec.ratio = TRIANGLE_CAP / welded
            final = bake_modifiers(obj)
        except Exception as exc:                       # noqa: BLE001
            print(f"[build] FAILED {obj.name}: {exc}", flush=True)
            obj.modifiers.clear()
            continue

        floored = final > TRIANGLE_CAP * 1.5
        note = "  <- island-floored" if floored else ""
        print(f"[build] {i:>3} {start:>12,} -> weld {welded:>9,} "
              f"-> {final:>8,}  {obj.name[:38]:38} "
              f"+{time.time()-t0:.0f}s{note}", flush=True)

    after = sum(len(o.data.polygons) for o in bpy.data.objects
                if o.type == "MESH")
    print(f"[build] {before:,} -> {after:,} polys "
          f"({after / before * 100:.2f}%) in {time.time() - t0:.0f}s",
          flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
        export_apply=True,
        export_yup=True,
        use_selection=False,
    )
    size_mb = os.path.getsize(OUT) / 1e6
    print(f"[build] WROTE {OUT}  {size_mb:.1f} MB  "
          f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
