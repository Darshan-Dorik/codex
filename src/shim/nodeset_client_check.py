"""
nodeset_client_check.py — Load the NodeSet in a Real OPC UA Client

A NodeSet that nobody has opened is not a NodeSet. XSD validation
proves the file is well-formed UANodeSet; it does not prove a real OPC
UA implementation can import it, resolve its references, and browse the
hierarchy. Those are different failures, and the second kind is the one
that surfaces at a customer site.

This check imports the generated NodeSet into an `asyncua` server and
browses it exactly as a client would — line → unit → measure — checking
datatypes and access levels on the way.

NOT PART OF THE STDLIB-ONLY ENGINE
----------------------------------
`asyncua` is a third-party package and is deliberately NOT a dependency
of this repo. This module degrades gracefully when it is absent, the
same way every AI path degrades when Ollama is not running.

To run it:

    python3 -m venv /tmp/uavenv
    /tmp/uavenv/bin/pip install asyncua
    /tmp/uavenv/bin/python src/shim/nodeset_client_check.py

UaExpert and opcua-modeler are the other clients worth trying. Both are
GUI applications, so they cannot be driven from here; asyncua is the
automatable equivalent and — being a conformant third-party stack —
is a better regression target than a hand-rolled server would be.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
DEFAULT_NODESET = os.path.join(_ROOT, "outputs", "nodesets",
                               "LoomTwin.NodeSet2.xml")

NAMESPACE_URI = "http://jpgroup.example/UA/LoomTwin/"
EXPECTED_VARIABLES = 12
EXPECTED_UNITS = ("controller", "drive", "shuttle")


def available():
    """True if asyncua is importable."""
    try:
        import asyncua        # noqa: F401
        return True
    except ImportError:
        return False


async def _load_and_browse(nodeset_path, line_name="loom-01"):
    from asyncua import Server, ua

    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://127.0.0.1:14840/loomtwin/")

    imported = await server.import_xml(nodeset_path)
    ns_index = await server.get_namespace_index(NAMESPACE_URI)

    result = {
        "imported_nodes": len(imported),
        "namespace_index": ns_index,
        "units": {},
        "variables": [],
        "writable": [],
        "errors": [],
    }

    async with server:
        line = None
        for child in await server.nodes.objects.get_children():
            if (await child.read_browse_name()).Name == line_name:
                line = child
        if line is None:
            result["errors"].append(
                f"line object {line_name!r} not found under Objects")
            return result

        for unit in await line.get_children():
            unit_name = (await unit.read_browse_name()).Name
            measures = []
            for var in await unit.get_children():
                name = (await var.read_browse_name()).Name
                dtype = (await var.read_data_type_as_variant_type()).name
                access = int((await var.read_attribute(
                    ua.AttributeIds.AccessLevel)).Value.Value)
                measures.append(name)
                result["variables"].append(
                    {"unit": unit_name, "measure": name,
                     "datatype": dtype, "access": access})
                # bit 1 (0x02) is CurrentWrite
                if access & 0x02:
                    result["writable"].append(f"{unit_name}/{name}")
            result["units"][unit_name] = measures

    return result


def check(nodeset_path=DEFAULT_NODESET):
    """Run the load-and-browse check. Returns the result dict."""
    import asyncio
    return asyncio.run(_load_and_browse(nodeset_path))


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 11 - Step 10: NodeSet Client Load Check")
    print("=" * 60)

    if not os.path.exists(DEFAULT_NODESET):
        print(f"\n  NodeSet not found at {DEFAULT_NODESET}")
        print("  Run: python3 src/shim/nodeset_export.py")
        sys.exit(1)

    if not available():
        print("\n  SKIPPED — asyncua is not installed.")
        print("  asyncua is intentionally NOT a dependency of this repo; "
              "the engine is stdlib-only.")
        print("\n  To run this check:")
        print("    python3 -m venv /tmp/uavenv")
        print("    /tmp/uavenv/bin/pip install asyncua")
        print("    /tmp/uavenv/bin/python src/shim/nodeset_client_check.py")
        sys.exit(0)

    print(f"\n  nodeset : {DEFAULT_NODESET}")
    result = check()

    print(f"  imported: {result['imported_nodes']} nodes")
    print(f"  namespace index: {result['namespace_index']}")

    print("\n  Browsed hierarchy:")
    for unit, measures in result["units"].items():
        print(f"    {unit}  ({len(measures)} variables)")
        for entry in result["variables"]:
            if entry["unit"] == unit:
                print(f"        {entry['measure']:20} "
                      f"{entry['datatype']:8} access={entry['access']}")

    print("\n--- Assertions ---")

    assert not result["errors"], f"errors: {result['errors']}"
    print("  PASS — a real OPC UA server imported the NodeSet")

    assert len(result["variables"]) == EXPECTED_VARIABLES, \
        (f"expected {EXPECTED_VARIABLES} variables, browsed "
         f"{len(result['variables'])}")
    print(f"  PASS — {len(result['variables'])} variables browsable "
          f"through the real client's address space")

    assert set(result["units"]) == set(EXPECTED_UNITS), \
        f"units {sorted(result['units'])} != {sorted(EXPECTED_UNITS)}"
    print(f"  PASS — line → unit → measure hierarchy intact "
          f"({', '.join(sorted(result['units']))})")

    assert not result["writable"], \
        f"writable variables in a read-only model: {result['writable']}"
    print("  PASS — every variable is read-only as browsed by the client, "
          "not merely as written in the XML")
