# opennotebook_import.sh — How it works

This script uploads all PDF files from a directory to an Open Notebook server into a single target notebook. It talks directly to the backend REST API using `curl`.

Key behavior
- Scans for `*.pdf` either in the specified directory (default: current) or recursively if `-recursive` is set.
- Resolves the notebook ID by name (`GET /api/notebooks`).
- Optional token authentication using `Authorization: Bearer <token>`. Provide with `-token=` or set `OPEN_NOTEBOOK_TOKEN`.
- Uploads each PDF via `POST /api/sources` using multipart form:
  - `type=upload`
  - `file=@<path>`
  - `notebooks=["<NOTEBOOK_ID>"]`
  - `title=<derived from filename>`
  - `embed=<true|false>`
  - `async_processing=<true|false>`
- Duplicate handling:
  - If a filename base matches an existing source title in the notebook or a previous file in the same run, the script appends `_1` to the title it sends (does not rename your local file).
  - All duplicates are listed in a final summary.
- Error reporting:
  - Collects HTTP status codes and any response body for failures, summarized at the end.
- Dry run:
  - With `-dry-run`, the script does not upload. It still attempts to query the server to resolve the notebook and detect duplicates (if reachable) and prints what would happen.

Usage examples
- Dry run from current directory into notebook `service_kb_new` on a custom host:
  ```
  ./opennotebook_import.sh -server=http://100.77.164.86:5005 -notebook=service_kb_new -dry-run
  ```
- Real upload from a specific directory, with token auth, embedding enabled and async processing:
  ```
  OPEN_NOTEBOOK_TOKEN=******** \
  ./opennotebook_import.sh -server=http://100.77.164.86:5005 -notebook=service_kb_new -dir="/path/to/PDF" -embed=true -async=true
  ```
- Recurse into subdirectories:
  ```
  ./opennotebook_import.sh -server=http://100.77.164.86:5005 -notebook=my_kb -dir="/data/pdfs" -recursive
  ```

Notes
- Base URL must be the server root (e.g., `http://IP:5005`). The script adds `/api` to reach endpoints.
- Authentication is optional depending on your server configuration. If enabled, supply a token with `-token=` or `OPEN_NOTEBOOK_TOKEN`.
- The script derives `title` from the filename without `.pdf`. Duplicate titles in the same run or already present on the server are sent as `<title>_1`.
- The server may still apply its own unique filename rules; this script’s `_1` suffix ensures duplicates are clearly reported in the summary.
