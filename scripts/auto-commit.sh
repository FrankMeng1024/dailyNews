#!/bin/bash

# Auto-commit script for dailyNews
# Usage: ./auto-commit.sh [commit message]

# Navigate to project root
cd "$(dirname "$0")/.."

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Error: Not a git repository"
    exit 1
fi

# Check for changes
if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi

# Show current status
echo "=== Current Changes ==="
git status --short
echo ""

# Get commit message
if [ -n "$1" ]; then
    commit_message="$1"
else
    read -p "Enter commit message (or press Enter for auto): " user_message
    if [ -z "$user_message" ]; then
        commit_message="Auto commit: $(date '+%Y-%m-%d %H:%M:%S')"
    else
        commit_message="$user_message"
    fi
fi

# Add all changes
git add .

# Commit
git commit -m "$commit_message"

# Push to remote
echo ""
echo "Pushing to remote..."
git push

echo ""
echo "=== Done ==="
