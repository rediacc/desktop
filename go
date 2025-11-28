#!/bin/bash

# Exit on error
set -e

# Required environment variables:
# - SYSTEM_HTTP_PORT: Middleware API port (default: 443)
# - SYSTEM_API_URL: Full API URL (default: https://www.rediacc.com/api)
# Optional environment variables:
# - TAG: Version tag for builds (default: dev)

# Root directory
ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MONOREPO_DIR="$( cd "$ROOT_DIR/.." && pwd )"

# Source parent .env file if it exists
if [ -f "$MONOREPO_DIR/.env" ]; then
    echo "📁 Loading environment from $MONOREPO_DIR/.env"
    set -a  # automatically export all variables
    source "$MONOREPO_DIR/.env"
    set +a  # turn off automatic export
fi

# Function to get latest git tag
get_latest_git_tag() {
    git tag -l 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null | sort -V | tail -1
}

# Use TAG environment variable if provided, otherwise try git tag, then date-based version
if [ -n "$TAG" ] && [ "$TAG" != "latest" ] && [ "$TAG" != "dev" ]; then
    export REDIACC_VERSION="$TAG"
else
    # Try to get version from git tags
    GIT_TAG=$(get_latest_git_tag)
    if [ -n "$GIT_TAG" ]; then
        # Strip 'v' prefix for consistency
        export REDIACC_VERSION="${GIT_TAG#v}"
        echo "📦 Using git tag version: $GIT_TAG (version: $REDIACC_VERSION)"
    else
        export REDIACC_VERSION="dev-$(date +%Y%m%d.%H%M%S)"
        echo "📦 No git tags found, using dev version: $REDIACC_VERSION"
    fi
fi

# Function to check required environment variables
check_required_env() {
    # These environment variables are optional - Python code has defaults
    # SYSTEM_HTTP_PORT defaults to 443
    # SYSTEM_API_URL defaults to https://www.rediacc.com/api
    
    if [ -z "$SYSTEM_HTTP_PORT" ]; then
        echo "ℹ️  SYSTEM_HTTP_PORT not set, using default: 443"
    else
        echo "✅ SYSTEM_HTTP_PORT set to: $SYSTEM_HTTP_PORT"
    fi
    
    if [ -z "$SYSTEM_API_URL" ]; then
        echo "ℹ️  SYSTEM_API_URL not set, using default: https://www.rediacc.com/api"
    else
        echo "✅ SYSTEM_API_URL set to: $SYSTEM_API_URL"
    fi
}

# Note: Environment variables should be set externally
# Default values are built into the Python applications

# Check if required environment variables are set after loading
check_required_env

# Source shared utilities if available
if [ -f "$MONOREPO_DIR/_scripts/_shared.sh" ]; then
    source "$MONOREPO_DIR/_scripts/_shared.sh"
else
    # Define minimal functions needed
    _get_current_arch() {
        local arch=$(uname -m)
        case "$arch" in
            x86_64|amd64)
                echo "amd64"
                ;;
            aarch64|arm64)
                echo "arm64"
                ;;
            *)
                echo "$arch"
                ;;
        esac
    }
fi

# Function to find Python
find_python() {
    # Check if we're in MSYS2 and should use MinGW64 Python
    if [ -n "$MSYSTEM" ] && [ -x "/mingw64/bin/python3" ]; then
        echo "/mingw64/bin/python3"
        return 0
    fi
    
    # Try different Python commands in order of preference
    for cmd in python3 python; do
        if command -v "$cmd" &> /dev/null; then
            if "$cmd" --version 2>&1 | grep -q "Python [0-9]"; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# Get Python command
PYTHON_CMD=$(find_python || echo "python3")

# Function to install host system dependencies
function host_setup() {
    echo "Setting up host system for CLI development..."
    
    # Detect if we're in a codespace environment
    local is_codespace=false
    if [ "${CODESPACES:-}" = "true" ] || [ -d "/workspaces" ]; then
        is_codespace=true
        echo "Detected GitHub Codespaces environment"
    fi
    
    # Check if sudo is available
    if ! command -v sudo &> /dev/null; then
        echo "❌ sudo is not available. Please install required packages manually:"
        echo "  - python3 python3-pip python3-venv"
        echo "  - python3-pytest python3-iniconfig python3-pluggy"
        echo "  - python3-tk xvfb"
        echo "  - rsync openssh-client curl jq"
        exit 1
    fi
    
    echo "Adding NOPASSWD for $USER (if not already set)..."
    if ! sudo -n true 2>/dev/null; then
        echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/$USER
    fi
    
    echo "Updating package list..."
    sudo apt-get update
    
    echo "Installing core Python packages..."
    sudo apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev
    
    echo "Installing Python testing packages..."
    sudo apt-get install -y \
        python3-pytest \
        python3-iniconfig \
        python3-pluggy \
        python3-dotenv
    
    echo "Installing desktop application testing dependencies..."
    sudo apt-get install -y \
        python3-tk \
        xvfb \
        x11-utils \
        xfonts-base \
        xfonts-75dpi \
        xfonts-100dpi
    
    echo "Installing CLI utilities..."
    sudo apt-get install -y \
        rsync \
        openssh-client \
        curl \
        jq \
        git

    # Only install Docker in native environments
    if [ "$is_codespace" = false ]; then
        if ! command -v docker &> /dev/null; then
            echo "Installing Docker..."
            sudo apt-get install -y docker.io docker-compose
            sudo usermod -aG docker $USER
            echo "You may need to log out and back in for Docker group membership to take effect"
        else
            echo "Docker is already installed"
        fi
    else
        echo "Docker is pre-installed in codespace environment"
    fi
    
    echo ""
    echo "✅ Host setup complete!"
    echo "You can now run: ./go setup"
}

# Function to setup development environment
function setup() {
    echo "Setting up CLI development environment..."
    
    # Check Python
    if ! command -v "$PYTHON_CMD" &> /dev/null; then
        echo "❌ Python is not installed"
        echo "Please install Python 3.7 or later"
        exit 1
    else
        python_version=$("$PYTHON_CMD" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        echo "✅ Python $python_version found ($PYTHON_CMD)"
    fi
    
    # Check rsync
    if ! command -v rsync &> /dev/null; then
        echo "⚠️  rsync not found"
        echo "Install rsync for file synchronization support:"
        echo "  Ubuntu/Debian: sudo apt-get install rsync"
        echo "  macOS: brew install rsync"
    else
        echo "✅ rsync found"
    fi
    
    # Check SSH
    if ! command -v ssh &> /dev/null; then
        echo "⚠️  SSH not found"
        echo "SSH is required for terminal access"
    else
        echo "✅ SSH found"
    fi
    
    # Install Python dependencies
    if [ -f "$ROOT_DIR/requirements.txt" ]; then
        echo "Installing Python dependencies..."
        "$PYTHON_CMD" -m pip install -r "$ROOT_DIR/requirements.txt"
        echo "✅ Python dependencies installed"
    fi
    
    # Check configuration
    echo "✅ Configuration uses built-in defaults (can be overridden with environment variables)"
    
    # Check middleware connectivity
    API_URL="${SYSTEM_API_URL:-https://www.rediacc.com/api}"
    if curl -s "$API_URL" > /dev/null 2>&1; then
        echo "✅ Middleware API is accessible at $API_URL"
    else
        echo "⚠️  Middleware API is not accessible at $API_URL"
        echo "Start it with: cd ../middleware && ./go start"
    fi
    
    echo ""
    echo "✅ Development environment setup complete!"
    echo "You can now run: ./go dev"
}

# Function to run CLI in development mode
function dev() {
    echo "Starting Rediacc CLI in development mode..."
    
    # Run the main CLI
    "$PYTHON_CMD" "$ROOT_DIR/src/cli/commands/cli_main.py" "$@"
}

# Function to run tests
function test() {
    echo "Running CLI tests..."
    
    cd "$ROOT_DIR"
    
    # Check if specific test type is requested
    local test_type="${1:-all}"
    shift || true
    
    case "$test_type" in
        desktop)
            # Run desktop application tests only
            if [ -f "tests/gui/run_gui_tests.py" ]; then
                echo "Running desktop application test suite..."
                "$PYTHON_CMD" tests/gui/run_gui_tests.py "$@"
            else
                echo "⚠️  No desktop tests found at tests/gui/run_gui_tests.py"
            fi
            ;;
        api)
            # Run API tests only
            if [ -f "tests/run_tests.py" ]; then
                echo "Running API test suite..."
                "$PYTHON_CMD" tests/run_tests.py "$@"
            else
                echo "⚠️  No API tests found at tests/run_tests.py"
            fi
            ;;
        all)
            # Run all tests
            local exit_code=0
            
            # Run API tests
            if [ -f "tests/run_tests.py" ]; then
                echo "Running API test suite..."
                "$PYTHON_CMD" tests/run_tests.py "$@"
                exit_code=$?
            fi
            
            # Run desktop tests if display is available or in CI
            if [ -f "tests/gui/run_gui_tests.py" ]; then
                echo ""
                echo "Running desktop application test suite..."
                "$PYTHON_CMD" tests/gui/run_gui_tests.py --headless "$@"
                local desktop_exit=$?
                if [ $desktop_exit -ne 0 ]; then
                    exit_code=$desktop_exit
                fi
            fi
            
            return $exit_code
            ;;
        *)
            # Assume it's a specific test file
            if [ -f "tests/run_tests.py" ]; then
                echo "Running Python test suite..."
                "$PYTHON_CMD" tests/run_tests.py "$test_type" "$@"
            else
                echo "⚠️  No tests found at tests/run_tests.py"
            fi
            ;;
    esac
}

# Function to run linting
function lint() {
    echo "Running code linting..."
    
    # Check if pylint is installed
    if ! "$PYTHON_CMD" -m pylint --version &> /dev/null; then
        echo "Installing pylint..."
        "$PYTHON_CMD" -m pip install pylint
    fi
    
    # Run pylint on source files
    echo "Running pylint..."
    "$PYTHON_CMD" -m pylint src/cli/*.py || true
    
    # Check if black is installed
    if ! "$PYTHON_CMD" -m black --version &> /dev/null; then
        echo "Installing black..."
        "$PYTHON_CMD" -m pip install black
    fi
    
    # Run black in check mode
    echo "Running black formatter check..."
    "$PYTHON_CMD" -m black --check src/cli/ || true
}

# Function to build Docker image
function build() {
    echo "Building Rediacc CLI Docker image..."
    
    # Default to using cache
    local build_args=""
    
    # Parse arguments
    for arg in "$@"; do
        case $arg in
            --no-cache)
                build_args="$build_args --no-cache"
                ;;
            --cache)
                # Cache is now default, kept for compatibility
                ;;
            *)
                build_args="$build_args $arg"
                ;;
        esac
    done
    
    # Use the existing build script
    "$ROOT_DIR/scripts/build-docker.sh" $build_args --version="$REDIACC_VERSION"
}

# Function to build Docker image (alias for consistency)
function docker_build() {
    build "$@"
}

# Function to run CLI in Docker
function docker_run() {
    echo "Running Rediacc CLI in Docker..."
    
    # Check if image exists
    if ! docker images | grep -q "rediacc/cli.*latest"; then
        echo "Docker image not found. Building..."
        docker_build
    fi
    
    # Run with proper mounts
    docker run -it --rm \
        -v "$ROOT_DIR/.config:/home/rediacc/.config" \
        -v "$HOME/.ssh:/home/rediacc/.ssh:ro" \
        -v "$PWD:/workspace" \
        -w /workspace \
        --env-file "$ROOT_DIR/.env" \
        rediacc/cli:latest \
        "$@"
}

# Function to create release
function release() {
    echo "Creating CLI release..."
    
    # Clean up bin directory
    echo "Cleaning up bin directory..."
    rm -rf "$ROOT_DIR/bin"
    mkdir -p "$ROOT_DIR/bin"
    
    # Build Docker image first
    echo "Building Docker image..."
    docker_build
    
    # Create version info file
    echo "{
  \"version\": \"${REDIACC_VERSION}\",
  \"buildDate\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
  \"gitCommit\": \"$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')\"
}" > "$ROOT_DIR/bin/version.json"
    
    # Create a release archive of Python scripts
    echo "Creating release archive..."
    # Build list of files to include (only if they exist)
    local tar_files=()
    for file in src/ rediacc rediacc.bat .env.example requirements.txt README.md docs/; do
        if [ -e "$ROOT_DIR/$file" ]; then
            tar_files+=("$file")
        fi
    done
    
    tar -czf "$ROOT_DIR/bin/rediacc-${REDIACC_VERSION}.tar.gz" \
        -C "$ROOT_DIR" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        --exclude=".git" \
        --exclude="bin" \
        --exclude=".config" \
        "${tar_files[@]}"
    
    echo ""
    echo "Release created successfully!"
    echo "Version: ${REDIACC_VERSION}"
    echo "Files created in: $ROOT_DIR/bin"
    
    # Copy to root bin/cli for distribution
    echo "Copying to root bin/cli directory..."
    ROOT_BIN_CLI="$MONOREPO_DIR/bin/cli"
    mkdir -p "$ROOT_BIN_CLI"
    
    # Clean existing files
    rm -rf "$ROOT_BIN_CLI"/*
    
    # Copy release files
    cp -r "$ROOT_DIR/bin/"* "$ROOT_BIN_CLI/"
    
    # Also save Docker image tag info
    echo "rediacc/cli:${REDIACC_VERSION}" > "$ROOT_BIN_CLI/docker-image.txt"
    
    echo "Files also copied to: $ROOT_BIN_CLI"
}

# Function to clean build artifacts
function clean() {
    echo "Cleaning build artifacts..."
    
    # Remove Python cache
    find "$ROOT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$ROOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    
    # Remove build directories
    rm -rf "$ROOT_DIR/bin"
    rm -rf "$ROOT_DIR/build"
    rm -rf "$ROOT_DIR/dist"
    
    # Remove .dockerbuild marker
    rm -f "$ROOT_DIR/.dockerbuild"
    
    echo "✅ Build artifacts cleaned"
}

# Function to check status
function status() {
    echo "Rediacc CLI Status:"
    echo "=================="
    
    # Check Python
    if command -v "$PYTHON_CMD" &> /dev/null; then
        python_version=$("$PYTHON_CMD" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        echo "✅ Python $python_version available"
    else
        echo "❌ Python not found"
    fi
    
    # Check configuration
    if [ -f "$ROOT_DIR/.env" ]; then
        echo "✅ Configuration file exists"
    else
        echo "❌ No configuration file"
    fi
    
    # Check middleware connectivity
    API_URL="${SYSTEM_API_URL:-https://www.rediacc.com/api}"
    if curl -s "$API_URL" > /dev/null 2>&1; then
        echo "✅ Middleware API is accessible"
    else
        echo "❌ Middleware API is not accessible"
    fi
    
    # Check Docker
    if command -v docker &> /dev/null; then
        if docker images | grep -q "rediacc/cli"; then
            echo "✅ Docker image exists: rediacc/cli"
        else
            echo "⚠️  Docker image not built"
        fi
    else
        echo "❌ Docker not available"
    fi
    
    # Show version
    echo "📦 Version: ${REDIACC_VERSION}"
}

# Function to show version
function version() {
    echo "Rediacc CLI ${REDIACC_VERSION}"
    
    # Show git commit if available
    if git_hash=$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null); then
        echo "Git commit: $git_hash"
    fi
}

# Help message
function show_help() {
    echo "Usage: ./go [COMMAND]"
    echo ""
    echo "Setup Commands:"
    echo "  host_setup    Install system dependencies (apt packages)"
    echo "  setup         Setup development environment"
    echo ""
    echo "Development Commands:"
    echo "  dev           Run CLI in development mode"
    echo "  test [type]   Run test suite (all|api|desktop) - default: all"
    echo "  lint          Run code linting"
    echo ""
    echo "Build Commands:"
    echo "  build         Build Docker image"
    echo "  docker-build  Build Docker image (alias)"
    echo "  docker-run    Run CLI in Docker container"
    echo "  release       Create release artifacts"
    echo ""
    echo "Utility Commands:"
    echo "  clean         Clean build artifacts"
    echo "  status        Check CLI environment status"
    echo "  version       Show version information"
    echo "  help          Show this help message"
    echo ""
    echo "Quick Start:"
    echo "  ./go host_setup  # Install system dependencies"
    echo "  ./go setup       # Setup environment"
    echo "  ./go dev         # Run CLI"
    echo ""
    echo "Docker Usage:"
    echo "  ./go docker-build          # Build image"
    echo "  ./go docker-run help       # Run CLI in Docker"
    echo "  ./go docker-run login      # Login via Docker"
}

# Main function to handle commands
main() {
    case "$1" in
        host_setup)
            host_setup
            ;;
        setup)
            setup
            ;;
        dev)
            shift
            dev "$@"
            ;;
        test)
            shift
            test "$@"
            ;;
        lint)
            lint
            ;;
        build)
            shift
            build "$@"
            ;;
        docker-build)
            shift
            docker_build "$@"
            ;;
        docker-run)
            shift
            docker_run "$@"
            ;;
        release)
            release
            ;;
        clean)
            clean
            ;;
        status)
            status
            ;;
        version)
            version
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            show_help
            exit 1
            ;;
    esac
}

# Execute main function if run directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && main "$@"