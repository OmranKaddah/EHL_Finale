#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
archive="$repo_root/dist/rfq-agent.tar.gz"
cd "$repo_root"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: scripts/rehearse_rfq.sh [--prepare-only | --public [Atira test-run options]]"
    exit 0
fi

if ! command -v atira >/dev/null 2>&1; then
    echo "The atira CLI is required for a rehearsal." >&2
    exit 1
fi

if [[ "${1:-}" == "--public" ]]; then
    shift
    if [[ "${RFQ_MODEL:-qwen}" != "qwen" ]]; then
        echo "Public Atira rehearsals require the supplied Qwen/Clef proxy. Unset RFQ_MODEL for --public." >&2
        exit 2
    fi
    for option in "$@"; do
        if [[ "$option" == "--model" || "$option" == --model=* ]]; then
            echo "Atira test-run does not accept a direct OpenAI model selection." >&2
            exit 2
        fi
    done
    if [[ -x "$repo_root/.venv/bin/python" ]]; then
        python_bin="$repo_root/.venv/bin/python"
    else
        python_bin="$(command -v python3 || true)"
    fi
    if [[ -z "$python_bin" ]]; then
        echo "Python 3 is required to build the RFQ package." >&2
        exit 1
    fi
    "$python_bin" "$repo_root/scripts/package_rfq.py"
    package_dir="$(mktemp -d "${TMPDIR:-/tmp}/ehl-rfq-rehearsal.XXXXXXXX")"
    trap 'rm -rf -- "$package_dir"' EXIT
    tar -xzf "$archive" -C "$package_dir"
    ATIRA_API=https://ehl-challenge.atira.ai atira test-run "$package_dir" --challenge rfq "$@"
    exit
fi

if [[ $# -gt 0 && "${1:-}" != "--prepare-only" ]] || [[ $# -gt 1 ]]; then
    echo "Usage: scripts/rehearse_rfq.sh [--prepare-only | --public [Atira test-run options]]" >&2
    exit 2
fi
if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
    echo "Install the local environment first: uv pip install --python .venv/bin/python -e '.[test,rfq]'" >&2
    exit 1
fi
if ! "$repo_root/.venv/bin/python" -c 'import dotenv' >/dev/null 2>&1; then
    echo "Install RFQ dependencies first: uv pip install --python .venv/bin/python -e '.[test,rfq]'" >&2
    exit 1
fi
if ! "$repo_root/.venv/bin/python" -c 'import os, sys; from dotenv import load_dotenv; load_dotenv(".env"); sys.exit(not bool(os.environ.get("OPENAI_API_KEY", "").strip()))'; then
    echo "OPENAI_API_KEY is missing; add it to the local .env file." >&2
    exit 2
fi
if ! command -v google-chrome >/dev/null 2>&1; then
    echo "google-chrome is required for the local rehearsal." >&2
    exit 1
fi

export RFQ_MODEL=gpt-6-luna
if [[ "${1:-}" == "--prepare-only" ]]; then
    bash "$repo_root/scripts/local_browsers.sh" 4
else
    bash "$repo_root/scripts/local_browsers.sh" 4 --submit
fi
