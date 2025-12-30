# Configuration Guide

This guide covers configuration options for the Rediacc CLI tools.

## Configuration Files

### Main Configuration

Location: `~/.rediacc/config.json`

```json
{
  "token": "xx-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxxxxxxxxxx",
  "api_url": "https://www.rediacc.com",
  "default_team": "Production",
  "output_format": "table",
  "verify_ssl": true
}
```

### Environment Variables

Environment variables override configuration file settings:

```bash
# Authentication
export REDIACC_TOKEN="your-token-here"

# API endpoint
export SYSTEM_API_URL="https://api.custom.com"

# Default team
export REDIACC_DEFAULT_TEAM="Development"

# Output format
export REDIACC_OUTPUT_FORMAT="json"

# Verbose logging
export REDIACC_VERBOSE=1

# SSL verification (development only)
export REDIACC_VERIFY_SSL=0
```

### Command-Line Parameters

Command-line parameters have the highest priority:

```bash
# Override token
rediacc --token "temporary-token" list teams

# Override API URL
rediacc --api-url "https://staging-api.com" list teams

# Override output format
rediacc --output json list teams
```

## Priority Order

Configuration values are used in this priority order (highest to lowest):
1. Command-line parameters
2. Environment variables
3. Configuration file
4. Default values

## Managing Configuration

### View Configuration

```bash
# Show all configuration
rediacc config list

# Get specific value
rediacc config get default_team
rediacc config get api_url
```

### Set Configuration

```bash
# Set default team
rediacc config set default_team "Production"

# Set output format
rediacc config set output_format "json"

# Set custom API URL
rediacc config set api_url "https://api.organization.internal"
```

### Reset Configuration

```bash
# Remove specific setting (falls back to default)
rediacc config unset output_format

# Reset all configuration
rm ~/.rediacc/config.json
```

## Tool-Specific Configuration

### rediacc-sync

```bash
# Default exclusions
export REDIACC_SYNC_EXCLUDE=".git,node_modules,__pycache__"

# Default rsync options
export REDIACC_RSYNC_OPTS="-avz --progress"

# SSH options for development
export REDIACC_SSH_OPTS="-o StrictHostKeyChecking=no"
```

### rediacc-term

```bash
# Default SSH options
export REDIACC_TERM_SSH_OPTS="-o ServerAliveInterval=60"

# Terminal type
export REDIACC_TERM_TYPE="xterm-256color"

# Development mode by default
export REDIACC_DEV_MODE=1
```

## Advanced Configuration

### Multiple Profiles

Create different configuration files for different environments:

```bash
# Production configuration
cp ~/.rediacc/config.json ~/.rediacc/config.prod.json

# Development configuration  
cp ~/.rediacc/config.json ~/.rediacc/config.dev.json

# Use specific configuration
export REDIACC_CONFIG_PATH=~/.rediacc/config.dev.json
rediacc list teams
```

### Team-Specific Settings

```bash
# Create team-specific aliases
alias rediacc-prod='REDIACC_DEFAULT_TEAM=Production rediacc'
alias rediacc-dev='REDIACC_DEFAULT_TEAM=Development rediacc'
alias rediacc-staging='REDIACC_DEFAULT_TEAM=Staging rediacc'

# Use aliases
rediacc-prod list machines
rediacc-dev list repositories
```

### Custom Scripts

Create wrapper scripts for common configurations:

```bash
#!/bin/bash
# prod-cli.sh - Production CLI wrapper

export REDIACC_DEFAULT_TEAM="Production"
export REDIACC_OUTPUT_FORMAT="json"
export SYSTEM_API_URL="https://prod-api.organization.com"

exec rediacc "$@"
```

## Security Configuration

### Token Storage

```bash
# Secure token file permissions
chmod 600 ~/.rediacc/config.json

# Verify permissions
ls -la ~/.rediacc/config.json
# -rw------- 1 user user 256 Jan 1 12:00 config.json
```

### SSL/TLS Configuration

```bash
# Production - always verify SSL
export REDIACC_VERIFY_SSL=1

# Development - disable verification (not recommended)
export REDIACC_VERIFY_SSL=0

# Custom CA bundle
export REDIACC_CA_BUNDLE="/path/to/ca-bundle.crt"
```

### Proxy Configuration

```bash
# HTTP proxy
export HTTP_PROXY="http://proxy.organization.com:8080"
export HTTPS_PROXY="http://proxy.organization.com:8080"

# Proxy with authentication
export HTTPS_PROXY="http://user:pass@proxy.organization.com:8080"

# No proxy for internal
export NO_PROXY="localhost,127.0.0.1,.organization.internal"
```

## Debugging Configuration

### Enable Verbose Output

```bash
# Temporary verbose mode
REDIACC_VERBOSE=1 rediacc list teams

# Persistent verbose mode
export REDIACC_VERBOSE=1

# Debug levels
export REDIACC_DEBUG=1      # Basic debug
export REDIACC_DEBUG=2      # Detailed debug
export REDIACC_DEBUG=3      # Trace level
```

### Log Configuration

```bash
# Log to file
export REDIACC_LOG_FILE="/tmp/rediacc.log"

# Log level
export REDIACC_LOG_LEVEL="DEBUG"  # DEBUG, INFO, WARNING, ERROR

# Separate error log
export REDIACC_ERROR_LOG="/tmp/rediacc-errors.log"
```

## Performance Configuration

### Connection Settings

```bash
# API timeout (seconds)
export REDIACC_API_TIMEOUT=30

# Retry configuration
export REDIACC_MAX_RETRIES=3
export REDIACC_RETRY_DELAY=1

# Connection pooling
export REDIACC_POOL_SIZE=10
export REDIACC_POOL_TIMEOUT=5
```

### Sync Performance

```bash
# Parallel transfers
export REDIACC_SYNC_PARALLEL=4

# Bandwidth limit (KB/s)
export REDIACC_SYNC_BWLIMIT=1000

# Compression level (1-9)
export REDIACC_SYNC_COMPRESS=6
```

## Example Configuration Scenarios

### CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
env:
  REDIACC_TOKEN: ${{ secrets.REDIACC_TOKEN }}
  REDIACC_DEFAULT_TEAM: "Production"
  REDIACC_OUTPUT_FORMAT: "json"
  REDIACC_API_TIMEOUT: "60"
  REDIACC_VERBOSE: "1"
```

### Development Environment

```bash
# .env.development
SYSTEM_API_URL=http://localhost:8080
REDIACC_DEFAULT_TEAM=Development
REDIACC_VERIFY_SSL=0
REDIACC_DEV_MODE=1
REDIACC_VERBOSE=1
```

### Production Script

```bash
#!/bin/bash
# deploy-production.sh

# Strict mode
set -euo pipefail

# Production configuration
export REDIACC_DEFAULT_TEAM="Production"
export REDIACC_VERIFY_SSL=1
export REDIACC_API_TIMEOUT=60
export REDIACC_MAX_RETRIES=5

# Ensure token is set
if [ -z "${REDIACC_TOKEN:-}" ]; then
  echo "Error: REDIACC_TOKEN not set"
  exit 1
fi

# Run deployment
rediacc-sync upload --local ./dist --machine prod-web --repo frontend --verify
```