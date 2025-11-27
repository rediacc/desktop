#!/usr/bin/env python3
"""
Build script for preparing Rediacc CLI distribution packages.

This script:
1. Updates version numbers (can extract from git tags)
2. Builds the distribution packages (wheel and sdist)
3. Validates the package

Packages are served from the nginx image at /pypi/ endpoint.
"""

import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path
import re

def get_latest_git_tag():
    """Get the latest version tag from git - prefers local repo tags."""
    try:
        script_dir = Path(__file__).parent.parent.absolute()

        # Always try current directory first (standalone or submodule)
        git_dir = script_dir

        result = subprocess.run(
            ["git", "tag", "-l", "v[0-9]*.[0-9]*.[0-9]*"],
            cwd=str(git_dir),
            capture_output=True,
            text=True,
            check=True
        )
        tags = result.stdout.strip().split('\n')

        # If no tags found AND we're in a submodule, try parent directory
        if (not tags or tags == ['']):
            git_file = script_dir / ".git"
            if git_file.exists() and git_file.is_file():
                # We're in a submodule, try parent directory as fallback
                git_dir = script_dir.parent
                result = subprocess.run(
                    ["git", "tag", "-l", "v[0-9]*.[0-9]*.[0-9]*"],
                    cwd=str(git_dir),
                    capture_output=True,
                    text=True,
                    check=True
                )
                tags = result.stdout.strip().split('\n')

        if not tags or tags == ['']:
            return None

        # Sort tags using version sort
        sorted_tags = subprocess.run(
            ["sort", "-V"],
            input='\n'.join(tags),
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip().split('\n') if tags else []

        return sorted_tags[-1] if sorted_tags else None
    except subprocess.CalledProcessError:
        return None

def get_next_version(version_type="patch"):
    """Get the next version by incrementing the latest git tag."""
    latest = get_latest_git_tag()
    
    if not latest:
        return "0.1.0"
    
    # Remove 'v' prefix if present
    version = latest.lstrip('v')
    
    # Parse version
    parts = version.split('.')
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2].split('-')[0])
    
    # Increment based on type
    if version_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif version_type == "minor":
        minor += 1
        patch = 0
    else:  # patch
        patch += 1
    
    return f"{major}.{minor}.{patch}"

def strip_v_prefix(version):
    """Strip 'v' prefix from version for PyPI compatibility."""
    return version.lstrip('v')

def update_version(version_file, new_version):
    """Update the version in _version.py file."""
    version_path = Path(version_file)
    content = version_path.read_text()
    
    # Replace the version string
    new_content = re.sub(
        r'__version__ = "[^"]*"',
        f'__version__ = "{new_version}"',
        content
    )
    
    version_path.write_text(new_content)
    print(f"✓ Updated version to {new_version} in {version_file}")

def clean_build_dirs(base_dir):
    """Remove previous build directories."""
    dirs_to_clean = ['build', 'dist', '*.egg-info', 'src/*.egg-info', '.build_venv']
    
    for pattern in dirs_to_clean:
        for path in Path(base_dir).glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
                print(f"✓ Removed {path}")

def build_package(base_dir):
    """Build the distribution packages."""
    print("\n📦 Building distribution packages...")
    
    # Try to use virtual environment, but fall back to system Python with --break-system-packages if needed
    venv_dir = base_dir / ".build_venv"
    use_venv = True
    venv_python = None
    
    if not venv_dir.exists():
        print("Attempting to create virtual environment for build...")
        venv_result = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True, text=True)
        if venv_result.returncode != 0:
            print("⚠️  Could not create virtual environment, using system Python with isolation")
            print("    (Install python3-venv package for better isolation)")
            use_venv = False
    
    if use_venv:
        # Use the virtual environment's Python
        venv_python = venv_dir / "bin" / "python" if os.name != 'nt' else venv_dir / "Scripts" / "python.exe"
        if venv_python.exists():
            # Ensure build tool is installed in the virtual environment
            subprocess.run([str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip", "build", "setuptools", "wheel"], check=True)
            python_cmd = [str(venv_python)]
        else:
            use_venv = False
    
    if not use_venv:
        # Fall back to system Python with --break-system-packages
        # First ensure build is installed
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--break-system-packages", "build", "setuptools", "wheel"], check=False)
        python_cmd = [sys.executable]
    
    # Build the package using the build module directly
    result = subprocess.run(
        python_cmd + ["-m", "build"],
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"✗ Build failed:\n{result.stderr}")
        return False
    
    print("✓ Built source distribution (sdist)")
    print("✓ Built wheel distribution (bdist_wheel)")
    return True

def validate_package(base_dir):
    """Validate the built package."""
    print("\n🔍 Validating package...")
    
    # Try to use the virtual environment if it exists
    venv_dir = base_dir / ".build_venv"
    venv_python = venv_dir / "bin" / "python" if os.name != 'nt' else venv_dir / "Scripts" / "python.exe"
    
    # Check if venv exists and has pip
    use_venv = False
    if venv_python.exists():
        # Check if pip works in the venv
        pip_check = subprocess.run([str(venv_python), "-m", "pip", "--version"], capture_output=True)
        if pip_check.returncode == 0:
            use_venv = True
            # Ensure twine is installed in the virtual environment (use working version)
            subprocess.run([str(venv_python), "-m", "pip", "install", "--quiet", "twine==6.0.1", "check-wheel-contents"], check=True)
            python_cmd = [str(venv_python)]
    
    if not use_venv:
        # Fall back to system Python with --break-system-packages
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--break-system-packages", "twine==6.0.1", "check-wheel-contents"], check=False)
        python_cmd = [sys.executable]
    
    # Check the distribution - expand glob manually
    import glob
    dist_files = glob.glob(str(base_dir / "dist" / "*"))
    if not dist_files:
        print("✗ No distribution files found")
        return False
    
    # First, check with twine
    result = subprocess.run(
        python_cmd + ["-m", "twine", "check"] + dist_files,
        cwd=base_dir,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        # Check if the only issue is the deprecated license-file field
        output = (result.stdout + result.stderr).lower()
        
        # Check for license-file error specifically
        if "license-file" in output and "invalid distribution" in output:
            # Count how many different errors there are
            error_count = 0
            for line in (result.stdout + result.stderr).split('\n'):
                if 'ERROR' in line:
                    error_count += 1
            
            # If there's only one ERROR line and it's about license-file, we can ignore it
            if error_count == 1:
                print("⚠️  Note: The 'license-file' field is deprecated but this won't prevent PyPI upload.")
                print("✓ Package validation passed (ignoring deprecated field warning)")
                return True
        
        # There are real errors
        print(f"✗ Validation failed:")
        if result.stderr:
            print(f"Error: {result.stderr}")
        if result.stdout:
            print(f"Output: {result.stdout}")
        return False
    
    print("✓ Package validation passed")
    return True

def main():
    parser = argparse.ArgumentParser(description="Build Rediacc CLI distribution packages")
    parser.add_argument("version", nargs="?", help="Version number (e.g., 0.1.0, v0.1.0, or 'auto' for git tag)")
    parser.add_argument("--skip-clean", action="store_true", help="Skip cleaning build directories")
    parser.add_argument("--skip-validation", action="store_true", help="Skip package validation")
    parser.add_argument("--increment", choices=["major", "minor", "patch"], default="patch",
                        help="Version increment type when using 'auto' (default: patch)")
    parser.add_argument("--use-git-tag", action="store_true", help="Use latest git tag as version")
    
    args = parser.parse_args()
    
    # Determine the base directory (cli folder)
    base_dir = Path(__file__).parent.parent.absolute()
    version_file = base_dir / "src" / "cli" / "_version.py"
    
    # Determine version
    if args.use_git_tag:
        version = get_latest_git_tag()
        if not version:
            print("❌ No git tags found!")
            sys.exit(1)
        version = strip_v_prefix(version)
        print(f"📦 Using latest git tag: v{version}")
    elif args.version == "auto":
        version = get_next_version(args.increment)
        print(f"🔄 Auto-incrementing {args.increment} version to: {version}")
    elif args.version:
        version = strip_v_prefix(args.version)
    else:
        # If no version specified, try to get from git tag
        git_tag = get_latest_git_tag()
        if git_tag:
            version = strip_v_prefix(git_tag)
            print(f"📦 Using latest git tag: {git_tag} (PyPI version: {version})")
        else:
            print("❌ No version specified and no git tags found!")
            print("Usage: build-pypi.py <version> or build-pypi.py --use-git-tag")
            sys.exit(1)
    
    print(f"🔧 Building Rediacc CLI v{version}")
    print(f"📂 Working directory: {base_dir}")
    
    # Step 1: Clean previous builds
    if not args.skip_clean:
        clean_build_dirs(base_dir)
    
    # Step 2: Update version
    update_version(version_file, version)
    
    # Step 3: Build the package
    if not build_package(base_dir):
        print("\n❌ Build failed!")
        sys.exit(1)
    
    # Step 4: Validate the package
    if not args.skip_validation:
        if not validate_package(base_dir):
            print("\n❌ Validation failed!")
            sys.exit(1)

    print("\n✅ Build complete!")
    
    # Show the built files
    dist_dir = base_dir / "dist"
    if dist_dir.exists():
        print("\n📦 Built packages:")
        for file in dist_dir.iterdir():
            size = file.stat().st_size / 1024  # KB
            print(f"  - {file.name} ({size:.1f} KB)")

if __name__ == "__main__":
    main()