"""
pipeline/nodes/spec_node.py
Stage 3: Spec Confirmation (user-facing pause point).

This node does not actively run — the pipeline pauses after parse_node sets
status to CONFIRMING and waits for the user to approve via the API.

The dashboard RunStatus screen displays the parsed spec and presents two options:
  - Approve and Build → POST /forge/runs/{id}/approve
  - Edit Blueprint → re-submit with corrections

On approval, the API enqueues run_pipeline_sync(run_id, "resume_from_architecture")
which skips directly to the architecture node.

This file provides the spec formatting utility used by the dashboard API route
to present the spec in a readable structure.
"""

from typing import Any


def format_spec_for_display(spec: dict) -> dict:
    """
    Format the raw spec JSON into a dashboard-friendly summary.
    Called by the runs route when status is CONFIRMING.
    """
    return {
        "agent_name": spec.get("agent_name", "Unknown"),
        "agent_slug": spec.get("agent_slug", "unknown"),
        "description": spec.get("description", ""),
        "fly_region": spec.get("fly_region", "syd"),
        "summary": {
            "total_files": len(spec.get("file_list", [])),
            "total_services": len(spec.get("fly_services", [])),
            "total_tables": len(spec.get("database_tables", [])),
            "total_routes": len(spec.get("api_routes", [])),
            "total_screens": len(spec.get("dashboard_screens", [])),
            "external_apis": spec.get("external_apis", []),
        },
        "fly_services": [
            {
                "name": s.get("name"),
                "type": s.get("type"),
                "machine": s.get("machine"),
                "memory": s.get("memory"),
                "description": s.get("description"),
            }
            for s in spec.get("fly_services", [])
        ],
        "database_tables": [
            {
                "name": t.get("name"),
                "description": t.get("description"),
                "column_count": len(t.get("columns", [])),
                "columns": [c.get("name") for c in t.get("columns", [])],
            }
            for t in spec.get("database_tables", [])
        ],
        "api_routes": [
            {
                "method": r.get("method"),
                "path": r.get("path"),
                "description": r.get("description"),
            }
            for r in spec.get("api_routes", [])
        ],
        "dashboard_screens": [
            {
                "name": s.get("name"),
                "route": s.get("route"),
                "description": s.get("description"),
            }
            for s in spec.get("dashboard_screens", [])
        ],
        "file_list_by_layer": _group_files_by_layer(spec.get("file_list", [])),
        "environment_variables": spec.get("environment_variables", []),
    }


def _group_files_by_layer(file_list: list[dict]) -> dict[str, list[dict]]:
    """Group file list by layer number for display."""
    layer_names = {
        1: "Database Schema",
        2: "Infrastructure",
        3: "Backend API",
        4: "Worker / Agent Logic",
        5: "Web Dashboard",
        6: "Deployment",
        7: "Documentation",
    }
    groups: dict[str, list[dict]] = {}
    for f in file_list:
        layer = f.get("layer", 0)
        key = f"{layer}. {layer_names.get(layer, f'Layer {layer}')}"
        if key not in groups:
            groups[key] = []
        groups[key].append({"path": f.get("path"), "description": f.get("description")})
    return groups
