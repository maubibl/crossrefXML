# GitHub Security Guide for Crossref Pipeline Scripts

## Overview

The Crossref registration scripts require credentials and configuration values that should **never** be committed to version control. This guide explains how to securely manage these sensitive values.

## Environment Variables

The scripts now use environment variables instead of hardcoded credentials:

| Variable | Script(s) | Purpose |
|----------|-----------|---------|
| `CROSSREF_USERNAME` | doireg.py, csv_reg.py | CrossRef account username |
| `CROSSREF_PASSWORD` | doireg.py, csv_reg.py | CrossRef account password |
| `CROSSREF_DEPOSITOR_NAME` | csv-crossref.py | Depositor name (format: org:org) |
| `CROSSREF_EMAIL` | csv-crossref.py | Contact email for CrossRef deposits |
| `CROSSREF_REGISTRANT` | csv-crossref.py | Organization name for registration |

## Setup Instructions

### 1. Local Development

**Create a `.env` file** in the project root:
```bash
cp .env.example .env
```

**Edit `.env`** and add your actual credentials:
```
CROSSREF_USERNAME=your_username
CROSSREF_PASSWORD=your_password
CROSSREF_DEPOSITOR_NAME=malmo:malmo
CROSSREF_EMAIL=your.email@mau.se
CROSSREF_REGISTRANT=Malmö University
```

**Load environment variables** before running scripts:
```bash
# Option 1: Load from .env file (using python-dotenv)
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv(); import doireg"

# Option 2: Export manually
export CROSSREF_USERNAME="your_username"
export CROSSREF_PASSWORD="your_password"
# Then run script
python doireg.py
```

**Add `.env` to `.gitignore`** to prevent accidental commits:
```bash
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Add .env to gitignore"
```

### 2. GitHub Actions / CI/CD

For automated deployments, add repository secrets in GitHub:

**Steps:**
1. Go to Settings → Secrets and variables → Actions
2. Click "New repository secret" for each variable:
   - `CROSSREF_USERNAME`
   - `CROSSREF_PASSWORD`
   - `CROSSREF_DEPOSITOR_NAME`
   - `CROSSREF_EMAIL`
   - `CROSSREF_REGISTRANT`

**In your workflow file** (e.g., `.github/workflows/deploy.yml`):
```yaml
- name: Run Crossref Pipeline
  env:
    CROSSREF_USERNAME: ${{ secrets.CROSSREF_USERNAME }}
    CROSSREF_PASSWORD: ${{ secrets.CROSSREF_PASSWORD }}
    CROSSREF_DEPOSITOR_NAME: ${{ secrets.CROSSREF_DEPOSITOR_NAME }}
    CROSSREF_EMAIL: ${{ secrets.CROSSREF_EMAIL }}
    CROSSREF_REGISTRANT: ${{ secrets.CROSSREF_REGISTRANT }}
  run: python csv_reg.py
```

### 3. Production / Server Deployment

**On the production server**, set environment variables:

**Option A: System environment (persistent)**
```bash
# Add to /etc/environment or ~/.bashrc
export CROSSREF_USERNAME="your_username"
export CROSSREF_PASSWORD="your_password"
# ... other variables
```

**Option B: Application configuration**
- Use a secrets management tool (AWS Secrets Manager, HashiCorp Vault, etc.)
- Load credentials from a secure configuration service

**Option C: Process-specific**
```bash
CROSSREF_USERNAME=user CROSSREF_PASSWORD=pass python csv_reg.py
```

## Security Best Practices

1. **Never commit credentials**: Even with Git history cleanup, committed secrets can be extracted
   - Always use `.env` / `.gitignore`
   - Assume any committed credentials are compromised

2. **Rotate credentials if compromised**:
   - Update credentials at CrossRef account settings
   - Update GitHub repository secrets
   - Update server environment variables

3. **Use strong passwords**:
   - Your password appears in command history and logs
   - Use a unique password for CrossRef account
   - Use a password manager

4. **Restrict access**:
   - GitHub Actions secrets are only visible to organization admins
   - Server environment variables should have restricted file permissions
   - Audit who has access to credentials

5. **Audit logs**:
   - Monitor CrossRef account login history for suspicious activity
   - Check server logs for credential leaks
   - Review GitHub Actions execution logs (don't commit sensitive output)

## Default Values

Some environment variables have sensible defaults:
- `CROSSREF_DEPOSITOR_NAME` → defaults to `malmo:malmo`
- `CROSSREF_EMAIL` → defaults to `depositor@example.com` (will fail upload)
- `CROSSREF_REGISTRANT` → defaults to `Malmö University`

**Note:** `CROSSREF_USERNAME` and `CROSSREF_PASSWORD` have no defaults and are **required** for uploads.

## Troubleshooting

### "CROSSREF_USERNAME and CROSSREF_PASSWORD environment variables must be set"
- Verify variables are exported: `echo $CROSSREF_USERNAME`
- Verify they're not empty
- Check script execution context (e.g., cronjob may have different env)

### Variables not loaded in Python
Ensure you're loading them correctly:
```python
import os
username = os.environ.get('CROSSREF_USERNAME')
password = os.environ.get('CROSSREF_PASSWORD')
print(f"Username: {username}")  # Debug
```

### GitHub Actions secrets not accessible
- Verify secret names exactly match env variable names (case-sensitive)
- Verify workflow syntax is correct (`${{ secrets.SECRET_NAME }}`)
- Check that secrets are set in the correct repository (not organization)

## Migration from Hardcoded Values

If you previously had hardcoded values:

1. **Backup your current setup** (optional):
   ```bash
   git stash  # Save current changes
   ```

2. **Pull the updated scripts** with environment variable support

3. **Create and configure `.env`** as described above

4. **Test locally**:
   ```bash
   export CROSSREF_USERNAME="test"
   export CROSSREF_PASSWORD="test"
   python csv-crossref.py --help  # Should work
   ```

5. **Deploy to production** and verify environment variables are set

6. **Remove backup** if everything works:
   ```bash
   git stash drop
   ```

## Additional Resources

- [GitHub Encrypted Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Python-dotenv Documentation](https://github.com/theskumar/python-dotenv)
- [OWASP Secrets Management Guidelines](https://owasp.org/www-project-top-10/)
