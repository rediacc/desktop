#!/usr/bin/env python3
"""
Rediacc CLI Compose - Docker Compose-like management for Rediaccfile
Provides prep/up/down commands for managing repository environments
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.shared import colorize, add_common_arguments, error_exit
from cli.core.config import setup_logging, get_logger
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry


def validate_environment(logger) -> bool:
    """
    Validate that DOCKER_HOST environment variable is set.
    This indicates we're running inside a Rediacc repository environment.

    Returns:
        bool: True if environment is valid, False otherwise
    """
    docker_host = os.environ.get('DOCKER_HOST', '')

    logger.debug(f"[validate_environment] DOCKER_HOST: {docker_host}")

    if not docker_host:
        print(colorize("Error: This command requires a Rediacc repository environment.", 'RED'))
        print()
        print("Please run inside a repository terminal:")
        print(colorize("  rediacc term --machine <name> --repository <name>", 'CYAN'))
        print()
        print("The DOCKER_HOST environment variable must be set.")
        return False

    logger.debug(f"[validate_environment] Environment validation passed")
    return True


def find_rediaccfile(logger) -> Optional[Path]:
    """
    Find Rediaccfile in the current working directory.

    Returns:
        Optional[Path]: Path to Rediaccfile if found, None otherwise
    """
    cwd = Path.cwd()
    rediaccfile = cwd / 'Rediaccfile'

    logger.debug(f"[find_rediaccfile] Current directory: {cwd}")
    logger.debug(f"[find_rediaccfile] Looking for: {rediaccfile}")

    if not rediaccfile.exists():
        print(colorize("Error: No Rediaccfile found in current directory.", 'RED'))
        print()
        print(f"Current directory: {colorize(str(cwd), 'CYAN')}")
        print()
        print("Ensure you are in a repository root containing a Rediaccfile.")
        return None

    if not rediaccfile.is_file():
        print(colorize("Error: Rediaccfile exists but is not a file.", 'RED'))
        return None

    if not os.access(rediaccfile, os.R_OK):
        print(colorize("Error: Rediaccfile is not readable.", 'RED'))
        return None

    logger.debug(f"[find_rediaccfile] Rediaccfile found and readable")
    return rediaccfile


def execute_function(function_name: str, rediaccfile: Path, logger, verbose: bool = False) -> int:
    """
    Execute a function (prep/up/down) from the Rediaccfile.

    Args:
        function_name: Name of the function to execute (prep, up, or down)
        rediaccfile: Path to the Rediaccfile
        logger: Logger instance
        verbose: Whether to show verbose output

    Returns:
        int: Exit code from the function execution
    """
    logger.debug(f"[execute_function] Executing function: {function_name}")
    logger.debug(f"[execute_function] Rediaccfile: {rediaccfile}")
    logger.debug(f"[execute_function] Working directory: {rediaccfile.parent}")

    # Build the bash command to source Rediaccfile and execute function
    bash_command = f'source ./Rediaccfile && {function_name}'

    logger.debug(f"[execute_function] Bash command: {bash_command}")

    # Print header
    print(colorize(f"=== Running '{function_name}' from Rediaccfile ===", 'HEADER'))
    print()

    try:
        # Execute the command
        # Use stdout/stderr passthrough for interactive output
        result = subprocess.run(
            ['bash', '-c', bash_command],
            cwd=rediaccfile.parent,
            check=False,  # Don't raise exception, we'll handle exit codes
        )

        logger.debug(f"[execute_function] Exit code: {result.returncode}")

        print()
        if result.returncode == 0:
            print(colorize(f"✓ Function '{function_name}' completed successfully", 'GREEN'))
        else:
            print(colorize(f"✗ Function '{function_name}' failed with exit code {result.returncode}", 'RED'))

        return result.returncode

    except FileNotFoundError:
        print(colorize("Error: bash command not found.", 'RED'))
        logger.error("[execute_function] bash not found in PATH")
        return 127
    except Exception as e:
        print(colorize(f"Error executing function: {e}", 'RED'))
        logger.error(f"[execute_function] Exception: {e}")
        return 1


def validate_function_exists(function_name: str, rediaccfile: Path, logger) -> bool:
    """
    Validate that the requested function exists in the Rediaccfile.

    Args:
        function_name: Name of the function to check
        rediaccfile: Path to the Rediaccfile
        logger: Logger instance

    Returns:
        bool: True if function exists, False otherwise
    """
    logger.debug(f"[validate_function_exists] Checking for function: {function_name}")

    try:
        # Check if function is defined in the Rediaccfile
        bash_command = f'source ./Rediaccfile && declare -f {function_name} > /dev/null'
        result = subprocess.run(
            ['bash', '-c', bash_command],
            cwd=rediaccfile.parent,
            check=False,
            capture_output=True
        )

        if result.returncode != 0:
            print(colorize(f"Error: Function '{function_name}' not found in Rediaccfile.", 'RED'))
            print()
            print("Valid functions are: prep, up, down")
            logger.debug(f"[validate_function_exists] Function not found")
            return False

        logger.debug(f"[validate_function_exists] Function exists")
        return True

    except Exception as e:
        logger.error(f"[validate_function_exists] Exception: {e}")
        return False


@track_command('compose')
def main():
    """Main entry point for rediacc compose command"""
    parser = argparse.ArgumentParser(
        prog='rediacc compose',
        description='Rediacc CLI Compose - Docker Compose-like management for Rediaccfile',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  rediacc compose prep    Pull Docker images and prepare directories
  rediacc compose up      Start services with docker compose up -d
  rediacc compose down    Stop services with docker compose down -v

Note: This command must be run inside a Rediacc repository environment.
Use 'rediacc term --machine <name> --repository <name>' to connect first.
        """
    )

    parser.add_argument(
        'action',
        choices=['prep', 'up', 'down'],
        help='Action to perform: prep (prepare), up (start), or down (stop)'
    )

    # Add only verbose argument (no token/team/machine/repository needed)
    # Note: --version is only available at root level (rediacc --version)
    add_common_arguments(parser, include_args=['verbose'])

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose if hasattr(args, 'verbose') else False)
    logger = get_logger(__name__)

    # Initialize telemetry
    initialize_telemetry()

    try:
        logger.info(f"[compose] Starting compose command: {args.action}")

        # Validate environment (DOCKER_HOST must be set)
        if not validate_environment(logger):
            return 1

        # Find Rediaccfile in current directory
        rediaccfile = find_rediaccfile(logger)
        if not rediaccfile:
            return 1

        # Validate that the requested function exists
        if not validate_function_exists(args.action, rediaccfile, logger):
            return 1

        # Execute the function
        exit_code = execute_function(
            args.action,
            rediaccfile,
            logger,
            verbose=args.verbose if hasattr(args, 'verbose') else False
        )

        logger.info(f"[compose] Command completed with exit code: {exit_code}")
        return exit_code

    except KeyboardInterrupt:
        print()
        print(colorize("Operation cancelled by user", 'YELLOW'))
        logger.info("[compose] Cancelled by user")
        return 130
    except Exception as e:
        print(colorize(f"Unexpected error: {e}", 'RED'))
        logger.error(f"[compose] Unexpected error: {e}", exc_info=True)
        return 1
    finally:
        shutdown_telemetry()


if __name__ == '__main__':
    sys.exit(main())
