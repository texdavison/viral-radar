# Viral Idea Radar: collector

Real trend data for the @how_does_it_work1 idea pipeline. Runs on Tex's PC every 3 hours,
pushes `signals/latest.json` to this public repo, and the cloud scan reads it.

Quick start: open this folder in Claude Code and say "set this up". The steps are in `CLAUDE.md`.

Manual run: `py collect.py --dry-run` to test, `powershell -ExecutionPolicy Bypass -File run.ps1` to collect and push.
