# Quick Guide: Finding Your Notebook ID

## The Problem: URL Encoding

When you look at your notebook URL in the browser, you'll see special characters encoded. The most common is the colon (`:`) which appears as `%3A`.

## Step-by-Step Guide

### 1. Find Your Notebook URL

Open your notebook in Open Notebook and look at the address bar:

```
http://127.0.0.1:8502/notebooks/notebook%3A075hgk2qbdgoka54yug5
```

### 2. Extract the Notebook ID Part

Take everything after `/notebooks/`:

```
notebook%3A075hgk2qbdgoka54yug5
```

### 3. Decode URL Encoding

Replace `%3A` with `:` (colon):

```
notebook:075hgk2qbdgoka54yug5
```

✅ This is your notebook ID!

## Common URL Encodings

| Encoded | Decoded | Character |
|---------|---------|-----------|
| `%3A` | `:` | Colon |
| `%2F` | `/` | Slash |
| `%20` | ` ` | Space |
| `%2B` | `+` | Plus |

## Quick Reference

```
❌ WRONG: notebook%3A075hgk2qbdgoka54yug5  (URL-encoded)
✅ RIGHT: notebook:075hgk2qbdgoka54yug5    (Decoded)
```

## Examples

### Example 1: Standard Format
```
URL: http://localhost:5055/notebooks/notebook:abc123xyz
ID:  notebook:abc123xyz
```
No decoding needed! The URL already shows the colon.

### Example 2: URL-Encoded (Most Common)
```
URL: http://127.0.0.1:8502/notebooks/notebook%3A075hgk2qbdgoka54yug5
ID:  notebook:075hgk2qbdgoka54yug5
```
Decode `%3A` → `:`

### Example 3: Complex ID
```
URL: http://localhost:5055/notebooks/notebook%3Aabc123%2Fxyz789
ID:  notebook:abc123/xyz789
```
Decode `%3A` → `:` and `%2F` → `/`

## Usage in Script

Once you have your decoded notebook ID:

```bash
python bulk_import_to_open_notebook.py \
    --notebook-id "notebook:075hgk2qbdgoka54yug5" \
    --source-dir ./my-documents
```

## Testing Your Notebook ID

The script will verify your notebook exists when you run it:

```
Verifying notebook...
✓ Found notebook: My Documentation
```

If you see an error, double-check:
1. Is Open Notebook running?
2. Did you decode `%3A` to `:`?
3. Did you copy the entire ID including `notebook:`?
4. Is the notebook actually in that API instance?

## Pro Tip: Copy from Browser's Developer Tools

For guaranteed accuracy:

1. Open Developer Tools (F12)
2. Go to Network tab
3. Click on a notebook request
4. Look at the Request URL
5. The notebook ID will be clearly visible

Or simply use the browser's address bar and do the `%3A` → `:` replacement!

---

**Need more help?** See the Troubleshooting section in [README.md](README.md)
