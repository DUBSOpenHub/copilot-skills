#!/usr/bin/env python3
"""
Google Docs/Slides/Sheets → Microsoft Office converter.

Usage:
  python3 convert.py <google_url> [--output-dir <dir>]
  python3 convert.py --auth-setup          # One-time OAuth setup for private docs

Supports:
  - Google Docs  → Word (.docx)
  - Google Slides → PowerPoint (.pptx)
  - Google Sheets → Excel (.xlsx)
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Google API imports (for private docs)
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

# --- Configuration ---
CONFIG_DIR = Path.home() / ".config" / "gdoc-converter"
TOKEN_PATH = CONFIG_DIR / "token.json"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# --- URL Parsing ---

# Maps Google MIME types to export MIME types and file extensions
EXPORT_MAP = {
    "document": {
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ext": ".docx",
        "label": "Word",
    },
    "spreadsheets": {
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ext": ".xlsx",
        "label": "Excel",
    },
    "presentation": {
        "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ext": ".pptx",
        "label": "PowerPoint",
    },
}

# Google MIME type string → our key
GOOGLE_MIME_TO_KEY = {
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.spreadsheet": "spreadsheets",
    "application/vnd.google-apps.presentation": "presentation",
}

# URL patterns for Google Workspace files
URL_PATTERNS = [
    # docs.google.com/document/d/FILE_ID/...
    re.compile(r"docs\.google\.com/(document)/d/([a-zA-Z0-9_-]+)"),
    # docs.google.com/spreadsheets/d/FILE_ID/...
    re.compile(r"docs\.google\.com/(spreadsheets)/d/([a-zA-Z0-9_-]+)"),
    # docs.google.com/presentation/d/FILE_ID/...
    re.compile(r"docs\.google\.com/(presentation)/d/([a-zA-Z0-9_-]+)"),
    # drive.google.com/file/d/FILE_ID/...
    re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"),
    # drive.google.com/open?id=FILE_ID
    re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"),
]


def parse_google_url(url):
    """Extract file ID and doc type from a Google URL.
    
    Returns (file_id, doc_type) where doc_type is 'document', 'spreadsheets', 
    or 'presentation'. For drive.google.com URLs, doc_type is None (must be 
    detected via API).
    """
    url = url.strip()
    
    for pattern in URL_PATTERNS:
        match = pattern.search(url)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return groups[1], groups[0]  # (file_id, doc_type)
            else:
                return groups[0], None  # (file_id, unknown type)
    
    # Try to extract a bare file ID (44-char alphanumeric string)
    bare_id = re.match(r"^([a-zA-Z0-9_-]{20,})$", url)
    if bare_id:
        return bare_id.group(1), None
    
    return None, None


def get_file_title_public(file_id):
    """Try to get the file title from public metadata."""
    try:
        api_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=name&key="
        # Without an API key, this won't work for most files
        # Fall back to using the file ID as the name
        return None
    except Exception:
        return None


def sanitize_filename(name):
    """Remove characters that are problematic in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name if name else "converted"


# --- Public Doc Export (no auth needed) ---

def export_public(file_id, doc_type, output_dir):
    """Export a publicly shared Google Doc using the direct export URL."""
    if doc_type not in EXPORT_MAP:
        print(f"❌ Unknown document type: {doc_type}")
        print("   Supported types: document (Docs), spreadsheets (Sheets), presentation (Slides)")
        sys.exit(1)
    
    export_info = EXPORT_MAP[doc_type]
    
    # Google's public export URL pattern
    if doc_type == "spreadsheets":
        export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    elif doc_type == "document":
        export_url = f"https://docs.google.com/document/d/{file_id}/export?format=docx"
    elif doc_type == "presentation":
        export_url = f"https://docs.google.com/presentation/d/{file_id}/export?format=pptx"
    
    print(f"📄 Exporting as {export_info['label']} ({export_info['ext']})...")
    print(f"   Source: https://docs.google.com/{doc_type}/d/{file_id}")
    
    try:
        req = urllib.request.Request(export_url, headers={
            "User-Agent": "Mozilla/5.0 (gdoc-converter/1.0)"
        })
        response = urllib.request.urlopen(req, timeout=60)
        content = response.read()
        
        if len(content) < 100:
            # Likely an error page, not a real document
            print("❌ Export failed — the document may be private or the URL may be incorrect.")
            print("   For private docs, run: python3 convert.py --auth-setup")
            sys.exit(1)
        
        # Try to get filename from Content-Disposition header
        cd = response.headers.get("Content-Disposition", "")
        filename_match = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)', cd)
        if filename_match:
            filename = urllib.request.url2pathname(filename_match.group(1)).strip()
            # Ensure correct extension
            if not filename.endswith(export_info["ext"]):
                filename = Path(filename).stem + export_info["ext"]
        else:
            filename = f"{file_id}{export_info['ext']}"
        
        filename = sanitize_filename(filename)
        output_path = Path(output_dir) / filename
        
        # Avoid overwriting
        if output_path.exists():
            stem = output_path.stem
            suffix = output_path.suffix
            counter = 1
            while output_path.exists():
                output_path = Path(output_dir) / f"{stem} ({counter}){suffix}"
                counter += 1
        
        output_path.write_bytes(content)
        size_kb = len(content) / 1024
        
        print(f"✅ Saved: {output_path}")
        print(f"   Size: {size_kb:.1f} KB")
        return str(output_path)
        
    except urllib.error.HTTPError as e:
        if e.code == 401 or e.code == 403:
            print("🔒 Document is private. You need to authenticate first.")
            print("   Run: python3 convert.py --auth-setup")
        elif e.code == 404:
            print("❌ Document not found. Check the URL and make sure it exists.")
        else:
            print(f"❌ HTTP Error {e.code}: {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ Network error: {e.reason}")
        sys.exit(1)


# --- Private Doc Export (OAuth required) ---

def get_credentials():
    """Get or refresh OAuth credentials."""
    creds = None
    
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                print("❌ No credentials.json found.")
                print(f"   Expected at: {CREDENTIALS_PATH}")
                print()
                print("To set up authentication:")
                print("1. Go to https://console.cloud.google.com/apis/credentials")
                print("2. Create a project (or use an existing one)")
                print("3. Enable the Google Drive API")
                print("4. Create OAuth 2.0 Client ID (Desktop application)")
                print("5. Download the JSON and save it as:")
                print(f"   {CREDENTIALS_PATH}")
                print("6. Run: python3 convert.py --auth-setup")
                sys.exit(1)
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        TOKEN_PATH.write_text(creds.to_json())
    
    return creds


def export_private(file_id, doc_type, output_dir):
    """Export a private Google Doc using the Drive API with OAuth."""
    if not HAS_GOOGLE_API:
        print("❌ Google API libraries not installed.")
        print("   Run: pip3 install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        sys.exit(1)
    
    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)
    
    # Get file metadata
    try:
        file_meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    except Exception as e:
        print(f"❌ Could not access file: {e}")
        sys.exit(1)
    
    file_name = file_meta["name"]
    mime_type = file_meta["mimeType"]
    
    # Determine export type from MIME type (overrides URL-based detection)
    key = GOOGLE_MIME_TO_KEY.get(mime_type)
    if not key:
        # Not a Google Workspace file — try direct download
        print(f"⚠️  '{file_name}' is not a Google Workspace file (type: {mime_type})")
        print("   Direct download of non-Google files is not yet supported.")
        sys.exit(1)
    
    export_info = EXPORT_MAP[key]
    print(f"📄 '{file_name}' → {export_info['label']} ({export_info['ext']})")
    
    # Export via API
    import io
    request = service.files().export_media(
        fileId=file_id, mimeType=export_info["mime"]
    )
    
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"   Downloading... {pct}%", end="\r")
    
    print()
    
    filename = sanitize_filename(file_name) + export_info["ext"]
    output_path = Path(output_dir) / filename
    
    # Avoid overwriting
    if output_path.exists():
        stem = output_path.stem
        suffix = output_path.suffix
        counter = 1
        while output_path.exists():
            output_path = Path(output_dir) / f"{stem} ({counter}){suffix}"
            counter += 1
    
    output_path.write_bytes(buffer.getvalue())
    size_kb = len(buffer.getvalue()) / 1024
    
    print(f"✅ Saved: {output_path}")
    print(f"   Size: {size_kb:.1f} KB")
    return str(output_path)


def auth_setup():
    """Run the one-time OAuth setup flow."""
    print("🔐 Google Drive OAuth Setup")
    print("=" * 40)
    
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if not CREDENTIALS_PATH.exists():
        print()
        print("Step 1: Get your credentials.json")
        print("-" * 40)
        print("1. Go to: https://console.cloud.google.com/apis/credentials")
        print("2. Create a project (or select an existing one)")
        print("3. Enable 'Google Drive API' under APIs & Services → Library")
        print("4. Go to APIs & Services → Credentials")
        print("5. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'")
        print("6. Application type: 'Desktop app'")
        print("7. Download the JSON file")
        print(f"8. Save it as: {CREDENTIALS_PATH}")
        print()
        print(f"Then run this command again: python3 {sys.argv[0]} --auth-setup")
        sys.exit(0)
    
    print("Found credentials.json. Starting OAuth flow...")
    print("A browser window will open for you to authorize access.")
    print()
    
    creds = get_credentials()
    
    if creds and creds.valid:
        print("✅ Authentication successful!")
        print(f"   Token saved to: {TOKEN_PATH}")
        print()
        print("You can now convert private Google Docs:")
        print(f"   python3 {sys.argv[0]} <google_url>")
    else:
        print("❌ Authentication failed. Please try again.")
        sys.exit(1)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Convert Google Docs/Slides/Sheets to Microsoft Office formats"
    )
    parser.add_argument("url", nargs="?", help="Google Doc/Slides/Sheets URL or file ID")
    parser.add_argument("--output-dir", "-o", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--auth-setup", action="store_true",
                        help="Set up OAuth for private docs")
    parser.add_argument("--private", "-p", action="store_true",
                        help="Force private doc mode (use OAuth)")
    
    args = parser.parse_args()
    
    if args.auth_setup:
        auth_setup()
        return
    
    if not args.url:
        parser.print_help()
        sys.exit(1)
    
    # Parse the URL
    file_id, doc_type = parse_google_url(args.url)
    
    if not file_id:
        print("❌ Could not extract a file ID from that URL.")
        print("   Supported URL formats:")
        print("   • https://docs.google.com/document/d/FILE_ID/...")
        print("   • https://docs.google.com/spreadsheets/d/FILE_ID/...")
        print("   • https://docs.google.com/presentation/d/FILE_ID/...")
        print("   • https://drive.google.com/file/d/FILE_ID/...")
        print("   • https://drive.google.com/open?id=FILE_ID")
        sys.exit(1)
    
    # Ensure output directory exists
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # If doc_type is unknown (drive.google.com URL) or --private flag, use API
    if doc_type is None or args.private:
        if doc_type is None:
            print("ℹ️  Doc type not in URL — using Drive API to detect it.")
        export_private(file_id, doc_type, output_dir)
    else:
        # Try public export first
        try:
            export_public(file_id, doc_type, output_dir)
        except SystemExit:
            # If public export failed with auth error, suggest private mode
            raise


if __name__ == "__main__":
    main()
