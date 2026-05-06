# Simulacrum — local CLI

`run.py` is a standalone CLI that wraps the same two-phase dispatch as the fly deployment. Useful for piping, scripting, or wiring as a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills).

## Install

```bash
pip install anthropic openai
ln -s ../fly/data/adversarial_pairs_annotated.json .   # or set $SIMULACRUM_DATA
```

## Required env

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Optional env (enables generalist branch)

```bash
export OPENAI_API_KEY=sk-proj-...
export GENERALIST_MODEL=ft:gpt-4o-mini-2024-07-18:personal:my-simulacrum:abc123
```

Without these, all turns route to the specialist. Still works.

## Use

```bash
./run.py "Every team needs a strong manager."

echo "Code quality is readable, working, deployable code." | ./run.py

echo '[["Interlocutor","Initial claim"],["Jeremy","First pushback"]]' > /tmp/dialog.json
./run.py --history /tmp/dialog.json "Their counter-claim"

cat /tmp/dialog.json | ./run.py --history-stdin "Follow-up"
```

Diagnostics on stderr (`[phase=... agent=... mode=...]`); response on stdout. Pass `--quiet` to suppress diagnostics.

## As a Claude Code skill

```bash
mkdir -p ~/.claude/skills/simulacrum
cp SKILL.md run.py ~/.claude/skills/simulacrum/
ln -s $(pwd)/../fly/data/adversarial_pairs_annotated.json ~/.claude/skills/simulacrum/
```

Then in any Claude Code session, the `simulacrum` skill is available — agents can invoke it to run an idea past the simulacrum before committing to a position.
