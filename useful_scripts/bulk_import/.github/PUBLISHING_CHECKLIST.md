# Publishing Checklist for ON_Bulk_Import

Use this checklist before making your repository public to ensure it's secure and ready for users.

## Pre-Publication Security Review

### 1. Git History Audit
- [ ] Review entire git history for accidentally committed secrets
  ```bash
  git log --all --full-history --source -- '*.env*' '*.key' '*.pem'
  ```
- [ ] Check for hardcoded credentials in old commits
  ```bash
  git log -p | grep -i "password\|secret\|api_key\|token" | head -20
  ```
- [ ] If found secrets, rewrite history BEFORE going public (see SETUP_SECURITY.md)

### 2. File Content Review
- [ ] Search all files for placeholder secrets/API keys
  ```bash
  grep -r "AKIA" .  # AWS keys
  grep -r "sk_live" .  # Stripe keys
  grep -r "ghp_" .  # GitHub tokens
  grep -r "password.*=" . --include="*.py"
  ```
- [ ] Review all Python files for hardcoded credentials
- [ ] Check documentation for real URLs, IP addresses, or system paths
- [ ] Verify no PII (Personal Identifiable Information) in examples

### 3. Configuration Files
- [ ] `.gitignore` is present and comprehensive
- [ ] `.gitattributes` is configured
- [ ] `.env.example` has no real values (only placeholders)
- [ ] No `.env` file in repository
- [ ] `LICENSE` file is present with correct copyright holder
- [ ] Update `[Your Name/Organization]` in LICENSE

### 4. Documentation
- [ ] README.md has security warning section
- [ ] SECURITY.md is present and contact info is updated
- [ ] SETUP_SECURITY.md reviewed (maintainer reference)
- [ ] All documentation reviewed for sensitive information
- [ ] Example outputs don't contain real data

### 5. GitHub Repository Settings

#### Before Going Public
- [ ] Review all files one more time
- [ ] Run security scan locally:
  ```bash
  pip install bandit gitleaks
  bandit -r . -f txt
  # Install gitleaks from: https://github.com/gitleaks/gitleaks
  gitleaks detect --source . --verbose
  ```

#### After Repository Creation
- [ ] Go to Settings → General → Features
  - [ ] Enable Issues
  - [ ] Enable Discussions (optional)
  - [ ] Disable Wikis (unless needed)
  - [ ] Disable Projects (unless needed)
  
- [ ] Go to Settings → Security
  - [ ] Enable Dependabot alerts
  - [ ] Enable Dependabot security updates
  - [ ] Enable Secret scanning
  - [ ] Enable Code scanning (if available)
  - [ ] Set up private vulnerability reporting

- [ ] Go to Settings → Branches
  - [ ] Add branch protection rule for `main`:
    - [ ] Require pull request reviews before merging
    - [ ] Require status checks to pass
    - [ ] Require branches to be up to date
    - [ ] Include administrators (optional but recommended)

### 6. GitHub Actions
- [ ] `.github/workflows/security.yml` is present
- [ ] Push a commit to verify workflows run successfully
- [ ] Check Actions tab - all checks should pass
- [ ] Review workflow permissions are minimal

### 7. Code Quality
- [ ] All Python files follow PEP 8
- [ ] Code is well-commented
- [ ] No TODO or FIXME comments with security implications
- [ ] No debug print statements with sensitive data
- [ ] Error messages don't expose system internals

### 8. Dependencies
- [ ] All dependencies are from trusted sources
- [ ] No known vulnerabilities in dependencies
  ```bash
  pip install safety
  safety check
  ```
- [ ] Requirements file is present (if applicable)
- [ ] Dependency versions are pinned or use compatible ranges

### 9. Legal & Compliance
- [ ] LICENSE file is present and appropriate (MIT recommended for open source)
- [ ] Copyright year is correct
- [ ] Copyright holder name is correct
- [ ] No proprietary code included
- [ ] No code copied from restrictive licenses
- [ ] All third-party attributions are present

### 10. User Experience
- [ ] README has clear installation instructions
- [ ] README has usage examples
- [ ] README explains what the tool does
- [ ] Security warnings are prominent
- [ ] Contributing guidelines (optional)
- [ ] Code of conduct (optional but recommended)

## Testing Before Publication

### Local Testing
```bash
# 1. Clone to a fresh directory (simulate new user)
cd /tmp
git clone /path/to/your/repo test-repo
cd test-repo

# 2. Verify gitignore works
echo "SECRET=test" > .env
git status  # Should NOT show .env

# 3. Test the script
# [Add your specific test commands]

# 4. Clean up
cd ..
rm -rf test-repo
```

### Pre-commit Hook Testing (Optional but Recommended)
```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Test all hooks
pre-commit run --all-files

# Should pass without errors
```

## Publication Steps

1. **Final Review**
   - [ ] All items above are checked
   - [ ] One last review of git history
   - [ ] One last grep for common secret patterns

2. **Create Repository on GitHub**
   - [ ] Choose visibility: Public
   - [ ] Add description
   - [ ] Add topics/tags for discoverability
   - [ ] Initialize with README: **NO** (you already have one)

3. **Push to GitHub**
   ```bash
   git remote add origin https://github.com/yourusername/repo-name.git
   git branch -M main
   git push -u origin main
   ```

4. **Post-Publication**
   - [ ] Verify repository is accessible
   - [ ] Check Actions tab - workflows should run
   - [ ] Review repository appearance on GitHub
   - [ ] Test cloning from a different machine
   - [ ] Add repository to your profile/organization

5. **Announce (Optional)**
   - [ ] Share on social media
   - [ ] Post to relevant communities
   - [ ] Add to your portfolio
   - [ ] Submit to package indexes (if applicable)

## Post-Publication Monitoring

### First Week
- [ ] Monitor for any security alerts
- [ ] Check if Actions are passing
- [ ] Review any issues opened
- [ ] Respond to initial feedback

### Ongoing
- [ ] Set up notifications for security alerts
- [ ] Review Dependabot PRs weekly
- [ ] Update dependencies quarterly
- [ ] Review and respond to issues/PRs
- [ ] Keep SECURITY.md updated

## Emergency Procedures

### If a Secret is Discovered After Publication

1. **IMMEDIATELY** rotate/revoke the exposed credential
2. Consider the credential compromised - assume it was accessed
3. Remove from git history:
   ```bash
   # Use BFG Repo-Cleaner or git filter-repo
   git filter-repo --path path/to/secret --invert-paths
   git push --force --all
   ```
4. Notify users via Security Advisory
5. Document the incident
6. Review how it happened and prevent recurrence

### If Malicious Use is Detected

1. Review GitHub security alerts
2. Check repository access logs
3. Contact GitHub Support if needed
4. Document the incident
5. Update security measures

## Resources

- [GitHub Repository Creation](https://docs.github.com/en/repositories/creating-and-managing-repositories)
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [Open Source Guide](https://opensource.guide/)
- [Choosing a License](https://choosealicense.com/)

---

**Remember:** Once published, everything is public. You can't un-publish secrets. Be thorough!

**Date Reviewed:** _______________
**Reviewed By:** _______________
**Publication Date:** _______________