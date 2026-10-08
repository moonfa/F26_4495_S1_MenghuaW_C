#!/usr/bin/env bash
# Run from the project folder: ./check.sh   (tells you exactly which code the server on :8000 is serving)
echo "Folder:                  $(pwd)"
echo "Version in files:        $(grep -o 'APP_VERSION = "[^"]*"' app/config.py)"
echo "Plan UI in page file:    $(grep -c planDlg app/static/index.html)  (expect 3)"
echo "Server reports:          $(curl -s --max-time 3 http://127.0.0.1:8000/api/v1/health || echo 'not reachable')"
echo "Server serves plan UI:   $(curl -s --max-time 3 http://127.0.0.1:8000/ | grep -c planDlg)  (expect 3)"
echo "Processes listening on 8000 and their folders:"
for pid in $(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | sort -u); do
  echo "  PID $pid  $(lsof -a -p $pid -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)"
done
