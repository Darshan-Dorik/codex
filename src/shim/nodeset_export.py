"""
nodeset_export.py — OPC UA NodeSet2 Export

Generates a UANodeSet XML file from the SAME signal definitions that
drive the Modbus register map. One source, two faces: adding a signal
in tag_map.make_twin_signals() adds it to both, and there is no second
place for the two to disagree.

Stdlib only (xml.etree).

WHY THE MODEL AND NOT A SERVER
------------------------------
A conformant OPC UA binary server is thousands of lines before UaExpert
connects — UACP handshake, OpenSecureChannel, GetEndpoints, session
activation, the binary encoder across 25 built-in types, chunking —
and that is before subscriptions, which is how every real collector
actually reads OPC UA. The durable artefact is the INFORMATION MODEL,
not the socket code: the model is what a conformance tool checks and
what the platform repo consumes. So this repo emits a versioned
NodeSet2 file and the platform repo (which has no stdlib constraint)
serves it with a real library.

Testing a collector against a hand-rolled server would test it against
our protocol bugs. Testing it against asyncua loaded with this NodeSet
tests it against a conformant implementation.

NAMESPACE — DELIBERATELY OURS
-----------------------------
This does NOT map to EUROMAP 84 / OPC 40084. The 40084 series has no
circular loom part, so mapping onto it now would mean extending a
standard before ever conforming to one — exactly the mistake the
platform brief warns about. This uses its own namespace URI.

The hierarchy is shaped so that mapping is later MECHANICAL rather
than a re-model:

    line -> unit -> measure          (this file)
    <enterprise>/<site>/<area>/<line>/<unit>/<measure>   (topic namespace)

40084 organises a line into components with variables; "unit" here
corresponds to a component and "measure" to its variables. Intended
alignment is noted in comments only, and nothing in this file claims
conformance to anything.

ACCESS LEVEL
------------
Every variable is AccessLevel=1 (CurrentRead) with UserAccessLevel=1.
Read-only, matching the Modbus face where read-only is a property of
the address space rather than a rule being trusted.

REPRODUCIBILITY
---------------
The file is byte-reproducible: no timestamps, no generated GUIDs, node
ids assigned deterministically in declaration order. A versioned
artefact that changes on every run cannot be diffed, and a NodeSet
that cannot be diffed cannot be reviewed.
"""

import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tag_map import make_twin_signals, PROTOCOL_VERSION

UANODESET_NS = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
XSI_NS       = "http://www.w3.org/2001/XMLSchema-instance"

# Well-known OPC UA node ids (Part 6, Annex A).
OBJECTS_FOLDER          = "i=85"
BASE_OBJECT_TYPE        = "i=58"
BASE_DATA_VARIABLE_TYPE = "i=63"
FOLDER_TYPE             = "i=61"
ORGANIZES               = "i=35"
HAS_TYPE_DEFINITION     = "i=40"
HAS_COMPONENT           = "i=47"

# Built-in DataType node ids, exposed through Aliases for readability.
DATATYPE_IDS = {
    "Boolean": "i=1",
    "SByte":   "i=2",
    "Byte":    "i=3",
    "Int16":   "i=4",
    "UInt16":  "i=5",
    "Int32":   "i=6",
    "UInt32":  "i=7",
    "Double":  "i=11",
    "String":  "i=12",
}

# Node id allocation. Fixed bases so ids are stable across runs and
# additions do not renumber existing nodes.
LINE_NODE_ID   = 5000
UNIT_NODE_BASE = 5100
VAR_NODE_BASE  = 6000

# Fixed so the artefact is byte-reproducible; bump with the model.
MODEL_VERSION      = f"1.{PROTOCOL_VERSION}.0"
MODEL_PUBLICATION  = "2026-08-13T00:00:00Z"


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = text
    return el


def _references(node, refs):
    """
    Append a References block.

    Element ORDER matters: UAVariable extends UAInstance extends UANode
    via complexContent, so the base sequence (DisplayName, Description,
    ..., References) comes BEFORE the extension's own elements. Emitting
    References after Value fails schema validation.
    """
    refs_el = _sub(node, "References")
    for ref_type, target, is_forward in refs:
        attrs = {"ReferenceType": ref_type}
        if not is_forward:
            attrs["IsForward"] = "false"
        _sub(refs_el, "Reference", text=target, **attrs)
    return refs_el


def build_nodeset(signal_set):
    """
    Build the NodeSet2 element tree for a SignalSet.

    Returns:
        xml.etree.ElementTree.Element — the UANodeSet root
    """
    ET.register_namespace("", UANODESET_NS)
    ET.register_namespace("xsi", XSI_NS)

    root = ET.Element(f"{{{UANODESET_NS}}}UANodeSet")

    # --- NamespaceUris ---
    ns_uris = _sub(root, "NamespaceUris")
    _sub(ns_uris, "Uri", text=signal_set.namespace_uri)

    # --- Models ---
    models = _sub(root, "Models")
    _sub(models, "Model",
         ModelUri=signal_set.namespace_uri,
         Version=MODEL_VERSION,
         PublicationDate=MODEL_PUBLICATION)

    # --- Aliases ---
    aliases = _sub(root, "Aliases")
    used_types = sorted({s.datatype for s in signal_set.signals})
    unknown = [t for t in used_types if t not in DATATYPE_IDS]
    if unknown:
        # A bare KeyError here reads as a bug in the exporter rather
        # than what it is: a signal declared with a datatype the model
        # has no OPC UA built-in for.
        offenders = {s.measure: s.datatype for s in signal_set.signals
                     if s.datatype in unknown}
        raise ValueError(
            f"signals declare datatypes with no OPC UA alias: "
            f"{offenders}. Known types: {sorted(DATATYPE_IDS)}. Add the "
            f"built-in to DATATYPE_IDS, or use one of those.")
    for name in used_types:
        _sub(aliases, "Alias", text=DATATYPE_IDS[name], Alias=name)
    for name, nid in (("Organizes", ORGANIZES),
                      ("HasTypeDefinition", HAS_TYPE_DEFINITION),
                      ("HasComponent", HAS_COMPONENT)):
        _sub(aliases, "Alias", text=nid, Alias=name)

    line_id = f"ns=1;i={LINE_NODE_ID}"

    # --- The line object, under the Objects folder ---
    line_node = _sub(root, "UAObject",
                     NodeId=line_id,
                     BrowseName=f"1:{signal_set.line}")
    _sub(line_node, "DisplayName", text=signal_set.line)
    _sub(line_node, "Description",
         text=(f"Line {signal_set.line} at "
               f"{signal_set.enterprise}/{signal_set.site}/"
               f"{signal_set.area}. Program: {signal_set.program}"))
    _references(line_node, [
        ("HasTypeDefinition", BASE_OBJECT_TYPE, True),
        ("Organizes", OBJECTS_FOLDER, False),
    ])

    # --- One object per machine unit, one variable per measure ---
    var_index = 0
    for unit_index, unit_name in enumerate(signal_set.units()):
        unit_id = f"ns=1;i={UNIT_NODE_BASE + unit_index}"

        unit_node = _sub(root, "UAObject",
                         NodeId=unit_id,
                         BrowseName=f"1:{unit_name}",
                         ParentNodeId=line_id)
        _sub(unit_node, "DisplayName", text=unit_name)
        _sub(unit_node, "Description",
             text=(f"Machine unit '{unit_name}' of {signal_set.line}. "
                   f"Corresponds to what OPC 40084 calls a component; "
                   f"not mapped to it — see module docstring."))
        _references(unit_node, [
            ("HasTypeDefinition", BASE_OBJECT_TYPE, True),
            ("HasComponent", line_id, False),
        ])

        for signal in signal_set.by_unit(unit_name):
            var_id = f"ns=1;i={VAR_NODE_BASE + var_index}"
            var_index += 1

            var_node = _sub(root, "UAVariable",
                            NodeId=var_id,
                            BrowseName=f"1:{signal.measure}",
                            ParentNodeId=unit_id,
                            DataType=signal.datatype,
                            AccessLevel=1,
                            UserAccessLevel=1)
            _sub(var_node, "DisplayName", text=signal.measure)

            description = signal.note
            extras = []
            if signal.symbol:
                extras.append(f"PLC symbol {signal.symbol} "
                              f"({signal_set.program})")
            if signal.eng_unit:
                extras.append(f"unit: {signal.eng_unit}")
            if signal.enum_values:
                extras.append("values: " + ", ".join(
                    f"{i}={v}" for i, v in enumerate(signal.enum_values)))
            extras.append(f"topic: {signal_set.topic(signal)}")
            if signal.modbus is not None:
                where = (f"register {signal.modbus.address}"
                         if signal.modbus.bit is None
                         else f"register {signal.modbus.address} "
                              f"bit {signal.modbus.bit}")
                extras.append(f"modbus: {where}")
            if extras:
                description = description + " [" + "; ".join(extras) + "]"
            _sub(var_node, "Description", text=description)

            # References BEFORE Value — see _references().
            _references(var_node, [
                ("HasTypeDefinition", BASE_DATA_VARIABLE_TYPE, True),
                ("HasComponent", unit_id, False),
            ])

    return root


def nodeset_xml(signal_set):
    """Serialise the NodeSet to a UTF-8 XML string."""
    root = build_nodeset(signal_set)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def write_nodeset(signal_set, filepath):
    """Write the NodeSet2 file. Returns the path."""
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(nodeset_xml(signal_set))
    return filepath


def structural_check(xml_text, signal_set):
    """
    Structural checks the XSD cannot express.

    Schema validation proves the file is well-formed UANodeSet. It does
    NOT prove the model is the one we meant: that every signal became a
    variable, that node ids are unique, that nothing is orphaned, or
    that everything is read-only. Those are checked here.

    Returns:
        {"ok": bool, "errors": [str, ...], "counts": {...}}
    """
    errors = []
    root = ET.fromstring(xml_text)

    def tag_of(el):
        return el.tag.split("}")[-1]

    objects   = [e for e in root if tag_of(e) == "UAObject"]
    variables = [e for e in root if tag_of(e) == "UAVariable"]

    node_ids = [e.get("NodeId") for e in objects + variables]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate NodeId in the nodeset")

    expected_measures = {s.measure for s in signal_set.signals}
    actual_measures = {v.get("BrowseName").split(":", 1)[1]
                       for v in variables}
    missing = expected_measures - actual_measures
    extra   = actual_measures - expected_measures
    if missing:
        errors.append(f"signals with no variable node: {sorted(missing)}")
    if extra:
        errors.append(f"variable nodes with no signal: {sorted(extra)}")

    for var in variables:
        name = var.get("BrowseName")
        if var.get("AccessLevel") != "1":
            errors.append(f"{name} is not read-only "
                          f"(AccessLevel={var.get('AccessLevel')})")
        if var.get("DataType") not in DATATYPE_IDS:
            errors.append(f"{name} has unaliased DataType "
                          f"{var.get('DataType')}")
        if var.get("ParentNodeId") is None:
            errors.append(f"{name} is orphaned (no ParentNodeId)")

    # Every node must be reachable from the Objects folder.
    ids = set(node_ids)
    parents = {e.get("NodeId"): e.get("ParentNodeId")
               for e in objects + variables}
    for node_id, parent in parents.items():
        if parent is not None and parent not in ids:
            errors.append(f"{node_id} has parent {parent} not in the set")

    # Element order: References must precede Value inside a UAVariable.
    for var in variables:
        children = [tag_of(c) for c in var]
        if "Value" in children and "References" in children:
            if children.index("References") > children.index("Value"):
                errors.append(f"{var.get('BrowseName')}: References must "
                              f"precede Value")

    return {
        "ok":     not errors,
        "errors": errors,
        "counts": {"objects": len(objects), "variables": len(variables)},
    }


if __name__ == "__main__":
    import json
    import shutil
    import subprocess

    print("=" * 60)
    print("Phase 11 - Step 9: OPC UA NodeSet2 Export")
    print("=" * 60)

    signals = make_twin_signals()
    xml_text = nodeset_xml(signals)

    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "outputs", "nodesets", "LoomTwin.NodeSet2.xml")
    write_nodeset(signals, out_path)

    print(f"\n  namespace : {signals.namespace_uri}")
    print(f"  program   : {signals.program}")
    print(f"  written   : {out_path} ({len(xml_text)} bytes)")

    # -------------------------------------------------------
    print("\nTest 1 — Hierarchy mirrors the topic namespace:")
    for unit in signals.units():
        print(f"  {signals.line}/{unit}")
        for sig in signals.by_unit(unit):
            sym = f" [{sig.symbol}]" if sig.symbol else ""
            print(f"      {sig.measure:20} {sig.datatype:8}{sym}")
    print(f"\n  topic form: {signals.topic(signals.by_measure('position'))}")

    # -------------------------------------------------------
    print("\nTest 2 — Structural check:")
    structural = structural_check(xml_text, signals)
    print(f"  objects={structural['counts']['objects']} "
          f"variables={structural['counts']['variables']}")
    print(f"  ok={structural['ok']} errors={structural['errors']}")

    # -------------------------------------------------------
    print("\nTest 3 — Byte-reproducible:")
    again = nodeset_xml(make_twin_signals())
    print(f"  regenerated → "
          f"{'identical' if again == xml_text else 'DIFFERENT'}")

    # -------------------------------------------------------
    print("\nTest 4 — Both faces come from one definition:")
    from tag_map import modbus_tag_map
    tm = modbus_tag_map(signals)
    root = ET.fromstring(xml_text)
    var_names = {v.get("BrowseName").split(":", 1)[1]
                 for v in root if v.tag.endswith("UAVariable")}
    modbus_covered = set()
    for sig in signals.signals:
        if sig.modbus is not None:
            modbus_covered.add(sig.measure)
    print(f"  signals defined      : {len(signals.signals)}")
    print(f"  OPC UA variables     : {len(var_names)}")
    print(f"  Modbus-placed signals: {len(modbus_covered)}")
    print(f"  registers            : {tm.size}")

    # -------------------------------------------------------
    print("\nTest 5 — XSD schema validation:")
    xsd_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "UANodeSet.xsd")
    xmllint = shutil.which("xmllint")
    schema_result = None
    if not os.path.exists(xsd_path):
        print(f"  SKIPPED — schema not vendored at {xsd_path}")
    elif xmllint is None:
        print("  SKIPPED — xmllint not available")
    else:
        proc = subprocess.run(
            [xmllint, "--noout", "--schema", xsd_path, out_path],
            capture_output=True, text=True)
        schema_result = proc.returncode
        print(f"  xmllint --schema UANodeSet.xsd → exit {proc.returncode}")
        for line in (proc.stderr or "").strip().splitlines():
            print(f"    {line}")

    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert structural["ok"], f"structural errors: {structural['errors']}"
    print(f"  PASS — structure valid: "
          f"{structural['counts']['objects']} objects, "
          f"{structural['counts']['variables']} variables, "
          f"all read-only, none orphaned")

    assert var_names == {s.measure for s in signals.signals}, \
        "every signal must become exactly one variable"
    print("  PASS — every signal has exactly one OPC UA variable "
          "and vice versa")

    assert modbus_covered == var_names, \
        "the two faces must cover the same signals"
    print(f"  PASS — Modbus and OPC UA project the SAME "
          f"{len(var_names)} signals from one definition")

    assert again == xml_text, "the artefact must be byte-reproducible"
    print("  PASS — byte-reproducible across regeneration")

    if schema_result is not None:
        assert schema_result == 0, \
            "the NodeSet must validate against the official UANodeSet XSD"
        print("  PASS — validates against the official OPC Foundation "
              "UANodeSet XSD (xmllint)")
    else:
        print("  SKIP — XSD validation not run in this environment")
