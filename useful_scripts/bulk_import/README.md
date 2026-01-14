# Open Notebook Bulk Import Tool

A secure, production-ready tool for bulk importing markdown files into Open Notebook.

## ⚠️ Security Notice

**Before using this script:**

- Ensure your source directory contains **no sensitive information** (API keys, credentials, PII, etc.)
- The script includes security protections, but YOU are responsible for reviewing your data
- Only works with localhost Open Notebook instances for security
- See [SECURITY.md](SECURITY.md) for detailed security guidelines

---

## 📋 What's Included

**`bulk_import_to_open_notebook.py`** - Bulk import markdown files into Open Notebook via the API.

**Use Case:** Import documentation from a directory into your Open Notebook instance for knowledge management, search, and AI-powered interactions.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Open Notebook running locally (default: http://localhost:5055)
- A notebook ID from your Open Notebook instance

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd ON_Bulk_Import

# Install dependencies
pip install -r requirements.txt

# Or use a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Basic Usage

```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123xyz" \
    --source-dir ./my-documents
```

---

## 📖 Documentation

### Requirements

- **Open Notebook** must be running (default: http://localhost:5055)
- **Notebook ID** - Found in the Open Notebook URL when viewing a notebook
- **Source directory** with markdown files to import

### Usage Examples

**Basic Import:**
```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123xyz" \
    --source-dir ./my-documents
```

**Auto-confirm (skip prompt):**
```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123xyz" \
    --source-dir ./my-documents \
    --yes
```

**Skip Embedding (faster, but no vector search):**
```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123xyz" \
    --source-dir ./my-documents \
    --no-embed
```

**Custom API URL and delay:**
```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123xyz" \
    --source-dir ./my-documents \
    --api-url "http://localhost:5055" \
    --delay 1.0
```

**Get help:**
```bash
python bulk_import_to_open_notebook.py --help
```

### Configuration Options

| Option | Default | Required | Description |
|--------|---------|----------|-------------|
| `--notebook-id` | - | ✅ Yes | Notebook ID to import into (e.g., "notebook:abc123") |
| `--source-dir` | - | ✅ Yes | Directory containing markdown files |
| `--api-url` | `http://localhost:5055` | No | Open Notebook API URL (localhost only) |
| `--pattern` | `*.md` | No | File pattern to match |
| `--no-embed` | `false` | No | Skip embedding (faster, no vector search) |
| `--delay` | `0.5` | No | Delay between imports (seconds) |
| `--yes`, `-y` | `false` | No | Skip confirmation prompt |
| `--transformations` | None | No | Transformation IDs to apply |

### Example Output

```
======================================================================
Open Notebook Bulk Import
======================================================================

Verifying notebook...
✓ Found notebook: My Documentation

Configuration:
  API URL: http://localhost:5055
  Notebook ID: notebook:abc123xyz...
  Source Directory: ./my-documents
  File Pattern: *.md
  Embed Sources: True
  Delay: 0.5s between imports

Security Limits:
  Max file size: 10MB
  Max total size: 500MB
  Max files: 10000

Found 15 files to import

Proceed with import? [y/N]: y

[1/15]   Importing: Getting Started
    ✓ Created source: src_xyz123
[2/15]   Importing: Installation Guide
    ✓ Created source: src_xyz124
[3/15]   Importing: API Reference
    ✓ Created source: src_xyz125
...

======================================================================
Import Complete!
======================================================================
Total files: 15
Successful: 15
Failed: 0

Imported sources:
  1. Getting Started (ID: src_xyz123)
  2. Installation Guide (ID: src_xyz124)
  3. API Reference (ID: src_xyz125)
  ...

You can now view these sources in Open Notebook!
```

---

## 🔒 Security Features

This script includes comprehensive security protections:

### Built-in Safeguards

- ✅ **Localhost Only** - API must be on localhost for security
- ✅ **Path Validation** - Prevents directory traversal attacks
- ✅ **File Size Limits** - 10MB per file, 500MB total
- ✅ **Symlink Protection** - Skips symbolic links
- ✅ **Safe Patterns** - Only allows markdown file patterns (*.md, *.markdown, *.txt)
- ✅ **Max Files Limit** - Prevents processing more than 10,000 files
- ✅ **Input Validation** - Sanitizes notebook IDs and file paths
- ✅ **Privacy Protection** - Doesn't expose full system paths in logs
- ✅ **Error Handling** - Graceful failure without exposing sensitive information

### Security Limits

```
MAX_FILE_SIZE = 10MB       # Maximum size per file
MAX_TOTAL_SIZE = 500MB     # Maximum total import size
MAX_FILES = 10,000         # Maximum number of files
```

### What's Protected Against

- Path traversal attacks (`../../../etc/passwd`)
- Symlink attacks pointing outside the source directory
- Oversized files causing denial of service
- System directory access (`/etc`, `/sys`, etc.)
- Files with dangerous characters in names
- Non-localhost API connections
- Malicious notebook IDs

### Security Checklist

Before running the script:
- [ ] Verify source directory contains no API keys, tokens, or credentials
- [ ] Check for PII or confidential information in markdown files
- [ ] Ensure Open Notebook API is only accessible on localhost
- [ ] Review files to be imported (script shows count before import)
- [ ] Use `--yes` flag only when you've verified the source directory

### For More Details

See [SECURITY.md](SECURITY.md) for:
- Complete security guidelines
- Vulnerability reporting process
- Best practices for users and maintainers
- Detailed threat model

---

## 🧪 Testing

Run the security test suite:

```bash
# Execute all security tests
./test_security.sh

# Expected output:
# ✓ All security tests passed!
```

The test suite validates:
- Path traversal protection
- Symlink protection
- File size limits
- Hidden file exclusion
- Localhost-only API access
- And more...

---

## 🛠️ Development

### Install Development Dependencies

```bash
# Install main dependencies
pip install -r requirements.txt

# Install development tools
pip install pre-commit bandit safety black flake8 isort
```

### Set Up Pre-commit Hooks (Recommended)

```bash
# Install pre-commit
pip install pre-commit

# Install the git hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

Pre-commit hooks automatically check for:
- Secrets and credentials (Gitleaks, detect-secrets)
- Private keys and AWS credentials
- Security issues (Bandit)
- Code quality (Black, flake8, isort)
- File format issues

### Enable Debug Mode

For troubleshooting, set the DEBUG environment variable:

```bash
export DEBUG=1
python bulk_import_to_open_notebook.py --notebook-id "..." --source-dir ./docs
```

This shows full stack traces for errors.

---

## ❓ FAQ

### Q: Is my data sent anywhere?

**A:** No. All processing happens locally on your machine. The only network request is to your local Open Notebook instance (localhost). No data is sent to external services.

### Q: What happens to my files?

**A:** 
- Files are read from your local source directory
- Content is sent to your local Open Notebook instance
- Original files are never modified or deleted
- Nothing is uploaded to external services

### Q: Can I use this with a remote Open Notebook instance?

**A:** No, for security reasons, the script only allows localhost connections. If you need to access a remote Open Notebook instance, use SSH tunneling:

```bash
# On your local machine, create SSH tunnel
ssh -L 5055:localhost:5055 user@remote-server

# Then run the script normally (it connects to localhost:5055)
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:abc123" \
    --source-dir ./docs
```

### Q: What if I have files larger than 10MB?

**A:** Files larger than 10MB are skipped. If you need to import larger files:
1. Split them into smaller chunks (recommended)
2. Modify the `MAX_FILE_SIZE` constant in the script (not recommended for public use)

### Q: How do I get my notebook ID?

**A:** 
1. Open your notebook in Open Notebook
2. Look at the URL in your browser
3. Find the part after `/notebooks/`
4. **Important:** If you see `%3A` in the URL, replace it with `:` (colon)

**Example 1 - Simple URL:**
```
URL: http://localhost:5055/notebooks/notebook:abc123xyz
ID:  notebook:abc123xyz
```

**Example 2 - URL-encoded (most common):**
```
URL: http://127.0.0.1:8502/notebooks/notebook%3A075hgk2qbdgoka54yug5
                                            ↑ This %3A is a colon (:)
ID:  notebook:075hgk2qbdgoka54yug5
     ↑ Use the decoded version with a real colon
```

**Quick Rule:** `%3A` in URLs = `:` (colon) in notebook IDs

📖 **For detailed instructions with more examples, see [NOTEBOOK_ID_GUIDE.md](NOTEBOOK_ID_GUIDE.md)**

### Q: Can I import files with different extensions?

**A:** Yes, but only safe text formats. The `--pattern` option accepts:
- `*.md` (default) - Markdown files
- `*.markdown` - Markdown files with .markdown extension
- `*.txt` - Plain text files

Other patterns are blocked for security.

### Q: What happens if the import is interrupted?

**A:** Files that were successfully imported before the interruption will remain in Open Notebook. You can:
1. Re-run the script (it will create duplicates)
2. Manually check and continue from where it stopped

### Q: Does this create duplicates?

**A:** Yes. The script imports all files it finds, even if they were previously imported. Make sure to avoid running it multiple times on the same directory unless you want duplicates.

---

## 🔧 Troubleshooting

### Common Issues

#### "Security Error: API URL must be localhost"

**Problem:** Trying to connect to a non-localhost API.

**Solution:** The script only allows localhost connections for security. If your Open Notebook is on a remote server, use SSH tunneling:
```bash
ssh -L 5055:localhost:5055 user@remote-server
```

#### "Notebook not found" or "Error checking notebook"

**Problem:** Invalid notebook ID or Open Notebook not running.

**Solutions:**
1. Make sure Open Notebook is running at the API URL (default: http://localhost:5055)
2. Verify your notebook ID is correct (see FAQ above)
3. Check if you need to decode `%3A` to `:` in the notebook ID
4. Verify the notebook exists by opening it in your browser first

#### "Source directory does not exist"

**Problem:** The path you provided doesn't exist.

**Solutions:**
1. Use absolute paths: `/Users/username/documents` instead of `~/documents`
2. Check for typos in the path
3. Ensure the directory exists: `ls -la /path/to/directory`

#### "File too large" or "Total size limit exceeded"

**Problem:** Files exceed security limits (10MB per file, 500MB total).

**Solutions:**
1. Split large files into smaller chunks
2. Import in batches (multiple runs with different source directories)
3. Remove oversized files from the source directory

#### Script hangs or is very slow

**Problem:** Many files or slow embedding process.

**Solutions:**
1. Use `--no-embed` flag to skip embedding (much faster)
2. Increase `--delay` if API is being overwhelmed
3. Process files in smaller batches

#### "Invalid file pattern"

**Problem:** Using a pattern other than `*.md`, `*.markdown`, or `*.txt`.

**Solution:** The script only accepts markdown and text files for security. Convert other formats to markdown first.

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Review [SECURITY.md](SECURITY.md) for security guidelines
2. Run security tests before submitting: `./test_security.sh`
3. Use pre-commit hooks for code quality
4. Include tests for new features
5. Update documentation

### Reporting Security Issues

**IMPORTANT:** If you find security vulnerabilities, see [SECURITY.md](SECURITY.md) for responsible disclosure guidelines. 

**DO NOT** open public issues for security vulnerabilities.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [Open Notebook](https://github.com/opennotebook/opennotebook) team for the excellent documentation tool
- Security scanning tools: Bandit, Safety, GitLeaks, TruffleHog, detect-secrets
- Python community for excellent libraries and tools

---

## 📚 Additional Resources

- [Open Notebook Documentation](https://github.com/opennotebook/opennotebook)
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [OWASP Secure Coding Practices](https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)

---

## 📦 Version

**Current Version:** v1.0.0  
**Status:** ✅ Production Ready | 🔒 Security Hardened

---

## 🆘 Support

- **Issues:** [GitHub Issues](https://github.com/yourusername/ON_Bulk_Import/issues)
- **Security:** See [SECURITY.md](SECURITY.md)
- **Documentation:** This README and inline code comments

---

**Made with ❤️ for the Open Notebook community**