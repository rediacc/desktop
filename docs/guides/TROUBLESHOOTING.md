# Troubleshooting Guide

This guide helps resolve common issues with the Rediacc CLI tools.

## Common Issues

### Authentication Problems

#### Invalid Token Format
```
Error: Invalid token format
```

**Causes:**
- Token doesn't match expected pattern
- Token copied incorrectly
- Extra whitespace in token

**Solutions:**
1. Verify token format: `XX-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXXXXXXXXXX`
2. Re-copy token without spaces: `echo "$REDIACC_TOKEN" | tr -d ' '`
3. Login again: `./rediacc login`

#### Token Expired
```
Error: Authentication failed
```

**Solutions:**
1. Login again to get new token:
   ```bash
   ./rediacc login
   ```
2. Check token validity:
   ```bash
   ./rediacc me
   ```

#### No Token Available
```
Error: No token available. Please login or provide token.
```

**Solutions:**
1. Login: `./rediacc login`
2. Set environment variable: `export REDIACC_TOKEN="your-token"`
3. Use parameter: `--token "your-token"`

### Connection Issues

#### Connection Refused
```
Error: Connection refused
```

**Causes:**
- API server down
- Wrong API URL
- Firewall blocking connection

**Solutions:**
1. Check API URL:
   ```bash
   rediacc config get api_url
   ```
2. Test connectivity:
   ```bash
   curl -I https://www.rediacc.com
   ```
3. Check proxy settings:
   ```bash
   echo $HTTP_PROXY $HTTPS_PROXY
   ```

#### SSL Certificate Errors
```
Error: SSL certificate problem: unable to get local issuer certificate
```

**Solutions:**
1. Update certificates:
   ```bash
   # Linux
   sudo update-ca-certificates
   
   # macOS
   brew install ca-certificates
   ```
2. For development only:
   ```bash
   export REDIACC_VERIFY_SSL=0
   ```

#### Timeout Errors
```
Error: Request timeout
```

**Solutions:**
1. Increase timeout:
   ```bash
   export REDIACC_API_TIMEOUT=60
   ```
2. Check network connectivity
3. Try again during off-peak hours

### SSH/Terminal Issues

#### Host Key Verification Failed
```
Host key verification failed
```

**Solutions:**
1. For known host changes:
   ```bash
   ssh-keygen -R <host-ip>
   ```
2. For development:
   ```bash
   rediacc-term --dev --machine dev-server
   ```

#### Permission Denied (publickey)
```
Permission denied (publickey)
```

**Causes:**
- Wrong SSH key in team vault
- Key permissions incorrect
- Machine not accepting key

**Solutions:**
1. Verify team vault has correct SSH key:
   ```bash
   rediacc inspect team MyTeam | jq '.vault.ssh_private_key'
   ```
2. Update SSH key in vault:
   ```bash
   echo '{"ssh_private_key": "-----BEGIN RSA..."}' > vault.json
   rediacc update team MyTeam --vault-file vault.json
   ```

#### Connection Timeout
```
ssh: connect to host X.X.X.X port 22: Connection timed out
```

**Solutions:**
1. Verify machine is online
2. Check machine IP in vault:
   ```bash
   rediacc inspect machine my-machine --team MyTeam
   ```
3. Test direct SSH:
   ```bash
   ssh -v user@machine-ip
   ```

### Sync Issues

#### Rsync Not Found
```
bash: rsync: command not found
```

**Solutions:**

**Linux:**
```bash
sudo apt-get install rsync  # Debian/Ubuntu
sudo yum install rsync      # RHEL/CentOS
```

**macOS:**
```bash
# Usually pre-installed, if not:
brew install rsync
```

**Windows:**
1. Install MSYS2
2. In MSYS2: `pacman -S rsync`
3. Add to PATH: `C:\msys64\usr\bin`

#### File Not Found
```
rsync: link_stat "/path/to/file" failed: No such file or directory
```

**Solutions:**
1. Verify local path exists:
   ```bash
   ls -la /path/to/file
   ```
2. Use absolute paths
3. Check for typos in path

#### Permission Denied During Sync
```
rsync: mkstemp "/path/.file.XXXXXX" failed: Permission denied
```

**Solutions:**
1. Check remote directory permissions
2. Verify repository exists:
   ```bash
   rediacc-term --machine server --repository myrepo --command "ls -la"
   ```

### API Errors

#### Resource Not Found
```
Error: Machine 'my-machine' not found in team 'MyTeam'
```

**Solutions:**
1. List available resources:
   ```bash
   rediacc list machines --team MyTeam
   ```
2. Check spelling and case
3. Verify team access

#### Validation Errors
```
Error: Validation failed: Name is required
```

**Solutions:**
1. Check required parameters in help:
   ```bash
   rediacc create machine --help
   ```
2. Provide all required fields

#### Rate Limiting
```
Error: Too many requests
```

**Solutions:**
1. Add delays between requests
2. Batch operations where possible
3. Contact support for limit increase

## Platform-Specific Issues

### Windows

#### PowerShell Execution Policy
```
cannot be loaded because running scripts is disabled
```

**Solution:**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

#### Path Spaces
```
The system cannot find the path specified
```

**Solution:**
Use quotes for paths with spaces:
```powershell
rediacc.bat sync upload --local "C:\My Documents\project" --machine server --repository data
```

#### MSYS2 Not Found
```
rsync: command not found
```

**Solution:**
1. Install MSYS2 from https://www.msys2.org/
2. Add to PATH: `C:\msys64\usr\bin`
3. Restart terminal

### macOS

#### Python Version Issues
```
python3: command not found
```

**Solution:**
```bash
# Install Python via Homebrew
brew install python@3.9
```

#### Quarantine Attributes
```
cannot be opened because the developer cannot be verified
```

**Solution:**
```bash
xattr -d com.apple.quarantine ./rediacc*
```

### Linux

#### Missing Dependencies
```
ImportError: No module named 'module_name'
```

**Solution:**
```bash
pip3 install -r requirements.txt
```

#### Permission Issues
```
Permission denied: '/usr/local/bin/rediacc'
```

**Solution:**
```bash
# Install to user directory
pip3 install --user -r requirements.txt

# Or use sudo (not recommended)
sudo pip3 install -r requirements.txt
```

## Debugging Techniques

### Enable Verbose Logging

```bash
# Maximum verbosity
export REDIACC_VERBOSE=1
export REDIACC_DEBUG=3

# Run command
rediacc list teams
```

### Check Configuration

```bash
# View all configuration
rediacc config list

# Check specific values
rediacc config get api_url
rediacc config get default_team
```

### Test Connectivity

```bash
# Test API endpoint
curl -v https://www.rediacc.com/health

# Test with token
curl -H "Rediacc-RequestToken: $REDIACC_TOKEN" \
     https://www.rediacc.com/api/StoredProcedure/GetUserInfo
```

### Capture Debug Output

```bash
# Save all output
rediacc list teams --debug > debug.log 2>&1

# Separate stdout and stderr
rediacc list teams > output.log 2> error.log
```

## Getting Help

### Built-in Help

```bash
# General help
./rediacc --help

# Command-specific help
rediacc create machine --help
rediacc-sync --help
rediacc-term --help
```

### Version Information

```bash
# CLI version
./rediacc --version

# Python version
python3 --version

# System information
uname -a
```

### Support Resources

1. **Documentation**: Check `/docs` folder
2. **GitHub Issues**: https://github.com/anthropics/claude-code/issues
3. **Logs**: Check `~/.rediacc/logs/` for detailed logs

### Reporting Issues

When reporting issues, include:
1. Command that failed
2. Full error message
3. Output of `./rediacc --version`
4. Operating system and version
5. Debug log if available

Example:
```bash
# Gather debug information
./rediacc --version > debug-info.txt
echo "OS: $(uname -a)" >> debug-info.txt
echo "Python: $(python3 --version)" >> debug-info.txt
echo "Error:" >> debug-info.txt
rediacc list teams --debug >> debug-info.txt 2>&1
```