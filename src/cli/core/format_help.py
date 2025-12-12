#!/usr/bin/env python3
"""
Format comprehensive help output for Rediacc CLI
Docker-style command listing with categories
"""

import sys
import json
import subprocess
from pathlib import Path

# ANSI color codes
CYAN = '\033[0;36m'
BLUE = '\033[0;34m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'  # No Color


def clean_description(desc: str) -> str:
    """Clean up description - remove 'Rediacc CLI X -' prefix if present"""
    if desc.startswith('Rediacc CLI'):
        # Extract text after the dash
        parts = desc.split(' - ', 1)
        if len(parts) > 1:
            return parts[1]
    return desc


def format_command_list(commands: list, max_name_len: int = 20) -> str:
    """Format a list of commands with aligned descriptions"""
    lines = []
    for cmd in commands:
        name = cmd['name']
        desc = clean_description(cmd['description'])
        # Pad name to align descriptions
        padding = ' ' * (max_name_len - len(name))
        lines.append(f"  {GREEN}{name}{NC}{padding}{desc}")
    return '\n'.join(lines)


def get_help_data() -> dict:
    """Get help data from help_generator.py"""
    try:
        # Try to find help_generator.py relative to this file
        # Works for both development (repository) and installed (PyPI) scenarios
        help_gen = Path(__file__).parent / "help_generator.py"

        if not help_gen.exists():
            # Fallback for development structure
            cli_root = Path(__file__).parent.parent.parent.parent
            help_gen = cli_root / "src" / "cli" / "core" / "help_generator.py"

        result = subprocess.run(
            [sys.executable, str(help_gen)],
            capture_output=True,
            text=True,
            check=True
        )

        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error generating help data: {e}", file=sys.stderr)
        sys.exit(1)


def format_comprehensive_help():
    """Format and print comprehensive help"""
    data = get_help_data()

    core_commands = data.get('core_commands', [])
    management_commands = data.get('management_commands', [])
    utility_commands = data.get('utility_commands', [])

    # Calculate max name length for alignment
    all_commands = core_commands + management_commands + utility_commands
    max_name_len = max(len(cmd['name']) for cmd in all_commands) + 2

    # Print header
    print(f"{CYAN}Rediacc CLI - Distributed Infrastructure Management{NC}\n")
    print(f"Usage:  rediacc [OPTIONS] COMMAND\n")

    # Print Core Commands
    if core_commands:
        print(f"{BLUE}Core Commands:{NC}")
        print(format_command_list(core_commands, max_name_len))
        print()

    # Print Management Commands
    if management_commands:
        print(f"{BLUE}Management Commands (via 'rediacc cli'):{NC}")
        print(format_command_list(management_commands, max_name_len))
        print()

    # Print Utility Commands
    if utility_commands:
        print(f"{BLUE}Utility Commands:{NC}")
        print(format_command_list(utility_commands, max_name_len))
        print()

    # Print footer
    print(f"Run '{YELLOW}rediacc COMMAND --help{NC}' for more information on a command.")
    print(f"Run '{YELLOW}rediacc cli COMMAND --help{NC}' for management command details.\n")
    print(f"Documentation: {CYAN}https://docs.rediacc.com/cli{NC}")


def main():
    """Main entry point"""
    try:
        format_comprehensive_help()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
