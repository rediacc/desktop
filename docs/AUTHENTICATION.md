# Authentication Guide

This guide covers authentication and token management for the Rediacc CLI.

## Overview

The Rediacc CLI uses token-based authentication with automatic token rotation for enhanced security. Tokens can be provided via:
1. Configuration file (`~/.rediacc/config.json`)
2. Environment variable (`REDIACC_TOKEN`)
3. Command-line parameter (`--token`)

## Authentication Methods

### 1. Interactive Login (Recommended)

```bash
# Interactive login prompts for email and password
./rediacc login

# Login with credentials
./rediacc login --email user@example.com --password yourpassword
```

After successful login, the token is stored in `~/.rediacc/config.json`.

### 2. Environment Variable

```bash
# Set token in environment
export REDIACC_TOKEN="your-api-token"

# Commands will use this token
./rediacc list teams
```

### 3. Command-Line Parameter

```bash
# Provide token directly
./rediacc --token "your-api-token" list teams

# Works with all tools
./rediacc-sync --token "your-api-token" upload --local ./files --machine server --repository data
```

## Token Priority

Tokens are used in the following priority order:
1. Command-line `--token` parameter (highest priority)
2. `REDIACC_TOKEN` environment variable
3. Stored token in `~/.rediacc/config.json` (lowest priority)

## Token Management

### View Current User

```bash
# Show current authenticated user
./rediacc me
```

### Logout

```bash
# Remove stored token
./rediacc logout
```

### Token Rotation

The Rediacc API uses automatic token rotation for security:
- Each API response includes a new token (`nextRequestToken`)
- The CLI automatically updates stored tokens after each request
- Old tokens are invalidated after use

### Multiple Tokens

The CLI supports managing multiple named tokens:

```bash
# Save a token with a name
./rediacc token save "production" "prod-token-value"

# Use a named token
./rediacc --token-name "production" list teams

# List saved tokens
./rediacc token list

# Remove a named token
./rediacc token remove "production"
```

## Security Best Practices

### 1. Token Storage
- Tokens are stored in `~/.rediacc/config.json` with restricted permissions (600)
- Never commit tokens to version control
- Use environment variables in CI/CD pipelines

### 2. Token Handling
- Tokens are masked in error messages
- Use `--output json` for programmatic access
- Rotate tokens regularly

### 3. Secure Transmission
- All API communications use HTTPS
- SSL/TLS certificate verification is enforced
- Use `--insecure` only for development (not recommended)

## Troubleshooting

### Invalid Token Format
```
Error: Invalid token format
```
**Solution**: Ensure token follows the pattern `twoLetters-uuid-32alphanumeric`

### Token Expired
```
Error: Authentication failed
```
**Solution**: Login again to get a new token

### Permission Denied
```
Error: Failed to save token: Permission denied
```
**Solution**: Check permissions on `~/.rediacc/` directory

### Token Not Found
```
Error: No token available
```
**Solution**: Run `./rediacc login` or set `REDIACC_TOKEN`

## Advanced Configuration

### Custom Config Location

```bash
# Use custom config file
export REDIACC_CONFIG_PATH="/path/to/config.json"
```

### API URL Override

```bash
# Use different API endpoint
./rediacc --api-url "https://api.custom.com" list teams
```

### Debugging Authentication

```bash
# Enable verbose output
export REDIACC_VERBOSE=1
./rediacc list teams

# Check token validation
./rediacc --token "your-token" me
```

## Integration Examples

### Shell Scripts
```bash
#!/bin/bash
# Script using environment variable
export REDIACC_TOKEN="your-token"
./rediacc list teams
./rediacc-sync upload --local ./data --machine server --repository backup
```

### CI/CD Pipeline
```yaml
# GitHub Actions example
- name: Deploy with Rediacc
  env:
    REDIACC_TOKEN: ${{ secrets.REDIACC_TOKEN }}
  run: |
    ./rediacc-sync upload --local ./dist --machine prod --repository webapp
```

### Python Integration
```python
import subprocess
import os

# Set token in environment
os.environ['REDIACC_TOKEN'] = 'your-token'

# Run CLI command
result = subprocess.run(['./rediacc', 'list', 'teams'], 
                       capture_output=True, text=True)
print(result.stdout)
```