# Vendored Draco decoder

`loom.glb` is Draco-compressed, so the browser needs a decoder to open it.

drei's `useGLTF` defaults to fetching one from a Google CDN. It is vendored
here instead so the dashboard runs on a plant network with no internet route
— which is the deployment this whole repo is aimed at. `LoomModel.jsx` passes
`'/draco/'` as the decoder path for exactly that reason; drop these files and
the model silently fails to load anywhere without outbound HTTPS.

Decoder only. The encoder lives in Blender's glTF exporter, so nothing in the
browser ever needs it.

Source: `three/examples/jsm/libs/draco/` from the pinned `three` version in
`ui/package.json`. Re-copy from there if `three` is upgraded.
