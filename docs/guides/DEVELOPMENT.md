# Development Guide

This guide covers development features and practices for working with the Rediacc CLI.

## Development Mode

### Enabling Dev Mode

Development mode relaxes certain security restrictions for easier development:

```bash
# Via command line flag
rediacc-term --dev --machine dev-server

# Via environment variable
export REDIACC_DEV_MODE=1
rediacc-term --machine dev-server

# In sync operations
rediacc-sync upload --dev --local ./src --machine dev --repository test
```

### What Dev Mode Changes

1. **SSH Host Checking**: Disables strict host key checking
2. **SSL Verification**: Can be disabled (use with caution)
3. **Verbose Output**: Automatically enables debug logging
4. **Timeouts**: Extended timeouts for debugging

**Warning**: Never use dev mode in production!

## Local Development Setup

### Running Against Local API

```bash
# Point to local API
export SYSTEM_API_URL="http://localhost:8080"
export REDIACC_VERIFY_SSL=0

# Use local middleware
./rediacc list teams
```

### Mock Environments

Create mock configurations for testing:

```bash
# Create test team with mock data
cat > mock-team.json << EOF
{
  "ssh_private_key": "$(cat ~/.ssh/id_rsa_test)",
  "config": {
    "environment": "development",
    "debug": true
  }
}
EOF

rediacc create team "DevTest" --vault-file mock-team.json
```

## Debugging Features

### Verbose Output

```bash
# Level 1: Basic verbose
REDIACC_VERBOSE=1 rediacc list teams

# Level 2: Include API calls
REDIACC_DEBUG=2 rediacc list teams

# Level 3: Full trace
REDIACC_DEBUG=3 rediacc list teams
```

### Request/Response Logging

```bash
# Log all API requests
export REDIACC_LOG_REQUESTS=1
export REDIACC_LOG_FILE="/tmp/rediacc-api.log"

# Monitor in real-time
tail -f /tmp/rediacc-api.log
```

### SSH Debugging

```bash
# Debug SSH connections
export REDIACC_SSH_DEBUG=1

# Very verbose SSH
rediacc-term --machine dev --command "echo test" 2>&1 | tee ssh-debug.log
```

## Testing Scripts

### Unit Test Helpers

```python
# test_helper.py
import os
import json
import subprocess

def run_cli_command(args, token=None):
    """Helper to run CLI commands in tests"""
    env = os.environ.copy()
    if token:
        env['REDIACC_TOKEN'] = token
    
    cmd = ['./rediacc'] + args
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    if '--output json' in args:
        return json.loads(result.stdout)
    return result.stdout, result.stderr, result.returncode
```

### Integration Test Example

```bash
#!/bin/bash
# test_integration.sh

set -e

# Setup
export REDIACC_TOKEN="test-token"
export SYSTEM_API_URL="http://localhost:8080"

# Test: Create and verify team
echo "Creating test team..."
./rediacc create team "TestTeam-$$"

echo "Verifying team exists..."
if ./rediacc list teams | grep -q "TestTeam-$$"; then
    echo "✓ Team created successfully"
else
    echo "✗ Team creation failed"
    exit 1
fi

# Cleanup
./rediacc delete team "TestTeam-$$"
```

## Development Workflows

### Feature Development

```bash
# 1. Create feature branch
git checkout -b feature/new-command

# 2. Set up dev environment
export REDIACC_DEV_MODE=1
export SYSTEM_API_URL="http://localhost:8080"
export REDIACC_VERBOSE=1

# 3. Test changes iteratively
while developing; do
    ./rediacc new-command --test
    # Make changes
done

# 4. Run test suite
./tests/run-all-tests.sh
```

### API Development

When developing against the API:

```bash
# Monitor API calls
export REDIACC_LOG_REQUESTS=1

# Use curl to test endpoints directly
TOKEN="your-dev-token"
curl -H "Rediacc-RequestToken: $TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:8080/api/StoredProcedure/GetTeams

# Compare with CLI
./rediacc --output json list teams
```

## Performance Profiling

### Timing Commands

```bash
# Simple timing
time ./rediacc list teams

# Detailed profiling
python3 -m cProfile -o profile.stats src/cli/commands/cli_main.py list teams
python3 -m pstats profile.stats
```

### Memory Profiling

```bash
# Install memory profiler
pip install memory_profiler

# Run with memory profiling
python3 -m memory_profiler src/cli/commands/cli_main.py list teams
```

## Custom Extensions

### Adding Custom Commands

```python
# custom_commands.py
def handle_custom_command(args):
    """Custom command implementation"""
    if args.command == 'custom-deploy':
        # Implementation
        pass

# In main CLI
if args.command.startswith('custom-'):
    import custom_commands
    custom_commands.handle_custom_command(args)
```

### Plugin System

```python
# plugins/my_plugin.py
class MyPlugin:
    def __init__(self, cli):
        self.cli = cli
    
    def register_commands(self):
        return {
            'my-command': self.my_command_handler
        }
    
    def my_command_handler(self, args):
        print("Executing custom plugin command")
```

## Development Tools

### Makefile for Common Tasks

```makefile
# Makefile
.PHONY: test lint format clean

test:
	cd tests && ./run-all-tests.sh

lint:
	pylint rediacc*.py
	shellcheck *.sh

format:
	black rediacc*.py
	shfmt -w *.sh

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete
	rm -rf .pytest_cache

dev-setup:
	pip install -r requirements-dev.txt
	pre-commit install
```

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 22.3.0
    hooks:
      - id: black
        language_version: python3

  - repo: https://github.com/pycqa/pylint
    rev: v2.13.0
    hooks:
      - id: pylint

  - repo: https://github.com/shellcheck-py/shellcheck-py
    rev: v0.8.0
    hooks:
      - id: shellcheck
```

## Environment Variables Reference

### Development-Specific Variables

```bash
# Core development
REDIACC_DEV_MODE=1              # Enable development mode
REDIACC_DEBUG=3                 # Maximum debug level
REDIACC_VERBOSE=1               # Verbose output

# API development
SYSTEM_API_URL="http://localhost:8080"
REDIACC_VERIFY_SSL=0            # Disable SSL verification
REDIACC_LOG_REQUESTS=1          # Log all API requests

# SSH development
REDIACC_SSH_DEBUG=1             # SSH debug output
REDIACC_SSH_OPTS="-v -o StrictHostKeyChecking=no"

# Testing
REDIACC_TEST_MODE=1             # Enable test mode
REDIACC_MOCK_API=1              # Use mock API responses
REDIACC_TEST_TOKEN="test-token" # Test token
```

## Troubleshooting Development Issues

### Import Errors

```python
# Add project root to Python path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

### SSL Issues in Development

```bash
# Disable SSL warnings in development
export PYTHONWARNINGS="ignore:Unverified HTTPS request"

# Or in code
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

### Mock SSH for Testing

```bash
# Create mock SSH script
cat > mock-ssh.sh << 'EOF'
#!/bin/bash
echo "Mock SSH: $@"
# Simulate commands
case "$@" in
  *"echo test"*) echo "test" ;;
  *"docker ps"*) echo "CONTAINER ID   IMAGE   STATUS" ;;
  *) echo "Unknown command" ;;
esac
EOF

chmod +x mock-ssh.sh
export PATH="$(pwd):$PATH"
alias ssh='./mock-ssh.sh'
```

## Contributing Guidelines

### Code Style

1. **Python**: Follow PEP 8, use Black formatter
2. **Shell**: Follow Google Shell Style Guide
3. **Documentation**: Use Markdown, include examples

### Testing Requirements

1. Add tests for new features
2. Ensure all tests pass
3. Include integration tests for API changes
4. Document test requirements

### Pull Request Process

1. Create feature branch
2. Implement changes with tests
3. Update documentation
4. Run linters and tests
5. Submit PR with clear description