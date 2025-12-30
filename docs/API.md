# API Operations Guide

The `rediacc` tool provides comprehensive access to the Rediacc API for managing resources and operations.

## Overview

The CLI provides operations for:
- Companies and teams
- Machines and bridges
- Repositories and storage
- Users and permissions
- Schedules and automation
- Queue operations

## Resource Management

### Companies

```bash
# List all companies
rediacc list companies

# Create new organization (admin only)
rediacc create organization "TechCorp" \
  --email admin@techcorp.com \
  --password securepass \
  --plan ELITE

# Inspect organization details
rediacc inspect organization "TechCorp"

# Update organization vault
echo '{"settings": {"tier": "enterprise"}}' > organization-vault.json
rediacc update organization "TechCorp" --vault-file organization-vault.json
```

### Teams

```bash
# List teams
rediacc list teams

# Create team
rediacc create team "Development"

# Create team with initial vault data
echo '{"ssh_key": "...", "config": {...}}' > team-vault.json
rediacc create team "Production" --vault-file team-vault.json

# Update team vault
rediacc update team "Production" --vault-file updated-vault.json

# Delete team
rediacc delete team "OldTeam"
```

### Machines

```bash
# List machines in team
rediacc list machines --team Production

# Create machine with vault configuration
cat > machine-vault.json << EOF
{
  "ip": "192.168.1.100",
  "user": "ubuntu",
  "datastore": "/mnt/data",
  "ssh_port": 22
}
EOF
rediacc create machine "web-server-01" --team Production \
  --vault-file machine-vault.json

# Inspect machine (shows vault data)
rediacc inspect machine "web-server-01" --team Production

# Update machine configuration
rediacc update machine "web-server-01" --team Production \
  --vault-file new-config.json

# Delete machine
rediacc delete machine "old-server" --team Production
```

### Repositories

```bash
# List repositories
rediacc list repositories --team Development

# Create repository
rediacc create repository "webapp" \
  --team Development \
  --machine "dev-server"

# Create with initial configuration
echo '{"docker_image": "node:14", "port": 3000}' > repo-config.json
rediacc create repository "api" \
  --team Production \
  --machine "api-server" \
  --vault-file repo-config.json

# Update repository settings
rediacc update repository "api" --team Production \
  --vault-file updated-config.json

# Delete repository
rediacc delete repository "old-app" --team Development
```

### Storage

```bash
# List storage configurations
rediacc list storages --team Production

# Create storage with S3 configuration
cat > s3-storage.json << EOF
{
  "type": "s3",
  "bucket": "my-backups",
  "region": "us-east-1",
  "access_key": "...",
  "secret_key": "..."
}
EOF
rediacc create storage "backup-s3" --team Production \
  --vault-file s3-storage.json

# Update storage credentials
rediacc update storage "backup-s3" --team Production \
  --vault-file new-creds.json

# Delete storage
rediacc delete storage "old-backup" --team Production
```

## User Management

```bash
# List team users
rediacc list users --team Development

# Add user to team
rediacc create user "developer@organization.com" \
  --team Development \
  --role MEMBER

# Available roles:
# - ADMIN: Full team management
# - MEMBER: Standard access
# - VIEWER: Read-only access

# Remove user from team
rediacc delete user "former@organization.com" --team Development

# Get current user info
rediacc me
```

## Automation & Scheduling

### Schedules

```bash
# List schedules
rediacc list schedules --team Production

# Create backup schedule
cat > backup-task.json << EOF
{
  "task": "backup",
  "source_repo": "database",
  "destination": "backup-s3",
  "options": {
    "compression": true,
    "retention_days": 30
  }
}
EOF
rediacc create schedule "daily-backup" \
  --team Production \
  --cron "0 2 * * *" \
  --vault-file backup-task.json

# Update schedule
rediacc update schedule "daily-backup" \
  --team Production \
  --cron "0 3 * * *" \
  --vault-file updated-task.json

# Delete schedule
rediacc delete schedule "old-schedule" --team Production
```

## Search Operations

```bash
# Search across all resources
rediacc search "production"

# Search with JSON output for parsing
rediacc --output json search "web" | jq '.data[]'
```

## Vault Data Management

### Understanding Vaults

Vaults store encrypted configuration and credentials:
- **Organization Vault**: Organization-wide settings
- **Team Vault**: SSH keys, shared credentials
- **Machine Vault**: Connection details, IP addresses
- **Repository Vault**: App configuration, environment variables
- **Storage Vault**: Backup destinations, cloud credentials

### Working with Vault Files

```bash
# Inspect current vault data
rediacc inspect team Production > current-vault.json

# Modify vault data
jq '.ssh_private_key = "new-key-content"' current-vault.json > updated-vault.json

# Apply vault update
rediacc update team Production --vault-file updated-vault.json

# Verify update
rediacc inspect team Production
```

## Output Formats

### Table Format (Default)

```bash
rediacc list machines --team Production
# ┌─────────────┬──────────┬─────────┐
# │ Name        │ Status   │ Created │
# ├─────────────┼──────────┼─────────┤
# │ web-01      │ ACTIVE   │ 2024-01 │
# │ web-02      │ ACTIVE   │ 2024-01 │
# └─────────────┴──────────┴─────────┘
```

### JSON Format

```bash
rediacc --output json list machines --team Production
# {
#   "success": true,
#   "data": [
#     {"name": "web-01", "status": "ACTIVE", ...},
#     {"name": "web-02", "status": "ACTIVE", ...}
#   ]
# }
```

## Advanced Usage

### Batch Operations

```bash
# Create multiple machines
for i in {1..3}; do
  cat > machine-$i.json << EOF
{
  "ip": "192.168.1.10$i",
  "user": "ubuntu",
  "datastore": "/data"
}
EOF
  rediacc create machine "worker-0$i" \
    --team Production \
    --vault-file machine-$i.json
done

# Update all repositories in a team
for repo in $(rediacc --output json list repositories --team Dev | jq -r '.data[].name'); do
  echo "Updating $repo..."
  rediacc update repository "$repo" --team Dev --vault-file config.json
done
```

### Pipeline Integration

```bash
#!/bin/bash
# Deploy script using CLI

# Get machine details
MACHINE_INFO=$(rediacc --output json inspect machine prod-web --team Production)
MACHINE_IP=$(echo "$MACHINE_INFO" | jq -r '.data.vault.ip')

# Use machine IP for direct operations
echo "Machine IP: $MACHINE_IP"
```

### Error Handling

```bash
# Check operation success
if rediacc create machine "test" --team Dev --vault-file config.json; then
  echo "Machine created successfully"
else
  echo "Failed to create machine"
  exit 1
fi

# Capture and parse errors
ERROR=$(rediacc delete machine "nonexistent" --team Dev 2>&1)
if [[ $ERROR == *"not found"* ]]; then
  echo "Machine doesn't exist"
fi
```

## Best Practices

### 1. Use Vault Files for Sensitive Data

Never put credentials in command arguments:
```bash
# Bad - credentials visible in process list
rediacc create storage "s3" --team Prod --data '{"key":"secret"}'

# Good - credentials in file
echo '{"access_key":"...","secret_key":"..."}' > s3-creds.json
chmod 600 s3-creds.json
rediacc create storage "s3" --team Prod --vault-file s3-creds.json
rm s3-creds.json
```

### 2. Validate JSON Before Updates

```bash
# Validate JSON syntax
jq . vault-update.json > /dev/null || echo "Invalid JSON"

# Preview changes
rediacc inspect resource Current > current.json
diff current.json new.json
```

### 3. Use Meaningful Names

```bash
# Good naming
rediacc create machine "prod-web-us-east-1" --team Production
rediacc create repository "api-v2-staging" --team Staging

# Poor naming  
rediacc create machine "server1" --team Production
rediacc create repository "test" --team Staging
```

### 4. Regular Backups

```bash
# Backup team configuration
for team in Production Staging Development; do
  rediacc inspect team "$team" > "backup-$team-$(date +%Y%m%d).json"
done

# Backup all machine configs
rediacc --output json list machines --team Prod | \
  jq -r '.data[].name' | \
  while read machine; do
    rediacc inspect machine "$machine" --team Prod > "machine-$machine.json"
  done
```