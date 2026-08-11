# translation-tools — install

**Target:** `~/Claude_Stuff/cli_projects/translation-tools/`

The kit is a git repository, distributed as a private repository on GitHub.
Clone it — do not unpack it from an archive. A copy extracted from a ZIP has
no `.git`, and without that the hook that keeps client documents out of the
repository cannot be installed at all.

```bash
export KIT=~/Claude_Stuff/cli_projects/translation-tools
git clone git@github.com:hmbseaotter/offline-legal-translation.git "$KIT"
chmod +x "$KIT"/bin/*

# adjust the username in the deny paths to match your account
nano "$KIT"/.claude/settings.json

# persist the shorthand
echo "export KIT=$KIT" >> ~/.bashrc
source ~/.bashrc

"$KIT"/bin/tr-setup
```

`tr-setup` points the repository at `.githooks` for you, and says so. A global
`core.hooksPath` shadows `.git/hooks` entirely, so until this is set the hook
that blocks a `git add -f` of a client document never runs. To do it by hand:

```bash
git -C "$KIT" config core.hooksPath .githooks
```

If you ever do have only an archive copy, treat it as unprotected: `git init`
it and set `core.hooksPath` before adding anything.

Then follow `~/translation-work/docs/01-operating-manual` §3.

## Why this location

The kit must sit on a different branch of the filesystem from the case data.
The `claude` guard refuses to start a session from anywhere inside or above
`~/translation-work/`, so `cd $KIT && claude` is only safe because the kit is
elsewhere. Placing it under `Claude_Stuff/cli_projects/` also keeps all
Claude Code CLI work in one area.

No script hardcodes its own location; each derives it at run time, and
`core.hooksPath` is relative, so both travel with the directory. Two lines in
`~/.bashrc` do not: the `export KIT=` and the `$KIT/bin` PATH entry that
`tr-setup` wrote with the old absolute path. Re-running `tr-setup` after a
move appends the new PATH line but leaves the stale one behind, so edit
`~/.bashrc` by hand.

(The paths in `.claude/settings.json` point at the *data*, not at the kit, so
a move does not affect them. They do need the username adjusted — see above.)

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
