# ANSI color helpers for readable terminal output.
# Works on Windows 10+ (console supports ANSI by default).

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# Foreground colors
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
MAGENTA= "\033[95m"
RED    = "\033[91m"
WHITE  = "\033[97m"
BLUE   = "\033[94m"


def c(color, text):
    """Wrap text in a color code."""
    return f"{color}{text}{RESET}"
