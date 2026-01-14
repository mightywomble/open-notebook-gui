# Security Setup Guide for Maintainers

This document explains the security measures implemented in this repository and how to set them up.

## Overview

This repository includes multiple layers of security to protect against accidental exposure of sensitive information:

1. **Git-level protection** (.gitignore, .gitattributes)
2. **Pre-commit hooks** (optional but recommended)
3. **GitHub Actions CI/CD** (automated scanning)
4. **Documentation** (user awareness)

## Quick Start

### For Repository Maintainers

1. **Enable GitHub Security Features**
   - Go to repository Settings → Security
   - Enable Dependabot alerts
   - Enable Dependabot security updates
   - Enable Secret scanning
   - Enable Code scanning (if available for your account)

2. **Set Up Branch Protection**
   - Go to Settings → Branches
   - Add rule for `main` branch:
     - Require pull request reviews
     - Require status checks to pass (including security scans)
     - Require branches to be up to date

3. **Configure Security Advisories**
   - Go to Security → Advisories
   - Enable private vulnerability reporting

### For Contributors (Optional but Recommended)

Install pre-commit hooks for local security checking:

```bash
# Install pre-commit
pip install pre-commit

# Install the hooks
pre-commit install

# Test it works
pre-commit run --all-files
```

This will automatically check for secrets, credentials, and security issues before each commit.

## Security Features Explained

### 1. `.gitignore` - Prevent Committing Secrets

**What it does:**
- Blocks common secret files (`.env`, `*.key`, `*.pem`, etc.)
- Ignores output directory (`doc_exports/`)
- Blocks credential files and patterns

**Verification:**
```bash
# Test that .gitignore is working
echo "SECRET_KEY=abc123" > .env
git status  # Should NOT show .env
```

### 2. `.gitattributes` - Normalize & Mark Sensitive Files

**What it does:**
- Normalizes line endings across platforms
- Marks binary files correctly
- Sets up patterns for git-crypt (if you choose to use it)

**Note:** The git-crypt filters are configured but optional. If you don't use git-crypt, these lines are safely ignored.

### 3. `.pre-commit-config.yaml` - Local Security Checks

**What it does:**
- Scans for hardcoded secrets (Gitleaks, detect-secrets)
- Checks for private keys
- Detects AWS credentials
- Runs Python security linter (Bandit)
- Code quality checks (Black, isort, flake8)

**Setup:**
```bash
pip install pre-commit
pre-commit install
```

**Manual run:**
```bash
pre-commit run --all-files
```

### 4. `.github/workflows/security.yml` - Automated CI Scanning

**What it does:**
- Runs on every push and PR
- Weekly scheduled scans
- Multiple security tools:
  - **Bandit**: Python security linter
  - **Safety**: Checks for vulnerable dependencies
  - **TruffleHog**: Advanced secret scanning
  - **GitLeaks**: Secret detection
  - **Dependency Review**: Checks for vulnerable dependencies in PRs

**Verification:**
- Check the "Actions" tab in GitHub after a commit
- Security scan should complete successfully

### 5. `SECURITY.md` - User Guidelines

**What it does:**
- Provides security policy
- Vulnerability reporting instructions
- Best practices for users
- Warnings about data handling

**For maintainers:**
- Update contact information for vulnerability reports
- Review and update supported versions

### 6. `.env.example` - Safe Configuration Template

**What it does:**
- Provides template for environment variables
- Safe to commit (contains no actual secrets)
- Helps users understand what config is needed

**Usage:**
```bash
cp .env.example .env
# Edit .env with actual values
# .env is gitignored and won't be committed
```

## Testing Your Security Setup

### 1. Test Gitignore

```bash
# Should be ignored
echo "SECRET=test123" > .env
git status  # Should NOT show .env

# Should be tracked
echo "EXAMPLE=placeholder" > .env.example
git status  # SHOULD show .env.example
```

### 2. Test Pre-commit (if installed)

```bash
# Create a test file with a fake secret
echo "aws_access_key_id = AKIAIOSFODNN7EXAMPLE" > test_secret.py

# Try to commit (should fail)
git add test_secret.py
git commit -m "test"  # Should be blocked by pre-commit

# Clean up
rm test_secret.py
```

### 3. Test GitHub Actions

```bash
# Make a small change and push
echo "# Test" >> README.md
git add README.md
git commit -m "Test security workflow"
git push

# Check Actions tab - security workflow should run
```

## Responding to Security Issues

### If a Secret is Accidentally Committed

1. **Immediately rotate the compromised credential**
2. **Remove from Git history:**
   ```bash
   # Using git filter-repo (recommended)
   pip install git-filter-repo
   git filter-repo --path path/to/secret/file --invert-paths
   
   # Force push (WARNING: rewrites history)
   git push origin --force --all
   ```
3. **Notify users** if the repository is public
4. **Review** why it wasn't caught and improve detection

### If a Vulnerability is Reported

1. **Acknowledge** the report within 48 hours
2. **Assess** the severity and impact
3. **Fix** the issue in a private branch
4. **Test** the fix thoroughly
5. **Release** the fix and publish a security advisory
6. **Thank** the reporter

## Maintenance Checklist

### Monthly
- [ ] Review Dependabot alerts
- [ ] Check Actions tab for failed security scans
- [ ] Update security scanning tools versions in workflows

### Quarterly
- [ ] Review and update SECURITY.md
- [ ] Test all security workflows
- [ ] Update pre-commit hook versions
- [ ] Review `.gitignore` for new patterns

### Before Each Release
- [ ] Run full security scan
- [ ] Review all dependencies for vulnerabilities
- [ ] Check for any TODO or FIXME related to security
- [ ] Verify no secrets in git history

## Additional Security Measures (Optional)

### Git-Crypt for Sensitive Files

If you need to commit encrypted files:

```bash
# Install git-crypt
brew install git-crypt  # macOS
# or: apt-get install git-crypt  # Linux

# Initialize
git-crypt init

# Add collaborators
git-crypt add-gpg-user USER_ID

# Files matching patterns in .gitattributes will be encrypted
```

### Signed Commits

Require commit signing:

```bash
# Generate GPG key
gpg --full-generate-key

# Configure git
git config --global user.signingkey YOUR_KEY_ID
git config --global commit.gpgsign true

# Add GPG key to GitHub account
```

### Security Scanning in IDE

**VS Code Extensions:**
- GitLens (secret detection)
- SonarLint (code quality & security)
- Git History (audit changes)

**PyCharm:**
- Built-in inspections include security checks
- Enable "Python Security" inspection profile

## Resources

- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)
- [Pre-commit Documentation](https://pre-commit.com/)
- [Bandit Documentation](https://bandit.readthedocs.io/)

## Questions?

If you have questions about security setup:
1. Check the documentation links above
2. Review existing GitHub issues
3. Open a new issue with the `security` label
4. For sensitive matters, see SECURITY.md for private reporting

---

**Last Updated:** 2024
**Maintainer:** See repository owner