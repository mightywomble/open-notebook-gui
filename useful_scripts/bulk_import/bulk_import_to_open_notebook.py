#!/usr/bin/env python3
"""
Bulk Import Files to Open Notebook

This script imports markdown files into Open Notebook using the Open Notebook API.

Usage:
    python bulk_import_to_open_notebook.py --notebook-id <id> --source-dir <path> [options]

    # Get your notebook ID from Open Notebook UI (it's in the URL when viewing a notebook)
    python bulk_import_to_open_notebook.py \
        --notebook-id "notebook:abc123" \
        --source-dir "./documents" \
        --api-url "http://localhost:5055"

Requirements:
    - Open Notebook must be running locally
    - You need the notebook ID where you want to import the files
    - The API must be accessible (default: http://localhost:5055)

Security:
    - Only imports from local directories
    - Validates all file paths to prevent directory traversal
    - Enforces file size limits (10MB per file, 500MB total)
    - API should only be accessed on localhost for security
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Configuration - Edit this to match your Open Notebook server
DEFAULT_API_URL = "http://localhost:5055"  # Change this for remote/hosted instances

# ANSI color codes
BLUE = "\033[94m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Security limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
MAX_TOTAL_SIZE = 500 * 1024 * 1024  # 500MB total
MAX_FILES = 10000  # Maximum number of files to process


class SecurityError(Exception):
    """Raised when a security constraint is violated."""

    pass


class OpenNotebookImporter:
    """Import markdown files into Open Notebook."""

    def __init__(self, api_url: str, notebook_id: str):
        """
        Initialize the importer.

        Args:
            api_url: Base URL of Open Notebook API (e.g., http://localhost:5055)
            notebook_id: ID of the notebook to import into

        Raises:
            SecurityError: If API URL or notebook ID are invalid
        """
        # Validate API URL
        self._validate_api_url(api_url)
        self.api_url = api_url.rstrip("/")

        # Validate notebook ID
        self._validate_notebook_id(notebook_id)
        self.notebook_id = notebook_id

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
            }
        )
        self.total_size_processed = 0

    @staticmethod
    def _validate_api_url(api_url: str) -> None:
        """Validate API URL is localhost only for security."""
        if not api_url:
            raise SecurityError("API URL cannot be empty")

        # Parse URL
        from urllib.parse import urlparse

        parsed = urlparse(api_url)

        # Only allow localhost/127.0.0.1 for security unless overridden
        if os.environ.get("ONBULK_ALLOW_REMOTE") == "1":
            return
        allowed_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
        if parsed.hostname and parsed.hostname.lower() not in allowed_hosts:
            raise SecurityError(
                f"API URL must be localhost for security. Got: {parsed.hostname}\n"
                f"If you need remote access, use SSH tunneling."
            )

    @staticmethod
    def _validate_notebook_id(notebook_id: str) -> None:
        """Validate notebook ID format."""
        if not notebook_id:
            raise SecurityError("Notebook ID cannot be empty")

        # Basic format validation
        if len(notebook_id) > 100:
            raise SecurityError("Notebook ID too long")

        # Check for suspicious characters
        dangerous_chars = {"\0", "\n", "\r", "<", ">", "|"}
        if any(char in notebook_id for char in dangerous_chars):
            raise SecurityError("Notebook ID contains invalid characters")

    @staticmethod
    def _validate_file_path(file_path: Path, base_dir: Path) -> None:
        """
        Validate file path is safe and within base directory.

        Args:
            file_path: File path to validate
            base_dir: Base directory file should be within

        Raises:
            SecurityError: If path is unsafe
        """
        try:
            # Resolve to absolute paths
            resolved_file = file_path.resolve()
            resolved_base = base_dir.resolve()

            # Check if file is within base directory
            if not str(resolved_file).startswith(str(resolved_base)):
                raise SecurityError(
                    f"File path escapes base directory: {file_path.name}"
                )

            # Check if it's a symlink
            if file_path.is_symlink():
                raise SecurityError(f"Symlinks not allowed: {file_path.name}")

        except (OSError, RuntimeError) as e:
            raise SecurityError(f"Invalid file path: {e}")

    @staticmethod
    def _validate_file_size(file_path: Path) -> int:
        """
        Validate file size is within limits.

        Args:
            file_path: Path to file

        Returns:
            File size in bytes

        Raises:
            SecurityError: If file is too large
        """
        try:
            size = file_path.stat().st_size
            if size > MAX_FILE_SIZE:
                raise SecurityError(
                    f"File too large: {file_path.name} "
                    f"({size / 1024 / 1024:.1f}MB > {MAX_FILE_SIZE / 1024 / 1024:.1f}MB)"
                )
            return size
        except OSError as e:
            raise SecurityError(f"Cannot stat file {file_path.name}: {e}")

    def verify_notebook_exists(self) -> bool:
        """Verify that the notebook exists."""
        try:
            response = self.session.get(
                f"{self.api_url}/api/notebooks/{self.notebook_id}"
            )
            if response.status_code == 200:
                notebook_data = response.json()
                print(
                    f"{GREEN}✓ Found notebook: {notebook_data.get('name', 'Unknown')}{RESET}"
                )
                return True
            elif response.status_code == 404:
                print(f"{RED}✗ Notebook not found: {self.notebook_id}{RESET}")
                return False
            else:
                print(f"{RED}✗ Error checking notebook: {response.status_code}{RESET}")
                print(f"{RED}  Response: {response.text}{RESET}")
                return False
        except Exception as e:
            print(f"{RED}✗ Error connecting to Open Notebook API: {e}{RESET}")
            return False

    def import_file(
        self,
        file_path: Path,
        base_dir: Path,
        embed: bool = True,
        transformations: Optional[List[str]] = None,
        delay: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Import a single markdown file as a source.

        Args:
            file_path: Path to the markdown file
            base_dir: Base directory for path validation
            embed: Whether to embed the source
            transformations: List of transformation IDs to apply
            delay: Delay after import in seconds

        Returns:
            Source data dict if successful, None otherwise
        """
        try:
            # Validate file path
            self._validate_file_path(file_path, base_dir)

            # Validate and track file size
            file_size = self._validate_file_size(file_path)

            # Check total size limit
            if self.total_size_processed + file_size > MAX_TOTAL_SIZE:
                raise SecurityError(
                    f"Total size limit exceeded "
                    f"({(self.total_size_processed + file_size) / 1024 / 1024:.1f}MB > "
                    f"{MAX_TOTAL_SIZE / 1024 / 1024:.1f}MB)"
                )

            # Read the file content with error handling
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError as e:
                print(
                    f"{RED}    ✗ Cannot read file (encoding error): {file_path.name}{RESET}"
                )
                return None

            # Extract title from filename (sanitize)
            title = file_path.stem[:200]  # Limit title length

            print(f"{BLUE}  Importing: {title}{RESET}")

            # Prepare form data for multipart/form-data request
            form_data = {
                "type": "text",
                "title": title,
                "content": content,
                "embed": str(embed).lower(),  # Convert bool to string "true"/"false"
                "async_processing": "true",  # Use async to avoid event loop issues
            }

            # Add notebook ID(s)
            import json

            form_data["notebooks"] = json.dumps([self.notebook_id])

            # Add transformations if specified
            if transformations:
                form_data["transformations"] = json.dumps(transformations)

            # Send the request using form data instead of JSON
            response = self.session.post(
                f"{self.api_url}/api/sources",
                data=form_data,
                timeout=60,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                source_id = result.get("id", "unknown")
                print(f"{GREEN}    ✓ Created source: {source_id}{RESET}")

                # Track successful size
                self.total_size_processed += file_size

                # Add delay to avoid overwhelming the API
                if delay > 0:
                    time.sleep(delay)

                return result
            else:
                print(f"{RED}    ✗ Failed: {response.status_code}{RESET}")
                # Sanitize error message - don't expose full response
                error_msg = response.text[:100] if response.text else "No error message"
                print(f"{RED}      Error: {error_msg}{RESET}")
                return None

        except SecurityError as e:
            print(f"{RED}    ✗ Security Error: {e}{RESET}")
            return None
        except Exception as e:
            print(f"{RED}    ✗ Error: {type(e).__name__}{RESET}")
            return None

    def import_directory(
        self,
        directory: Path,
        embed: bool = True,
        transformations: Optional[List[str]] = None,
        delay: float = 1.0,
        pattern: str = "*.md",
        recursive: bool = False,
    ) -> Dict[str, Any]:
        """
        Import all markdown files from a directory.

        Args:
            directory: Path to directory containing markdown files
            embed: Whether to embed the sources
            transformations: List of transformation IDs to apply
            delay: Delay between imports in seconds
            pattern: File pattern to match (default: *.md)
            recursive: Search subdirectories recursively

        Returns:
            Dict with import statistics

        Raises:
            SecurityError: If security constraints are violated
        """
        # Validate pattern
        if pattern not in ["*.md", "*.markdown", "*.txt"]:
            raise SecurityError(
                f"Invalid file pattern: {pattern}. Only markdown files allowed."
            )

        # Get markdown files
        try:
            if recursive:
                all_files = list(directory.rglob(pattern))
            else:
                all_files = list(directory.glob(pattern))
        except Exception as e:
            print(f"{RED}Error scanning directory: {e}{RESET}")
            return {"total": 0, "success": 0, "failed": 0}

        # Filter to regular files only (no symlinks, no directories)
        markdown_files = [f for f in all_files if f.is_file() and not f.is_symlink()]

        if not markdown_files:
            print(f"{YELLOW}No markdown files found{RESET}")
            return {"total": 0, "success": 0, "failed": 0}

        # Check file count limit
        if len(markdown_files) > MAX_FILES:
            raise SecurityError(
                f"Too many files to process: {len(markdown_files)} > {MAX_FILES}"
            )

        print(f"{BLUE}Found {len(markdown_files)} markdown files to import{RESET}\n")

        stats = {"total": len(markdown_files), "success": 0, "failed": 0, "sources": []}

        for i, file_path in enumerate(markdown_files, 1):
            print(f"{BLUE}[{i}/{len(markdown_files)}]{RESET}", end=" ")

            result = self.import_file(
                file_path=file_path,
                base_dir=directory,
                embed=embed,
                transformations=transformations,
                delay=delay,
            )

            if result:
                stats["success"] += 1
                stats["sources"].append(
                    {
                        "file": file_path.name,
                        "id": result.get("id"),
                        "title": result.get("title"),
                    }
                )
            else:
                stats["failed"] += 1

        return stats



def resolve_notebook_id_by_name(api_url: str, name: str) -> str | None:
    """Resolve a notebook ID from its name using the API."""
    try:
        url = f"{api_url.rstrip('/')}/api/notebooks"
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code != 200:
            print(f"{RED}✗ Error listing notebooks: {resp.status_code}{RESET}")
            try:
                print(f"{RED}  Response: {resp.text[:200]}{RESET}")
            except Exception:
                pass
            return None
        for nb in resp.json() or []:
            if nb.get('name') == name:
                return nb.get('id')
        print(f"{RED}✗ Notebook not found by name: {name}{RESET}")
        return None
    except Exception as e:
        print(f"{RED}✗ Error connecting to Open Notebook API: {e}{RESET}")
        return None

def main():
    parser = argparse.ArgumentParser(
        description="Bulk import markdown files into Open Notebook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments (mutually exclusive: ID or name)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--notebook-id", help='Notebook ID to import into (e.g., "notebook:abc123")')
    group.add_argument("--notebook-name", help="Notebook name to import into (will be resolved via API)")

    parser.add_argument(
        "--source-dir",
        required=True,
        help="Directory containing markdown files to import",
    )

    # Optional arguments
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Open Notebook API URL (default: {DEFAULT_API_URL})",
    )

    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow non-localhost API URL (override security check)",
    )

    parser.add_argument(
        "--pattern",
        default="*.md",
        help="File pattern to match (default: *.md)",
    )

    parser.add_argument(
        "-R",
        "--recursive",
        action="store_true",
        help="Search subdirectories recursively",
    )

    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding sources (faster but no vector search)",
    )

    parser.add_argument(
        "--transformations",
        nargs="+",
        help="Transformation IDs to apply to each source",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between imports in seconds (default: 0.5)",
    )

    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )

    args = parser.parse_args()

    # Validate source directory
    try:
        source_dir = Path(args.source_dir).resolve()
        # Allow remote API if requested
        if getattr(args, "allow-remote", False) or getattr(args, "allow_remote", False):
            os.environ["ONBULK_ALLOW_REMOTE"] = "1"

        # Resolve notebook ID if only name provided
        if getattr(args, "notebook_name", None) and not getattr(args, "notebook_id", None):
            resolved = resolve_notebook_id_by_name(args.api_url, args.notebook_name)
            if not resolved:
                sys.exit(1)
            args.notebook_id = resolved
    except Exception as e:
        print(f"{RED}Error: Invalid source directory path: {e}{RESET}")
        sys.exit(1)

    if not source_dir.exists():
        print(f"{RED}Error: Source directory does not exist{RESET}")
        sys.exit(1)

    if not source_dir.is_dir():
        print(f"{RED}Error: Source path is not a directory{RESET}")
        sys.exit(1)

    # Validate source directory is not a system directory
    system_dirs = {"/", "/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc"}
    if str(source_dir) in system_dirs or str(source_dir).startswith("/etc/"):
        print(f"{RED}Error: Cannot import from system directories{RESET}")
        sys.exit(1)

    # Print banner
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}Open Notebook Bulk Import{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")

    # Initialize importer
    try:
        importer = OpenNotebookImporter(
            api_url=args.api_url, notebook_id=args.notebook_id
        )
    except SecurityError as e:
        print(f"{RED}Security Error: {e}{RESET}")
        sys.exit(1)

    # Verify notebook exists
    print(f"{BLUE}Verifying notebook...{RESET}")
    if not importer.verify_notebook_exists():
        print(f"\n{RED}Cannot proceed without a valid notebook.{RESET}")
        print(
            f"{YELLOW}Please check your notebook ID and ensure Open Notebook is running.{RESET}"
        )
        sys.exit(1)

    print()

    # Display configuration (sanitized)
    print(f"{BLUE}Configuration:{RESET}")
    print(f"  API URL: {args.api_url}")
    print(f"  Notebook ID: {args.notebook_id[:50]}...")  # Truncate for display
    print(f"  Source Directory: {args.source_dir}")  # Use arg, not resolved path
    print(f"  File Pattern: {args.pattern}")
    print(f"  Recursive Search: {args.recursive}")
    print(f"  Embed Sources: {not args.no_embed}")
    if args.transformations:
        print(f"  Transformations: {', '.join(args.transformations)}")
    print(f"  Delay: {args.delay}s between imports")
    print()

    # Display security limits
    print(f"{BLUE}Security Limits:{RESET}")
    print(f"  Max file size: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB")
    print(f"  Max total size: {MAX_TOTAL_SIZE / 1024 / 1024:.0f}MB")
    print(f"  Max files: {MAX_FILES}")
    print()

    # Count files
    if args.recursive:
        markdown_files = list(source_dir.rglob(args.pattern))
    else:
        markdown_files = list(source_dir.glob(args.pattern))
    print(f"{BLUE}Found {len(markdown_files)} files to import{RESET}")

    if not markdown_files:
        print(f"{YELLOW}No files to import. Exiting.{RESET}")
        sys.exit(0)

    print()

    # Confirm
    if not args.yes:
        try:
            response = input(f"{YELLOW}Proceed with import? [y/N]: {RESET}")
            if response.lower() not in ["y", "yes"]:
                print(f"{YELLOW}Import cancelled.{RESET}")
                sys.exit(0)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Import cancelled.{RESET}")
            sys.exit(0)
        print()
    else:
        print(f"{GREEN}Auto-confirming import (--yes flag provided){RESET}\n")

    # Perform import
    try:
        stats = importer.import_directory(
            directory=source_dir,
            embed=not args.no_embed,
            transformations=args.transformations,
            delay=args.delay,
            pattern=args.pattern,
            recursive=args.recursive,
        )
    except SecurityError as e:
        print(f"\n{RED}Security Error: {e}{RESET}")
        sys.exit(1)

        # Print summary
        print(f"\n{BLUE}{'=' * 70}{RESET}")
        print(f"{GREEN}Import Complete!{RESET}")
        print(f"{BLUE}{'=' * 70}{RESET}")
        print(f"{GREEN}Total files: {stats['total']}{RESET}")
        print(f"{GREEN}Successful: {stats['success']}{RESET}")
        if stats["failed"] > 0:
            print(f"{RED}Failed: {stats['failed']}{RESET}")
        print()

        if stats["sources"]:
            print(f"{BLUE}Imported sources:{RESET}")
            for i, source in enumerate(stats["sources"][:10], 1):
                print(f"  {i}. {source['title']} (ID: {source['id']})")

            if len(stats["sources"]) > 10:
                print(f"  ... and {len(stats['sources']) - 10} more")

        print()
        print(f"{GREEN}You can now view these sources in Open Notebook!{RESET}")
        print()

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Import interrupted.{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Import failed: {type(e).__name__}{RESET}")
        # Only show traceback in debug mode
        if os.getenv("DEBUG"):
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
