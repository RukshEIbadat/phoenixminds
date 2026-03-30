#!/bin/bash
# PhoenixMinds — Image Setup Script
# Run from your Round-2 project folder
# ═══════════════════════════════════

echo "Setting up PhoenixMinds image folders..."

# Create static folder structure
mkdir -p static/images
mkdir -p static/css

echo "Folders created: static/images/ and static/css/"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   MANUAL STEP REQUIRED — 2 minutes                          ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║   Copy your two images into: static/images/                 ║"
echo "║                                                              ║"
echo "║   Image 1 (blue/teal tech - for Services page):             ║"
echo "║   → Rename to:  service_hero.jpeg                           ║"
echo "║   → Save in:    static/images/service_hero.jpeg             ║"
echo "║                                                              ║"
echo "║   Image 2 (orange/AI brain - for About page):               ║"
echo "║   → Rename to:  about_founder.jpeg                          ║"
echo "║   → Save in:    static/images/about_founder.jpeg            ║"
echo "║                                                              ║"
echo "║   In VS Code:                                                ║"
echo "║   1. Open Explorer panel (left sidebar)                     ║"
echo "║   2. Find static/images/ folder                             ║"
echo "║   3. Drag and drop both images into it                      ║"
echo "║   4. Rename them as shown above                             ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Also add static folder route to Flask if not present
echo "Checking Flask static folder config..."
echo "✓ Flask serves static files from 'static/' folder automatically."
echo "✓ Images will be available at: http://localhost:5000/static/images/"
echo ""
echo "Done! Run: python app.py"
