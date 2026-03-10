import uuid
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify

import tools
from agent import Agent
from colors import CYAN, GREEN, YELLOW, MAGENTA, DIM, BOLD, RESET

app = Flask(__name__)

# ── Agent store ───────────────────────────────────────────────────────────────
agents = {}  # agent_id -> Agent

UNITY_URL = "http://localhost:8080"

# ── System prompts ────────────────────────────────────────────────────────────

BUILDER_SYSTEM_PROMPT = """You are a builder agent in a 3D Unity scene.
Ground y=0. 1 unit = 1 meter. To sit on ground: y = scale_y/2.
Primitives: cube, sphere, cylinder, capsule. Colors: RGB 0.0-1.0.

Reply in as few words as possible. Never explain. Never use filler. Just data.

PROPOSE → numbered list only. One object per line:
  type | x y z | scale_x scale_y scale_z | r g b
  Example: cube | 0 0.5 0 | 10 1 10 | 0.6 0.5 0.4

VOTE → one line per proposal:
  Name: APPROVE or REJECT - reason in 5 words max.

EXECUTE → call spawn_object for each object. No text at all."""

COORDINATOR_PROMPT = """You are a building coordinator. Work autonomously. No explanations. No pauses. Just tool calls.
Ground y=0. 1 unit = 1 meter. Stay within 20x20 area at (0,0,0).

Tools:
- create_builder_agent(name, zone_description) -> agent_id
- broadcast_to_agents(agent_ids, message) -> all responses (runs in parallel, always prefer this)
- send_message_to_agent(agent_id, message) -> response

Steps — execute immediately one after another:

1. CREATE: call create_builder_agent 5 times (Foundation, North Wall, South Wall, Side Walls, Roof). Save each id.
2. PROPOSE: broadcast "PROPOSE your zone of a [building]. List: type | x y z | sx sy sz | r g b"
3. VOTE: broadcast all 5 proposals, ask "VOTE: APPROVE/REJECT each OTHER plan. 5 words max per vote."
4. EXECUTE: broadcast "EXECUTE your plan. Call spawn_object for every object. No text."
5. done."""

# ── Tool implementations ──────────────────────────────────────────────────────

def _send_unity_event(event_name, payload):
    """Send a flat event payload to Unity."""
    try:
        r = requests.post(f"{UNITY_URL}/event",
                          json={"eventName": event_name, **payload},
                          timeout=5)
        return r.text
    except Exception as e:
        return f"Unity unreachable: {e}"


def _create_builder_agent(name, zone_description):
    """Create a builder agent pre-configured with Unity tools."""
    agent_id = str(uuid.uuid4())
    agent = Agent(
        agent_id=agent_id,
        name=name,
        system_prompt=BUILDER_SYSTEM_PROMPT + f"\n\nYour zone: {zone_description}",
        tool_names=["spawn_object", "move_object", "draw_line",
                    "delete_object", "send_message_to_agent"],
        model="qwen3-vl-fast",
    )
    agents[agent_id] = agent
    print(f"{GREEN}[server] Builder '{name}' created{RESET} {DIM}(id={agent_id}){RESET}")
    return agent_id


def _send_message_to_agent(target_agent_id, message):
    if target_agent_id not in agents:
        return f"Agent '{target_agent_id}' not found."
    target = agents[target_agent_id]
    print(f"\n{DIM}{'─'*60}{RESET}")
    print(f"{CYAN}{BOLD}[→ {target.name}]{RESET} {message}")
    response = target.run(message)
    print(f"{MAGENTA}{BOLD}[← {target.name}]{RESET} {response}")
    print(f"{DIM}{'─'*60}{RESET}\n")
    return response


def _broadcast_to_agents(agent_ids, message):
    """Send the same message to multiple agents IN PARALLEL. Returns a combined response."""
    missing = [aid for aid in agent_ids if aid not in agents]
    if missing:
        return f"Unknown agent IDs: {missing}"

    results = {}
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_send_message_to_agent, aid, message): aid
                   for aid in agent_ids}
        for future in as_completed(futures):
            aid = futures[future]
            results[agents[aid].name] = future.result()

    return "\n\n".join(f"[{name}]: {resp}" for name, resp in results.items())


def _spawn_object(object_type, x, y, z,
                  scale_x=1.0, scale_y=1.0, scale_z=1.0,
                  r=1.0, g=1.0, b=1.0):
    object_id = str(uuid.uuid4())[:8]
    _send_unity_event("spawn_object", {
        "id": object_id, "type": object_type,
        "x": float(x), "y": float(y), "z": float(z),
        "ex": 0.0, "ey": 0.0, "ez": 0.0,
        "sx": float(scale_x), "sy": float(scale_y), "sz": float(scale_z),
        "r": float(r), "g": float(g), "b": float(b),
    })
    return f"spawned:{object_id}"


def _move_object(object_id, x, y, z):
    return _send_unity_event("move_object", {
        "id": object_id, "type": "",
        "x": float(x), "y": float(y), "z": float(z),
        "ex": 0.0, "ey": 0.0, "ez": 0.0,
        "sx": 1.0, "sy": 1.0, "sz": 1.0,
        "r": 1.0, "g": 1.0, "b": 1.0,
    })


def _draw_line(x1, y1, z1, x2, y2, z2, r=1.0, g=0.0, b=0.0):
    line_id = str(uuid.uuid4())[:8]
    _send_unity_event("draw_line", {
        "id": line_id, "type": "line",
        "x": float(x1), "y": float(y1), "z": float(z1),
        "ex": float(x2), "ey": float(y2), "ez": float(z2),
        "sx": 0.1, "sy": 0.1, "sz": 0.1,
        "r": float(r), "g": float(g), "b": float(b),
    })
    return f"line:{line_id}"


def _delete_object(object_id):
    return _send_unity_event("delete_object", {
        "id": object_id, "type": "",
        "x": 0.0, "y": 0.0, "z": 0.0,
        "ex": 0.0, "ey": 0.0, "ez": 0.0,
        "sx": 1.0, "sy": 1.0, "sz": 1.0,
        "r": 1.0, "g": 1.0, "b": 1.0,
    })


# ── Register tools ────────────────────────────────────────────────────────────

tools.register(
    name="create_builder_agent",
    description="Create a new builder agent for a specific zone of the building. Returns the agent's ID.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Display name, e.g. 'Foundation Builder'."},
            "zone_description": {"type": "string", "description": "What this builder is responsible for."},
        },
        "required": ["name", "zone_description"],
    },
    func=_create_builder_agent,
)

tools.register(
    name="send_message_to_agent",
    description="Send a message to one agent by ID and get its response.",
    parameters={
        "type": "object",
        "properties": {
            "target_agent_id": {"type": "string", "description": "The ID of the agent to message."},
            "message": {"type": "string", "description": "The message to send."},
        },
        "required": ["target_agent_id", "message"],
    },
    func=_send_message_to_agent,
)

tools.register(
    name="broadcast_to_agents",
    description="Send the same message to multiple agents IN PARALLEL and get all responses at once. Much faster than messaging them one by one.",
    parameters={
        "type": "object",
        "properties": {
            "agent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of agent IDs to message simultaneously.",
            },
            "message": {"type": "string", "description": "The message to send to all of them."},
        },
        "required": ["agent_ids", "message"],
    },
    func=_broadcast_to_agents,
)

tools.register(
    name="spawn_object",
    description="Spawn a primitive 3D object in Unity at a given position, scale, and color. Returns the object's ID.",
    parameters={
        "type": "object",
        "properties": {
            "object_type": {"type": "string", "description": "Primitive type: cube, sphere, cylinder, or capsule."},
            "x": {"type": "number", "description": "Position on the X axis (east/west)."},
            "y": {"type": "number", "description": "Position on the Y axis (up). Set to scale_y/2 to sit on ground."},
            "z": {"type": "number", "description": "Position on the Z axis (north/south)."},
            "scale_x": {"type": "number", "description": "Width. Default 1."},
            "scale_y": {"type": "number", "description": "Height. Default 1."},
            "scale_z": {"type": "number", "description": "Depth. Default 1."},
            "r": {"type": "number", "description": "Red channel 0.0–1.0. Default 1."},
            "g": {"type": "number", "description": "Green channel 0.0–1.0. Default 1."},
            "b": {"type": "number", "description": "Blue channel 0.0–1.0. Default 1."},
        },
        "required": ["object_type", "x", "y", "z"],
    },
    func=_spawn_object,
)

tools.register(
    name="move_object",
    description="Move an existing Unity object to a new position.",
    parameters={
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "description": "The ID returned by spawn_object."},
            "x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"},
        },
        "required": ["object_id", "x", "y", "z"],
    },
    func=_move_object,
)

tools.register(
    name="draw_line",
    description="Draw a line between two points in the Unity scene. Returns the line's ID.",
    parameters={
        "type": "object",
        "properties": {
            "x1": {"type": "number"}, "y1": {"type": "number"}, "z1": {"type": "number"},
            "x2": {"type": "number"}, "y2": {"type": "number"}, "z2": {"type": "number"},
            "r": {"type": "number", "description": "Red 0–1. Default 1."},
            "g": {"type": "number", "description": "Green 0–1. Default 0."},
            "b": {"type": "number", "description": "Blue 0–1. Default 0."},
        },
        "required": ["x1", "y1", "z1", "x2", "y2", "z2"],
    },
    func=_draw_line,
)

tools.register(
    name="delete_object",
    description="Delete an object from the Unity scene by its ID.",
    parameters={
        "type": "object",
        "properties": {
            "object_id": {"type": "string", "description": "The ID of the object to delete."},
        },
        "required": ["object_id"],
    },
    func=_delete_object,
)


# ── Bootstrap coordinator ─────────────────────────────────────────────────────

def _init_coordinator():
    coordinator = Agent(
        agent_id="coordinator",
        name="Coordinator",
        system_prompt=COORDINATOR_PROMPT,
        tool_names=["create_builder_agent", "broadcast_to_agents", "send_message_to_agent"],
        model="qwen3-vl-fast",
    )
    agents["coordinator"] = coordinator
    print(f"{YELLOW}{BOLD}[server] Coordinator initialized{RESET} {DIM}(id=coordinator){RESET}")

_init_coordinator()


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.route("/agents", methods=["GET"])
def list_agents():
    """List all active agents."""
    return jsonify([
        {"id": a.id, "name": a.name, "tools": a.tool_names, "model": a.model}
        for a in agents.values()
    ])


@app.route("/agents", methods=["POST"])
def create_agent():
    """
    Create a custom agent.
    Body: { name, system_prompt, tools (optional), model (optional) }
    """
    data = request.get_json()
    if not data or "name" not in data or "system_prompt" not in data:
        return jsonify({"error": "'name' and 'system_prompt' are required."}), 400

    agent_id = str(uuid.uuid4())
    agent = Agent(
        agent_id=agent_id,
        name=data["name"],
        system_prompt=data["system_prompt"],
        tool_names=data.get("tools", []),
        model=data.get("model", "qwen3-vl:8b"),
    )
    agents[agent_id] = agent
    print(f"{GREEN}[server] Created agent '{agent.name}'{RESET} {DIM}(id={agent_id}){RESET}")
    return jsonify({"id": agent_id, "name": agent.name}), 201


@app.route("/agents/<agent_id>/run", methods=["POST"])
def run_agent(agent_id):
    """
    Run an agent with an instruction.
    Body: { instruction }
    """
    if agent_id not in agents:
        return jsonify({"error": f"Agent '{agent_id}' not found."}), 404

    data = request.get_json()
    if not data or "instruction" not in data:
        return jsonify({"error": "'instruction' is required."}), 400

    instruction = data["instruction"]
    print(f"{YELLOW}[server] Running '{agents[agent_id].name}':{RESET} {instruction}")
    response = agents[agent_id].run(instruction)
    return jsonify({"response": response})
