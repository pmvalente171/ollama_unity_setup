# Tool registry
# Tools are Python functions with a name, description, and JSON schema for parameters.
# Register tools here and assign them to agents by name.

_tools = {}


def register(name, description, parameters, func):
    """
    Register a tool that agents can use.

    parameters: JSON Schema object describing the tool's arguments, e.g.:
        {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X position"}
            },
            "required": ["x"]
        }
    """
    _tools[name] = {
        "func": func,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
    }


def call(name, args):
    """Call a registered tool by name with a dict of arguments."""
    if name not in _tools:
        return f"Error: tool '{name}' not found."
    try:
        result = _tools[name]["func"](**args)
        return str(result) if result is not None else "done"
    except Exception as e:
        return f"Error calling tool '{name}': {e}"


def get_schemas(names):
    """Return the Ollama-compatible tool schemas for a list of tool names."""
    return [_tools[n]["schema"] for n in names if n in _tools]
