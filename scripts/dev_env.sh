# Source this file: source scripts/dev_env.sh
_k="${LOCALAPPDATA:-$HOME/.local/share}/komute"
if [ -e "$_k/venv/Scripts/python.exe" ]; then export PY="$_k/venv/Scripts/python.exe"; else export PY="$_k/venv/bin/python"; fi
set -a
[ -f "$_k/dev.env" ] && . "$_k/dev.env"
set +a
export PYTHONUTF8=1
export KOMUTE_ENV=dev
export KOMUTE_STORAGE_ROOT="$_k/storage"
export KOMUTE_SAMPLES_DIR="$_k/samples"
unset _k
