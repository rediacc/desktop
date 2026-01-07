# File Synchronization Guide

The `rediacc-sync` tool provides efficient file synchronization between local directories and remote repositories using rsync over SSH.

## Overview

Key features:
- Efficient rsync-based transfers
- Upload and download operations
- Mirror mode for exact replication
- File exclusion patterns
- Verification mode
- Progress tracking

## Basic Usage

### Upload Files

```bash
# Basic upload
rediacc-sync upload --local ./myproject --machine server --repository webapp

# With team specification
rediacc-sync upload --local ./src --machine dev-server --repository backend --team Development
```

### Download Files

```bash
# Basic download
rediacc-sync download --machine server --repository webapp --local ./backup

# With verification
rediacc-sync download --machine server --repository webapp --local ./backup --verify
```

## Advanced Options

### Mirror Mode

Mirror mode ensures the destination is an exact copy of the source by deleting files that don't exist in the source.

```bash
# Upload with mirror (deletes remote files not in local)
rediacc-sync upload --local ./dist --machine prod --repository frontend --mirror --confirm

# Download with mirror (deletes local files not in remote)
rediacc-sync download --machine backup --repository archive --local ./restore --mirror --confirm
```

**Warning**: Always use `--confirm` with `--mirror` to preview changes before execution.

### File Exclusions

Exclude files or patterns from synchronization:

```bash
# Single exclusion
rediacc-sync upload --local ./app --machine server --repository api \
  --exclude "*.log"

# Multiple exclusions
rediacc-sync upload --local ./app --machine server --repository api \
  --exclude "*.log" \
  --exclude "*.tmp" \
  --exclude "__pycache__" \
  --exclude "node_modules"

# Using exclude file
echo -e "*.log\n*.tmp\n__pycache__\nnode_modules" > .syncignore
rediacc-sync upload --local ./app --machine server --repository api \
  --exclude-from .syncignore
```

### Verification Mode

Verify file integrity after transfer:

```bash
# Download with verification
rediacc-sync download --machine prod --repository database-backup \
  --local ./backups/latest --verify

# Verification checks:
# - File sizes match
# - Modification times preserved
# - Checksums verified (if different)
```

## Common Use Cases

### 1. Deploy Web Application

```bash
# Build and deploy frontend
npm run build
rediacc-sync upload --local ./dist --machine prod --repository webapp \
  --mirror --exclude ".DS_Store" --confirm

# Deploy backend with dependencies
rediacc-sync upload --local ./backend --machine prod --repository api \
  --exclude "__pycache__" --exclude "*.pyc" --exclude ".env"
```

### 2. Backup Repository

```bash
# Create timestamped backup
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

rediacc-sync download --machine prod --repository database \
  --local "$BACKUP_DIR" --verify
```

### 3. Sync Development Environment

```bash
# Push changes to dev server
rediacc-sync upload --local ./src --machine dev --repository myapp \
  --exclude ".git" --exclude "*.swp"

# Pull latest changes
rediacc-sync download --machine dev --repository myapp \
  --local ./src --exclude ".git"
```

### 4. Migrate Between Machines

```bash
# Download from old machine
rediacc-sync download --machine old-server --repository app-data \
  --local ./migration-temp --verify

# Upload to new machine
rediacc-sync upload --local ./migration-temp \
  --machine new-server --repository app-data --verify
```

## Performance Tips

### 1. Use Compression

Rsync automatically compresses data during transfer. This is especially beneficial for:
- Text files
- Source code
- Uncompressed data

### 2. Exclude Unnecessary Files

Always exclude:
- Build artifacts (`dist/`, `build/`)
- Dependencies (`node_modules/`, `vendor/`)
- Cache directories
- Log files
- Temporary files

### 3. Use Mirror Mode Carefully

- Always use `--confirm` first
- Keep backups before using `--mirror`
- Understand what will be deleted

### 4. Batch Operations

```bash
# Sync multiple repos efficiently
REPOS=("frontend" "backend" "scripts")
for repo in "${REPOS[@]}"; do
  echo "Syncing $repository..."
  rediacc-sync upload --local ./$repository --machine prod --repository $repository
done
```

## Troubleshooting

### Common Issues

#### Permission Denied
```
Error: Permission denied (publickey)
```
**Solution**: Ensure your team vault has the correct SSH key

#### Connection Timeout
```
Error: ssh: connect to host X.X.X.X port 22: Connection timed out
```
**Solution**: Check machine is online and accessible

#### Rsync Not Found
```
Error: bash: rsync: command not found
```
**Solution**: Install rsync on the remote machine

#### File Not Found
```
Error: rsync: link_stat "/path/to/file" failed: No such file or directory
```
**Solution**: Verify local path exists and is accessible

### Debug Mode

Enable verbose output for troubleshooting:

```bash
# Set verbose environment variable
export REDIACC_VERBOSE=1

# Run sync command
rediacc-sync upload --local ./test --machine server --repository test
```

## Security Considerations

1. **SSH Key Management**
   - Private keys are stored encrypted in team vault
   - Temporary key files are created with restricted permissions (600)
   - Keys are cleaned up after use

2. **Data Encryption**
   - All transfers use SSH encryption
   - No data is stored unencrypted during transfer

3. **Access Control**
   - Requires valid Rediacc token
   - Respects team and machine permissions
   - Operations logged for audit

## Best Practices

1. **Always Preview Changes**
   ```bash
   # Use --confirm to preview
   rediacc-sync upload --local ./app --machine prod --repository webapp \
     --mirror --confirm
   ```

2. **Create Exclude Lists**
   ```bash
   # .syncignore file
   *.log
   *.tmp
   .DS_Store
   Thumbs.db
   __pycache__/
   node_modules/
   .git/
   ```

3. **Verify Important Transfers**
   ```bash
   # Always verify critical data
   rediacc-sync download --machine backup --repository critical-data \
     --local ./restore --verify
   ```

4. **Use Descriptive Repository Names**
   - Good: `webapp-frontend`, `api-backend`, `database-backups`
   - Bad: `stuff`, `files`, `backup1`