"""
tools/build_loom_model.py — CAD → web model build step

Turns loom-meshed.blend (1.3 GB, 117 assemblies, 53 M polygons) into
ui/public/loom.glb, a few megabytes the browser can actually render.

Run it with Blender, headless:

    /Applications/Blender.app/Contents/MacOS/Blender \\
        loom-meshed.blend --background --python tools/build_loom_model.py

    # keep the two creel frames (adds ~15 M source polys, ~150 k output)
    ... --python tools/build_loom_model.py -- --include-creel

    # geometry check: render the reed and circular guide, no export
    ... --python tools/build_loom_model.py -- --render
    ... --python tools/build_loom_model.py -- --render --raw   # before shot

This is a BUILD STEP, not part of the stdlib-only engine. It needs
Blender; nothing else in the repo does, and the engine never imports it.
The output GLB is a build artefact and is gitignored.

WHY VOXEL REMESH AND NOT DECIMATE
Decimate collapses edges, so it cannot collapse across a disconnected
island. CAD tessellation is unwelded triangle soup made of thousands of
discrete solids, so the island count IS the floor: a 14.2 M assembly
asked for 30 k came out at 381 k, and welding first (0.01 mm → 0.5 mm →
2 mm) moved the weld figure 30x without moving that floor. The full run
bottomed out at 18.3 M polys / 123 MB, which is not a web deliverable.

Voxel remesh rebuilds the surface from a signed distance field. It does
not care about islands at all, and it discards interior geometry — the
threads inside bolt holes, the faces of parts buried inside housings —
which is most of what makes this CAD heavy. Measured surface area drops
of 60–99% are that hidden interior going away, not detail being lost.

THE VOXEL SIZE IS BOUNDED FROM ABOVE, PER PART
A voxel wider than a part's thinnest feature erodes that feature. This
was measured (volume ratio against the source, `--render` to confirm by
eye) rather than guessed, and the binding constraint was NOT the reed:

    CIRCULAR GUIDE   3 mm vol x1.04    6 mm vol x0.52   <- half of it gone
    REED WITH CAM    3 mm vol x1.03    8 mm vol x1.86
    FLAT STEEL REED  6 mm vol x1.00   12 mm vol x0.79

The reed survives coarse voxels because it is ALREADY a single welded
solid in the CAD — there are no separate wires to fuse. The circular
guide's thin spreading vanes are the real limit. Hence PLAN below is a
per-part table, not one global number.

Ratios above 1.0 are voxel remesh closing hollows and bridging narrow
gaps; that is expected and is why nothing here runs coarser than 12 mm.

SMALL PARTS ARE NOT REMESHED AT ALL
An eyelet is 7.9 mm across. At a 6 mm voxel it is one voxel. Everything
at or below SMALL_PART_POLYS is passed through untouched — together the
~100 small parts are only ~120 k polys, which is cheaper than the damage
remeshing them would do.

CO-LOCATED DUPLICATES
Four assemblies ship 2–3 copies at an identical world centre and
rotation, hidden exactly inside one another — 17.25 M polys, a third of
the model, invisible. They are dropped after a vertex-fingerprint check
confirms the copies really are identical (a mirrored copy would share a
centre too). See drop_colocated_duplicates.

NO bpy.ops FOR THE MESH WORK. In background mode there is no screen
context: bpy.ops.object.select_all fails poll() outright, and
modifier_apply leaks an Edit-mode context that makes the NEXT object fail
with "not allowed from Edit mode". Modifiers are evaluated through the
depsgraph and the result swapped in as mesh data directly, which needs no
context at all.

Centring and scaling are deliberately NOT done here — they happen in
LoomModel.jsx on load, where the bounding box is measured directly rather
than baked through Blender's parent-inverse matrices.
"""

import os
import sys
import time

import bpy
from mathutils import Vector

# ── Reduction plan ────────────────────────────────────────────────
# (name fragment, voxel mm). FIRST MATCH WINS, so the longer, more
# specific fragment must come first: "FLAT STEEL REED WITH CAM" has to
# be tested before "FLAT STEEL REED" or the cam assembly takes the bare
# reed's setting.
PLAN = [
    # Thin spreading vanes — measured 48% volume loss at 6 mm. This is
    # the tightest constraint in the model; do not coarsen it to save
    # triangles, take them from TAKE-UP instead.
    ("CIRCULAR GUIDE",           3.0),
    # 4 mm keeps the reed's segmented plates and rivets legible for
    # 159 k triangles. 6 mm turns that band into crust for 67 k, and
    # 3 mm buys very little visible improvement for 303 k — it is the
    # single most recognisable part of the machine, so it gets the
    # largest share of the budget. Confirmed by eye with --render.
    ("FLAT STEEL REED WITH CAM", 4.0),
    # None = pass through untouched. Remeshing the bare reed only takes
    # 55.6 k to 45.4 k — an 18% saving in exchange for softening exactly
    # the crisp CAD surfaces worth keeping. Not a trade worth making.
    ("FLAT STEEL REED",          None),
    ("COMPENSATOR HOLDER",       6.0),
    ("LOOM BED",                 8.0),
    # Big peripheral frames: 2.1 m across and mostly tube. Coarse is
    # free here, and this is where the budget comes from.
    ("TAKE-UP",                 12.0),
    ("PATH106",                 12.0),
    ("SURFACE WINDER",          12.0),
    ("CREEL",                   12.0),
]
DEFAULT_VOXEL = 6.0
# Below this, pass through untouched — see SMALL PARTS above.
SMALL_PART_POLYS = 20_000

# Excluded unless --include-creel. Not deleted from the source: the two
# creel frames are 15 M polys of yarn-supply rack that read as scaffolding
# beside the loom, but someone will want the whole machine eventually.
CREEL_FRAGMENT = "CREEL"

_REPO = os.path.dirname(os.path.abspath(bpy.data.filepath)) \
    if bpy.data.filepath else os.getcwd()
OUT = os.path.join(_REPO, "ui", "public", "loom.glb")
# NOT under ui/public — anything there is served to the browser and
# bundled by Vite, and this render is a developer check, not an asset.
RENDER_OUT = os.path.join(_REPO, "voxel_check.png")

# Parts the --render check inspects: the two the voxel size is bounded by.
RENDER_SUBSET = ["FLAT STEEL REED", "CIRCULAR GUIDE"]


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


# Set by --voxel=N. Overrides the whole PLAN, which is only useful with
# --render: it is how the per-part sizes in PLAN were chosen in the first
# place, so keeping it means the next person can redo that measurement
# instead of trusting the table.
VOXEL_OVERRIDE = None


def voxel_for(name):
    if VOXEL_OVERRIDE is not None:
        return VOXEL_OVERRIDE
    upper = name.upper()
    for fragment, size in PLAN:
        if fragment in upper:
            return size
    return DEFAULT_VOXEL


def mesh_objects():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def fingerprint(obj):
    """
    Cheap identity hash of a mesh's local vertex coordinates.

    Co-location plus an equal polygon count is strong evidence of a
    duplicate but not proof — a MIRRORED copy shares a centre, a
    rotation and a poly count while being different geometry. Summing
    the coordinates separates them: a mirror flips the sign of one axis,
    so its sum differs unless the part is perfectly symmetric about that
    axis, and a part that symmetric is visually identical anyway.
    """
    n = len(obj.data.vertices)
    buf = [0.0] * (n * 3)
    obj.data.vertices.foreach_get("co", buf)
    return (n,
            round(sum(buf[0::3]), 3),
            round(sum(buf[1::3]), 3),
            round(sum(buf[2::3]), 3))


def drop_colocated_duplicates():
    """Remove copies stacked exactly inside one another. Returns polys saved."""
    by_count = {}
    for o in mesh_objects():
        by_count.setdefault(len(o.data.polygons), []).append(o)

    saved = 0
    for polys, members in sorted(by_count.items(), key=lambda kv: -kv[0]):
        if len(members) < 2:
            continue

        centres = {}
        for o in members:
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            centre = sum(pts, Vector()) / 8
            key = (round(centre.x, 1), round(centre.y, 1), round(centre.z, 1))
            centres.setdefault(key, []).append(o)

        for group in centres.values():
            if len(group) < 2:
                continue
            keep = group[0]
            ref = fingerprint(keep)
            for other in group[1:]:
                if fingerprint(other) != ref:
                    print(f"[build] KEPT {other.name}: co-located with "
                          f"{keep.name} but geometry differs", flush=True)
                    continue
                saved += polys
                print(f"[build] dupe  {polys:>12,}  {other.name}", flush=True)
                bpy.data.objects.remove(other, do_unlink=True)
    return saved


def drop_creel():
    saved = 0
    for o in mesh_objects():
        if CREEL_FRAGMENT in o.name.upper():
            saved += len(o.data.polygons)
            print(f"[build] creel {len(o.data.polygons):>12,}  {o.name}",
                  flush=True)
            bpy.data.objects.remove(o, do_unlink=True)
    return saved


def bake_modifiers(obj):
    """
    Bake obj's whole modifier stack into its mesh, once.

    ONE swap, at the end, and no mesh is ever removed. Both matter:

      - Swapping mid-stack re-evaluated stale geometry on the second
        pass and handed back the ORIGINAL mesh. Building the stack and
        evaluating once removes the failure mode rather than working
        around it.
      - bpy.data.meshes.remove() on a mesh the depsgraph still holds
        CRASHED Blender outright. The process exports and exits; leaked
        datablocks cost nothing.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    new_mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    obj.modifiers.clear()
    obj.data = new_mesh
    return len(new_mesh.polygons)


def remesh(obj, voxel_mm):
    obj.modifiers.clear()
    mod = obj.modifiers.new(name="voxel", type="REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel_mm
    # Adaptivity trades triangles for a slightly looser surface. Left at
    # 0: Draco compresses the uniform output well, and adaptivity makes
    # the triangle count much harder to predict from the voxel size.
    mod.adaptivity = 0.0
    return bake_modifiers(obj)


def reduce_all():
    total_before = 0
    total_after = 0
    for i, obj in enumerate(sorted(mesh_objects(),
                                   key=lambda o: -len(o.data.polygons))):
        start = len(obj.data.polygons)
        total_before += start
        if start <= SMALL_PART_POLYS:
            total_after += start
            continue

        voxel = voxel_for(obj.name)
        if voxel is None:
            total_after += start
            print(f"[build] {i:>3} {start:>12,}    (as-is)  "
                  f"       {obj.name[:44]:44}", flush=True)
            continue

        t0 = time.time()
        try:
            final = remesh(obj, voxel)
        except Exception as exc:                        # noqa: BLE001
            print(f"[build] FAILED {obj.name}: {exc}", flush=True)
            obj.modifiers.clear()
            total_after += start
            continue

        total_after += final
        print(f"[build] {i:>3} {start:>12,} -> {final:>8,}  "
              f"{voxel:4.1f}mm  {obj.name[:44]:44} "
              f"{time.time() - t0:5.1f}s", flush=True)
    return total_before, total_after


# ── Geometry check render ─────────────────────────────────────────

def setup_render_scene():
    """
    Frame whatever objects remain, with a camera and light built from
    bpy.data rather than bpy.ops — object_add operators are among the
    ones that behave badly without a screen context.
    """
    objs = mesh_objects()
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) / 2
    span = max((hi - lo).x, (hi - lo).y, (hi - lo).z)

    cam_data = bpy.data.cameras.new("check_cam")
    cam_data.clip_start = span * 0.01
    cam_data.clip_end = span * 20
    cam = bpy.data.objects.new("check_cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    offset = Vector((0.85, -1.25, 0.65)).normalized() * span * 1.7
    cam.location = centre + offset
    cam.rotation_euler = (-offset).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    # Workbench, not EEVEE: this render exists to judge whether thin
    # structure survived, and workbench's cavity shading shows edges far
    # more legibly than a lit material would.
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.film_transparent = False
    scene.render.filepath = RENDER_OUT
    scene.render.image_settings.file_format = "PNG"


def do_render(raw, subset=True):
    if subset:
        keep = [o for o in mesh_objects()
                if any(f in o.name.upper() for f in RENDER_SUBSET)]
        keep_names = {o.name for o in keep}
        for o in mesh_objects():
            if o.name not in keep_names:
                bpy.data.objects.remove(o, do_unlink=True)
    else:
        keep = mesh_objects()

    print(f"[build] render subset: {len(keep)} objects", flush=True)
    for o in sorted(keep, key=lambda o: -len(o.data.polygons)):
        before = len(o.data.polygons)
        voxel = voxel_for(o.name)
        if raw or voxel is None or before <= SMALL_PART_POLYS:
            print(f"[build]   {before:>10,} (as-is)  {o.name}", flush=True)
            continue
        after = remesh(o, voxel)
        print(f"[build]   {before:>10,} -> {after:>8,} @ {voxel:.1f}mm  "
              f"{o.name}", flush=True)

    setup_render_scene()
    bpy.ops.render.render(write_still=True)
    print(f"[build] WROTE {RENDER_OUT}", flush=True)


def main():
    global VOXEL_OVERRIDE
    args = argv_after_ddash()
    t0 = time.time()

    for a in args:
        if a.startswith("--voxel="):
            VOXEL_OVERRIDE = float(a.split("=", 1)[1])
            print(f"[build] voxel override: {VOXEL_OVERRIDE} mm "
                  f"(PLAN ignored)", flush=True)

    before = sum(len(o.data.polygons) for o in mesh_objects())
    print(f"[build] {len(mesh_objects())} assemblies, {before:,} polys",
          flush=True)

    dupes = drop_colocated_duplicates()
    print(f"[build] dropped {dupes:,} polys of co-located duplicates",
          flush=True)

    if "--include-creel" not in args:
        creel = drop_creel()
        print(f"[build] dropped {creel:,} polys of creel "
              f"(pass --include-creel to keep)", flush=True)
    else:
        print("[build] keeping creel assemblies", flush=True)

    if "--render" in args or "--render-all" in args:
        do_render(raw="--raw" in args, subset="--render-all" not in args)
        print(f"[build] done in {time.time() - t0:.0f}s", flush=True)
        return

    src, out = reduce_all()
    print(f"[build] {src:,} -> {out:,} polys "
          f"({out / src * 100:.2f}%) in {time.time() - t0:.0f}s", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=OUT,
        export_format="GLB",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
        export_apply=True,
        # FALSE, and this is not the obvious setting.
        #
        # export_yup=True converts Blender's Z-up to glTF's Y-up. But
        # this CAD is ALREADY Y-up — every circular part has its thin
        # axis on Y (reed 1184x351x1189, loom bed 855x282x855,
        # compensator 1192x180x1192), i.e. the rings' axis is Y. The
        # STEP file was imported into a Z-up Blender scene without a
        # conversion, so the data sits in Blender unrotated.
        #
        # Converting again stood the whole loom on edge like a Ferris
        # wheel. Passing coordinates through unchanged is what actually
        # produces a Y-up glTF here. Verified by round-tripping the
        # export back through the importer and checking that the rings
        # come back flat (thin axis Z in Blender's Z-up space).
        export_yup=False,
        use_selection=False,
    )
    print(f"[build] WROTE {OUT}  {os.path.getsize(OUT) / 1e6:.1f} MB  "
          f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
