import re
import ollama
import tools
from colors import CYAN, YELLOW, GREEN, DIM, RED, RESET


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks that leak into content when think=False is ignored."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()

MODEL = "qwen3-vl-fast"
MAX_TOOL_ROUNDS = 30  # coordinator needs: 5 creates + 3 broadcasts + text turns between steps


class Agent:
    def __init__(self, agent_id, name, system_prompt, tool_names=None, model=MODEL):
        self.id = agent_id
        self.name = name
        self.system_prompt = system_prompt
        self.tool_names = tool_names or []
        self.model = model
        # Persistent history — agents remember previous interactions
        # /no_think must be at the top of the system message for Qwen3 to honour it
        self.messages = [{"role": "system", "content": f"/no_think\n{self.system_prompt}"}]

    def run(self, instruction):
        """
        Run a plan-and-execute loop for the given instruction.
        Conversation history is preserved across calls so agents remember
        their previous proposals, votes, etc.
        """
        self.messages.append({"role": "user", "content": instruction})
        tool_schemas = tools.get_schemas(self.tool_names)

        for _ in range(MAX_TOOL_ROUNDS):
            response = ollama.chat(
                model=self.model,
                messages=self.messages,
                tools=tool_schemas if tool_schemas else None,
            )

            message = response.message
            if message.thinking:
                print(f"{RED}[{self.name}] WARNING: thinking is still active ({len(message.thinking)} chars){RESET}")

            # Strip any <think> blocks that leaked into the content
            clean_content = _strip_thinking(message.content)
            self.messages.append({"role": "assistant", "content": clean_content, "tool_calls": message.tool_calls})

            # No tool calls
            if not message.tool_calls:
                # Empty response = model stalled; nudge it to continue
                if not clean_content:
                    print(f"{YELLOW}[{self.name}] Empty response, nudging...{RESET}")
                    self.messages.append({"role": "user", "content": "Continue. Use your tools to proceed with the task."})
                    continue
                return clean_content

            # Execute each tool call and append results
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments or {}
                result = tools.call(name, args)
                print(f"{CYAN}[{self.name}]{RESET} {YELLOW}{name}{RESET}({DIM}{args}{RESET}) {GREEN}=> {result}{RESET}")
                self.messages.append({"role": "tool", "content": result})

        return "Reached maximum tool call rounds without a final answer."
