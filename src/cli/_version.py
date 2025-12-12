"""
Version information for Rediacc CLI package.

This file is the single source of truth for the package version.
It is imported by setup.py and can be updated programmatically
during the build process.
"""

__version__ = "0.2.117"

def _parse_version(version_string):
    """Parse version string, handling development versions gracefully."""
    if version_string.startswith('dev-') or version_string == 'dev':
        # For development versions, return a sensible default
        return (0, 0, 0, 'dev')

    # Handle semantic versions (e.g., "1.2.3", "1.2.3a1", "1.2.3.dev0")
    try:
        # Split by dots and take only numeric parts
        parts = version_string.split('.')
        numeric_parts = []

        for part in parts:
            # Extract numeric portion from each part (handles "3a1" -> "3")
            numeric_part = ""
            for char in part:
                if char.isdigit():
                    numeric_part += char
                else:
                    break  # Stop at first non-digit

            if numeric_part:
                numeric_parts.append(int(numeric_part))
            else:
                break  # Stop if we can't extract a number

        # Ensure we have at least 3 parts (major.minor.patch)
        while len(numeric_parts) < 3:
            numeric_parts.append(0)

        return tuple(numeric_parts[:3])  # Return only major.minor.patch

    except (ValueError, AttributeError):
        # Fallback for any parsing errors
        return (0, 0, 0)

__version_info__ = _parse_version(__version__)