#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Please follow the setup instructions in README.md first."
  read -r -p "Press Return to close."
  exit 1
fi
export MPLCONFIGDIR="${TMPDIR:-/tmp}/hp48g-matplotlib"
exec .venv/bin/python -m hp48g
