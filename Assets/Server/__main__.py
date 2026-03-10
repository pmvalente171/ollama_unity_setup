import threading
from server import app, agents
from colors import YELLOW, BOLD, DIM, RESET, CYAN

def run_flask():
    # Disable Flask's reloader — it conflicts with background threads
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    # Start Flask in the background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"{BOLD}Flask server running on http://localhost:5000{RESET}")
    print(f"{DIM}Unity should be open and listening on port 8080.{RESET}")
    print(f"{DIM}Type a building description and press Enter. Type 'quit' to exit.{RESET}\n")

    # Interactive REPL — drives the coordinator directly from the terminal
    while True:
        try:
            instruction = input(f"{YELLOW}> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not instruction:
            continue
        if instruction.lower() in ("quit", "exit"):
            break

        print(f"\n{CYAN}{BOLD}Running coordinator...{RESET}\n")
        response = agents["coordinator"].run(instruction)
        print(f"\n{BOLD}Coordinator finished:{RESET} {response}\n")
