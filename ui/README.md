# Loom Twin Dashboard

React + react-three-fiber front end for the circular loom twin.

```bash
python3 ui/api_server.py          # backend on :5174
cd ui && npm install && npm run dev
```

`api_server.py` is a thin HTTP frontend over
`src/shim/twin_runtime.TwinRuntime`. It runs no simulation of its own —
the runtime owns the only mutable state and hands out immutable
snapshots, so the dashboard, the Modbus shim and anything else read the
same PLC scan.

## Theme

Light, deliberately. This is read on a plant floor under high ambient
light, where a dark panel behaves like a mirror. The palette comes from
the machine's own materials — mill concrete, galvanised steel, the
machine-green of the enamel, the burnt amber of the shuttles — and lives
as custom properties at the top of `src/App.css`.

**No webfonts.** The deployment target has no route to a font CDN, and a
stylesheet that blocks on one shows the operator an empty panel. Type
personality comes from instrument vernacular instead: large tabular
monospace readouts against small wide-tracked uppercase labels.

The 3D scene carries its own lighting environment built from
`<Lightformer>`s rather than an HDR file, for the same offline reason.
It is not decoration — the machine material is metallic, and a metal with
nothing to reflect renders black.

## The machine model

The 3D machine is the real CAD, reduced to `ui/public/loom.glb` by
`tools/build_loom_model.py`. The GLB is a **build artefact** and is
gitignored — a fresh clone has no model, and the scene falls back to a
primitive frame rather than showing an empty canvas. To build it you need
Blender and `loom-meshed.blend`:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
    loom-meshed.blend --background --python tools/build_loom_model.py
# 53 M polys -> 580 k, 6.0 MB, ~7 s

... --python tools/build_loom_model.py -- --include-creel   # whole machine
... --python tools/build_loom_model.py -- --render          # geometry check
```

Nothing else in the repo needs Blender, and the engine never imports this
script — the stdlib-only rule is unaffected.

**The mesh is a visual shell and carries no simulation state.** It is
voxel-remeshed at 3–12 mm depending on the part, so its surfaces
approximate the CAD rather than being it, and none of its parts move. Do
not derive positions, angles or sensor triggers from it; the twin is the
source of truth for all of that.

**There are no shuttles in the CAD.** All 117 assemblies were checked —
creel, compensators, reeds, loom bed, take-up, winders — and not one is a
shuttle or bobbin. The six shuttles are synthesised in `Shuttles.jsx` and
driven from `shuttle_position`, i.e. from the twin's `CyclicShuttleModel`.
They are placed by measuring the reed assembly in the loaded GLB, not by
a hardcoded radius: the model spans the whole 5.7 m machine and the loom
head is a ~0.6-unit ring off-centre within it, so a fixed radius puts the
shuttles beside the machine instead of on its track. If the reed node
cannot be found, the shuttles are hidden rather than drawn somewhere
wrong.

## Two behaviours that look like bugs and are not

The twin used to run **open-loop**: `api_server.py` commanded the motor
directly and injected a jam on a timer, and no PLC existed anywhere —
so there were no `Y` outputs at all. The PLC is now in the loop:

```
twin sensors ──► PLC inputs ──► PLC.scan() ──► PLC outputs ──► motor
```

running `programs/shuttle_control.st` (`Y0 := X0 AND NOT X2`,
`Y1 := X1`). Two visible behaviours changed as a result. **Both are
intended. Please do not "fix" either.**

### 1. X0 stays TRUE during a jam

Before, the jam was implemented by dropping `X0`. That was the twin
cheating: `X0` is the operator's **run command**, and nothing about a
jam withdraws it. A real machine jams while the operator is still
asking it to run — that is the entire situation.

Now `X2` (jam) rises, the PLC evaluates `Y0 := X0 AND NOT X2`, and
`Y0` falls. `X0` stays asserted throughout, which is why the sensor
panel keeps showing X0 lit during a jam.

### 2. The motor reads "running" for one more scan after the jam

```
        t      X0     X2     Y0   motor_running
  12310ms    True  False   True   True
  12320ms    True   True  False   True     <-- jam is up, motor still True
  12330ms    True   True  False   False
```

`Y0` falls in the **same scan** `X2` is sampled — the PLC samples its
inputs and evaluates them within one scan, so the logic adds no
latency at all. But that scan's physics already ran before the scan
committed the new motor command, so `motor_running` is still `True` in
that snapshot and turns over on the next one.

At the default 10ms scan period that is a 10ms window where the jam
banner is up and the motor still reads as running. It is one scan of
observation lag, not a missed stop.

## The twin does not run at a real loom's speed

**The twin completes a shuttle revolution every 1.8–6 seconds — 10 to
33 rpm depending on the calibration profile. A real 6-shuttle circular
loom runs at around 200 rpm.**

So the twin is roughly an order of magnitude slow, and it models a
single position sensor firing once per revolution — it has no
per-shuttle event at all, where a real loom at 200 rpm passes a shuttle
about every 50 ms.

This matters if you are using the twin as a bench target and reasoning
about timing. Control *logic* exercised against it is valid; anything
that depends on the machine's real rate — poll budgets, sample counts
per shuttle pass, throughput figures — is not. Do not quote the twin's
timing as representative of a machine.

| Profile      | speed (u/s) | cycle time | rpm  | sensor pulse |
| ------------ | ----------- | ---------- | ---- | ------------ |
| `default`    | 100         | 3.6 s      | 16.7 | 200 ms       |
| `fast`       | 200         | 1.8 s      | 33.3 | 100 ms       |
| `slow`       | 80          | 4.5 s      | 13.3 | 250 ms       |
| shim default | 60          | 6.0 s      | 10.0 | 333 ms       |

Re-speeding it is a deliberate deferral, not an oversight: at 200 rpm
the cycle is 300 ms and a 20-unit sensor window becomes a **16.7 ms**
pulse, which forces `scan_period_ms=5` and a rethink of the sensor
window, and invalidates all three calibration profiles. The full
derivation is preserved in `docs/backlog.md` so it does not have to be
reconstructed.

## Rates

The runtime integrates physics at `sim_step_ms=1` and scans the PLC at
`scan_period_ms=10`. They are deliberately different: if they were
equal the PLC would see every physics update and no sub-scan event
could exist, so a sensor pulse narrower than one scan could never be
missed — which real controllers do all the time. See
`src/shim/twin_runtime.py`.

Real loom PLCs scan at 5–20ms. The previous `step_ms=100` was a
simulation convenience, never a modelled scan period. The scan period
is realistic; the machine speed it is scanning (above) is not.

## State contract

```jsonc
{
  "time": 1970,                 // ms, PLC scan time
  "motor_running": true,
  "shuttle_position": 99.6,     // degrees, 0-360
  "sensors": { "X0": true, "X1": false, "X2": false },
  "jam_detected": false,

  // additive; the dashboard reads the five keys above
  "outputs": { "Y0": true, "Y1": false },
  "motor_state": "RUNNING",     // STOPPED|STARTING|RUNNING|STOPPING
  "scan_count": 197,
  "cycles_completed": 0
}
```
