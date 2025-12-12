#!/usr/bin/env python3
"""
Rediacc CLI Protocol - Manage rediacc:// protocol registration for browser integration
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli._version import __version__
from cli.core.shared import colorize
from cli.core.telemetry import track_command, initialize_telemetry, shutdown_telemetry

def handle_register(args):
    """Handle protocol registration"""
    from cli.core.protocol_handler import register_protocol, get_platform

    system_wide = hasattr(args, 'system_wide') and args.system_wide
    platform_name = get_platform()

    print(f"Registering rediacc:// protocol on {platform_name}...")
    if system_wide:
        print("Note: System-wide registration requires elevated privileges")

    success = register_protocol(force=False, system_wide=system_wide)
    if success:
        print(colorize("Successfully registered rediacc:// protocol for browser integration", 'GREEN'))
        if platform_name == "windows":
            print("You may need to restart your browser for changes to take effect")
        elif platform_name == "linux":
            print("Desktop entries have been updated. You may need to log out and back in for changes to take effect")
        return 0
    else:
        print(colorize("Failed to register rediacc:// protocol", 'RED'))
        return 1

def handle_unregister(args):
    """Handle protocol unregistration"""
    from cli.core.protocol_handler import unregister_protocol, get_platform

    system_wide = hasattr(args, 'system_wide') and args.system_wide
    platform_name = get_platform()

    print(f"Unregistering rediacc:// protocol from {platform_name}...")
    success = unregister_protocol(system_wide=system_wide)
    if success:
        print(colorize("Successfully unregistered rediacc:// protocol", 'GREEN'))
        return 0
    else:
        print(colorize("Failed to unregister rediacc:// protocol", 'RED'))
        return 1

def handle_status(args):
    """Handle protocol status check"""
    from cli.core.protocol_handler import get_protocol_status, get_install_instructions

    system_wide = hasattr(args, 'system_wide') and args.system_wide
    status = get_protocol_status(system_wide=system_wide)

    print(f"Protocol Registration Status:")
    print(f"  Platform: {status.get('platform', 'unknown')}")
    print(f"  Supported: {status.get('supported', False)}")

    if status.get('user_registered'):
        print(f"  User-level: {colorize('Registered', 'GREEN')}")
    else:
        print(f"  User-level: {colorize('Not registered', 'YELLOW')}")

    if status.get('system_registered'):
        print(f"  System-wide: {colorize('Registered', 'GREEN')}")
    else:
        print(f"  System-wide: {colorize('Not registered', 'YELLOW')}")

    if status.get('details'):
        print(f"  Details: {status['details']}")

    # Show installation instructions if not registered
    if not status.get('user_registered') and not status.get('system_registered'):
        instructions = get_install_instructions()
        if instructions:
            print(f"\nInstallation Instructions:")
            for instruction in instructions:
                print(f"  {instruction}")

    return 0

def handle_run(args):
    """Handle protocol URL (called by OS when clicking rediacc:// links or manually from command line)"""
    from cli.core.protocol_handler import handle_protocol_url

    if not hasattr(args, 'url') or not args.url:
        print(colorize("No URL provided. Usage: rediacc protocol run <rediacc://...>", 'RED'))
        return 1

    # Always use is_protocol_call=True for proper error display with wait
    # This is the primary entry point for OS protocol handler registration
    return handle_protocol_url(args.url, is_protocol_call=True)

@track_command('protocol')
def main():
    # Initialize telemetry
    initialize_telemetry()

    parser = argparse.ArgumentParser(
        prog='rediacc protocol',
        description='Rediacc CLI Protocol - Manage rediacc:// protocol registration for browser integration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Register protocol for browser integration:
    %(prog)s register
    %(prog)s register --system-wide

  Check registration status:
    %(prog)s status
    %(prog)s status --system-wide

  Unregister protocol:
    %(prog)s unregister
    %(prog)s unregister --system-wide

  Handle protocol URL from command line:
    %(prog)s run "rediacc://repo/open?team=Default&machine=server1&repository = webapp"

Protocol Registration:
  The rediacc:// protocol enables one-click access from the browser to CLI operations.

  User-level registration (default):
    - No elevated privileges required
    - Only works for the current user

  System-wide registration (--system-wide):
    - Requires elevated privileges (sudo/admin)
    - Works for all users on the system

  Platform support:
    - Windows: Registry-based registration
    - Linux: Desktop entry and XDG MIME registration
    - macOS: Launch Services registration
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Register subcommand
    register_parser = subparsers.add_parser('register', help='Register rediacc:// protocol for browser integration')
    register_parser.add_argument('--system-wide', action='store_true',
                                help='Install protocol system-wide (requires sudo on Linux/macOS, admin on Windows)')
    register_parser.set_defaults(func=handle_register)

    # Unregister subcommand
    unregister_parser = subparsers.add_parser('unregister', help='Unregister rediacc:// protocol')
    unregister_parser.add_argument('--system-wide', action='store_true',
                                  help='Unregister protocol system-wide (requires sudo on Linux/macOS, admin on Windows)')
    unregister_parser.set_defaults(func=handle_unregister)

    # Status subcommand
    status_parser = subparsers.add_parser('status', help='Show rediacc:// protocol registration status')
    status_parser.add_argument('--system-wide', action='store_true',
                              help='Check system-wide protocol registration status')
    status_parser.set_defaults(func=handle_status)

    # Run subcommand
    run_parser = subparsers.add_parser('run', help='Handle rediacc:// protocol URL from command line')
    run_parser.add_argument('url', help='The rediacc:// URL to handle')
    run_parser.set_defaults(func=handle_run)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        result = args.func(args)
        sys.exit(result if result is not None else 0)
    except Exception as e:
        print(colorize(f"Error handling protocol command: {e}", 'RED'))
        sys.exit(1)
    finally:
        # Shutdown telemetry
        shutdown_telemetry()

if __name__ == '__main__':
    main()
