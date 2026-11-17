#!/bin/bash
# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

# Build script for docbook example with search
# Usage: ./scripts/build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "========================================="
echo "Building docbook example with search"
echo "========================================="

# Step 1: Clean up previous builds
echo ""
echo "Step 1: Cleaning up previous build..."
rm -rf chunks index.jsonl

# Step 2: Chunk the documents (generates HTML pages)
echo ""
echo "Step 2: Chunking documents..."
opm chunk data/doc --force

# Step 2.5: Add search to index.html
echo ""
echo "Step 2.5: Adding search to index page..."
if [ -f chunks/index.html ]; then
    python3 << 'PYTHON_SCRIPT'
import re

with open('chunks/index.html', 'r') as f:
    content = f.read()

# Add Pagefind module script to <head> so components are registered before parsing
head_pattern = r'(</head>)'
head_replacement = r'  <script defer src="assets/search/pagefind-component-ui.js"></script>\n  <link rel="stylesheet" href="assets/search/pagefind-component-ui.css">\n\1'
content = re.sub(head_pattern, head_replacement, content, count=1)

# Add search trigger to the toolbar nav
toolbar_pattern = r'(<nav class="toolbar"[^>]*>)'
replacement = r'\1\n    <pagefind-modal-trigger></pagefind-modal-trigger>'
content = re.sub(toolbar_pattern, replacement, content, count=1)

# Add modal and config before </body>
body_pattern = r'(</body>)'
body_replacement = r'  <pagefind-modal></pagefind-modal>\n\1'
content = re.sub(body_pattern, body_replacement, content, count=1)

with open('chunks/index.html', 'w') as f:
    f.write(content)

print("Search components added to index.html")
PYTHON_SCRIPT
fi

# Step 3: Generate opm index JSONL
echo ""
echo "Step 3: Generating search index from opm..."
opm index data/doc -o index.jsonl

# Step 4: Check if we have records
echo ""
echo "Step 4: Checking index records..."
if [ ! -f index.jsonl ]; then
    echo "ERROR: index.jsonl was not created"
    exit 1
fi

RECORD_COUNT=$(wc -l < index.jsonl)
echo "Generated $RECORD_COUNT index records"

# Step 5: Build Pagefind index
echo ""
echo "Step 5: Building Pagefind search index..."
uv run --script scripts/build_search_index.py --jsonl index.jsonl --output chunks/assets/search

# Step 6: Copy Pagefind UI assets (using CDN for simplicity)
echo ""
echo "Step 6: Setting up Pagefind UI..."
# Create assets directory if it doesn't exist
mkdir -p chunks/assets

# Download Pagefind components (optional - can use CDN instead)
# For production, you might want to download these locally:
# curl -o chunks/assets/pagefind.js https://cdn.jsdelivr.net/npm/pagefind@1.6.0/dist/esm/pagefind.js
# curl -o chunks/assets/pagefind.css https://cdn.jsdelivr.net/npm/pagefind@1.6.0/dist/esm/pagefind-component-ui.css

# Step 7: Clean up temporary files
echo ""
echo "Step 7: Cleaning up..."
rm -f index.jsonl

echo ""
echo "========================================="
echo "Build complete!"
echo "========================================="
echo ""
echo "To test the search:"
echo "  1. Run: opm serve"
echo "  2. Open http://localhost:8080 in your browser"
echo "  3. Click the search icon (magnifying glass) in the toolbar"
echo "  4. Try searching for terms like 'TEI Publisher' or 'introduction'"
echo ""
echo "The search index is in: chunks/assets/search/"
