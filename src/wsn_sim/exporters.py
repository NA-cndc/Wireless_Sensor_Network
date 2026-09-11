"""Export WSN topology to external verification engines (ns-3, OMNeT++/INET, Contiki-NG)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wsn_sim.network import Network


def export_to_ns3_mobility(network: Network, output_path: str | Path) -> Path:
    """Export node positions to ns-2/ns-3 mobility trace format.

    Format: $node_(<id>) set X_ <x>
            $node_(<id>) set Y_ <y>
            $node_(<id>) set Z_ 0.0

    Args:
        network: Active Network instance containing sensors and sinks.
        output_path: Path to the output trace file.

    Returns:
        Path of the written trace file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# ns-3 mobility trace for WSN simulation (seed={network.config.seed})",
        f"# Area: {network.config.area_width_m}m x {network.config.area_height_m}m",
        f"# Sensors: {len(network.sensors)}, Sinks: {len(network.sinks)}",
        "",
    ]

    all_nodes = {**network.sensors, **network.sinks}
    for index, (node_id, node) in enumerate(all_nodes.items()):
        lines.append(f"# {node_id} ({'sink' if 'sink' in node_id else 'sensor'})")
        lines.append(f"$node_({index}) set X_ {node.x:.2f}")
        lines.append(f"$node_({index}) set Y_ {node.y:.2f}")
        lines.append(f"$node_({index}) set Z_ 0.00")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_to_omnetpp_ned(
    network: Network,
    output_path: str | Path,
    network_name: str = "WsnNetwork",
) -> Path:
    """Export network topology to an OMNeT++ / INET Network Description (.ned) file.

    Args:
        network: Active Network instance.
        output_path: Path to the output .ned file.
        network_name: Name of the NED network module.

    Returns:
        Path of the written .ned file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"// OMNeT++ / INET Network Description for WSN (seed={network.config.seed})",
        "package wsn.simulations;",
        "",
        "import inet.node.inet.SensorNode;",
        "import inet.node.inet.WirelessHost;",
        "import inet.physicallayer.wireless.common.medium.RadioMedium;",
        "",
        f"network {network_name} {{",
        "    parameters:",
        f'        @display("bgb={int(network.config.area_width_m)},{int(network.config.area_height_m)}");',
        "    submodules:",
        "        radioMedium: RadioMedium {",
        '            @display("p=50,50");',
        "        }",
    ]

    for sink_id, sink in network.sinks.items():
        lines.append(f"        {sink_id}: WirelessHost {{")
        lines.append(
            f'            @display("p={int(sink.x)},{int(sink.y)};i=device/antennatower");'
        )
        lines.append("        }")

    for sensor_id, sensor in network.sensors.items():
        lines.append(f"        {sensor_id}: SensorNode {{")
        lines.append(f'            @display("p={int(sensor.x)},{int(sensor.y)};i=misc/sensor");')
        lines.append("        }")

    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_to_cooja(network: Network, output_path: str | Path) -> Path:
    """Export network topology to Contiki-NG Cooja simulation XML (.csc).

    Args:
        network: Active Network instance.
        output_path: Path to output .csc file.

    Returns:
        Path of the written .csc file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sim = ET.Element("simconf")
    project = ET.SubElement(sim, "project")
    project.text = "Contiki-NG Cooja WSN Simulation"

    simulation = ET.SubElement(sim, "simulation")
    title = ET.SubElement(simulation, "title")
    title.text = f"WSN Simulation (seed={network.config.seed})"

    # Add motes for sinks and sensors
    mote_id = 1
    for sink in network.sinks.values():
        mote = ET.SubElement(simulation, "mote")
        ET.SubElement(mote, "motetype_identifier").text = "sink_mote"
        ET.SubElement(mote, "id").text = str(mote_id)
        pos = ET.SubElement(mote, "interface_config")
        ET.SubElement(pos, "x").text = f"{sink.x:.2f}"
        ET.SubElement(pos, "y").text = f"{sink.y:.2f}"
        ET.SubElement(pos, "z").text = "0.00"
        mote_id += 1

    for sensor in network.sensors.values():
        mote = ET.SubElement(simulation, "mote")
        ET.SubElement(mote, "motetype_identifier").text = "sensor_mote"
        ET.SubElement(mote, "id").text = str(mote_id)
        pos = ET.SubElement(mote, "interface_config")
        ET.SubElement(pos, "x").text = f"{sensor.x:.2f}"
        ET.SubElement(pos, "y").text = f"{sensor.y:.2f}"
        ET.SubElement(pos, "z").text = "0.00"
        mote_id += 1

    tree = ET.ElementTree(sim)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
