# translation-tools — install

**Target:** `~/Claude_Stuff/cli_projects/translation-tools/`

This ZIP's contents go directly into that folder (no wrapper directory).

```bash
export KIT=~/Claude_Stuff/cli_projects/translation-tools
mkdir -p "$KIT"
unzip translation-tools.zip -d "$KIT"
chmod +x "$KIT"/bin/*

# adjust the username in the deny paths to match your account
nano "$KIT"/.claude/settings.json

# persist the shorthand
echo "export KIT=$KIT" >> ~/.bashrc
source ~/.bashrc

"$KIT"/bin/tr-setup
```

`tr-setup` points the repository at `.githooks` for you. If you unpack the
kit somewhere that is already a git repository and skip `tr-setup`, do it
by hand — a global `core.hooksPath` shadows `.git/hooks` entirely, so until
this is set the hook that keeps client documents out of the repo never runs:

```bash
git -C "$KIT" config core.hooksPath .githooks
```

Then follow `~/translation-work/docs/01-operating-manual` §3.

## Why this location

The kit must sit on a different branch of the filesystem from the case data.
The `claude` guard refuses to start a session from anywhere inside or above
`~/translation-work/`, so `cd $KIT && claude` is only safe because the kit is
elsewhere. Placing it under `Claude_Stuff/cli_projects/` also keeps all
Claude Code CLI work in one area.

Nothing here hardcodes its own location — every script derives it at run time —
so this directory can be renamed or moved without edits.

## Contents

```
bin/          the tools (see CLAUDE.md for the table)
lib/trlib.py  segmentation, translation memory, model client
glossary/     templates; case-init seeds _shared/ from these
prompts/      system prompt template
CLAUDE.md     read by Claude Code at session start — states the data boundary
.claude/      permission rules (a backstop, not the primary control)
.githooks/    pre-commit blocks client documents; pre-push guards the remote.
              Inert until core.hooksPath points here — see above
```

## First commands

```bash
tr-hwsurvey                 # confirm the machine still matches the manual
tr-model                    # pull and register gams3:q8 (~13 GB, once)
./bin/case-init 40G         # create the encrypted container
mkdir -p ~/.local/sbin        # the guard shadows, never replaces, the launcher
cp bin/case-guard ~/.local/sbin/claude && chmod +x ~/.local/sbin/claude
case-open
tr-project --new <matter>
tr-fixtures fixtures/       # synthetic test documents, no real data needed
```
