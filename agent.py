"""Atira's platform entrypoint. No credentials or scenario constants live here."""
from atira_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
