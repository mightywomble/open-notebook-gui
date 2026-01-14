# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it by:

1. **DO NOT** open a public issue
2. Email the maintainer directly (check the repository for contact information)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond as quickly as possible and work with you to address the issue.

## Security Best Practices for Users

### 1. Protect Your Data

- **Never commit sensitive files**: Ensure your `docs/` folder doesn't contain:
  - API keys, tokens, or credentials
  - Personal identifiable information (PII)
  - Proprietary or confidential information
  - Private keys or certificates

### 2. Review Before Running

- Always review the script before running it on your documentation
- Check what files will be processed: the script scans all `.md` files in `docs/` subdirectories
- Verify the output in `doc_exports/` before sharing

### 3. Environment Setup

- Use a virtual environment for running this script
- Keep your Python installation and dependencies up to date
- Review the code if you're processing sensitive documentation

### 4. Output Handling

- The `doc_exports/` directory is gitignored by default
- **Verify your `.gitignore` is working** before committing
- Review consolidated files before uploading them anywhere
- Be aware that consolidating documents may expose information you intended to keep separate

### 5. Public Sharing

If sharing exported documentation publicly:
- Remove any internal references, URLs, or system paths
- Sanitize examples that might contain real data
- Review for accidentally included credentials or secrets
- Consider if the consolidated view reveals information architecture you want to keep private

## Known Limitations

- This script does not encrypt or redact any content
- It processes files as plain text without security scanning
- It's the user's responsibility to ensure source documentation is safe to consolidate and share

## Supported Versions

This is a simple utility script. Always use the latest version from the main branch.

## Security Updates

Security-related updates will be noted in release notes and commit messages with a `[SECURITY]` prefix.