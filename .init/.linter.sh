#!/bin/bash
cd /home/kavia/workspace/code-generation/manufacturing-defect-management-system-241916-241932/defect_management_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

