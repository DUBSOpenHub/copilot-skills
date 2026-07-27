---
name: copilot-builder-showcase
description: >
  Turn any workshop into a live Copilot Builder Showcase. Drop the links,
  activate the judging panel, and spotlight the winners in under two minutes.
  The same single-screen flow works for builder workshops, product demos,
  conference build sessions, and online challenges. Say "showcase" to start.
tools:
  - bash
  - powershell
  - ask_user
---

# Copilot Builder Showcase

The primary experience is one live showcase. Use the installed `showcase` command;
never ask a beginner to run Python or know the internal `workshop` subcommand.
Never invent an outcome in prose.

## Triggers

- `hackathon`
- `hackathon judge`
- `showcase`
- `builder showcase`
- `copilot builder showcase`
- `run hackathon judging`
- `judge these projects`
- `judge these repos`
- `judge these demos`
- `wrap up this builder workshop`
- `turn these projects into a showcase`
- `run the panel`
- `run a hackathon judge demo`

## First-run setup

Before collecting projects, check for the command.

On macOS or Linux:

```bash
command -v showcase
```

On Windows PowerShell:

```powershell
Get-Command showcase -ErrorAction SilentlyContinue
```

If it is missing:

1. Explain in one sentence that installation downloads this repository into
   `~/.local/share/copilot-builder-showcase` and creates commands in
   `~/.local/bin`.
2. Use `ask_user` to request installation permission.
3. Do not install unless the user explicitly approves.
4. When approved on macOS or Linux, run:

   ```bash
   bash -o pipefail -c 'gh api repos/DUBSOpenHub/copilot-builder-showcase/contents/install.sh \
     -H "Accept: application/vnd.github.raw+json" | bash'
   ```

   On Windows PowerShell, run:

   ```powershell
   $installer = Join-Path $env:TEMP "install-copilot-builder-showcase.ps1"
   gh api repos/DUBSOpenHub/copilot-builder-showcase/contents/install.ps1 `
     -H "Accept: application/vnd.github.raw+json" > $installer
   if ($LASTEXITCODE -ne 0) { throw "Installer download failed." }
   powershell -ExecutionPolicy Bypass -File $installer
   ```

5. Use the absolute launcher for the current run even if the shell has not
   reloaded its PATH: `~/.local/bin/showcase` on macOS/Linux or
   `$HOME\.local\bin\showcase.exe` on Windows.
6. Run the absolute launcher with `doctor`. If it fails, stop and report the
   specific setup issue before accepting projects.

The install command requires an authenticated GitHub CLI. If `gh auth status`
fails, stop and tell the user to run `gh auth login`; never request or handle a
token directly.

If installation is declined, provide the install command and stop. Never change
shell profiles automatically.

## One experience

- Do not offer Live, Quick, or Slack judging as mode choices.
- If project links or an uploaded submissions file are already present, start
  the live showcase immediately.
- If no project links are present, ask only for the links.
- Accept safe HTTP(S) project or demo URLs and GitHub `owner/repo` entries.
- If the organizer says `run again` or `start over`, reuse the previous project
  entries with a fresh run ID.
- If the organizer asks for a demo without links, use `showcase --demo`.

Plain links are enough. GitHub links may use public repository context and label
an unnamed entry as `<repository owner> team`. Generic links are never fetched
during intake; derive a safe project label and use `Project team` when no team is
supplied. Never infer Copilot or frontier use from a link, code, metadata, or a
judge impression. Missing evidence stays `not provided`.

## Result status

Keep the showcase result status explicit:

- `PRACTICE SHOWCASE — ILLUSTRATIVE RESULTS` means local practice judges are active.
- `OFFICIAL COPILOT PANEL` means an authenticated GitHub Copilot CLI panel is connected.

Installed local runs use the authenticated GitHub Copilot CLI when available.
`showcase --demo` is always a deterministic practice showcase. If the organizer
requires an official event, add `--official`; the command must block rather than
silently produce practice results. Never request or expose Copilot credentials.
On Windows, official judging requires the native `copilot.exe` installation
from `winget install GitHub.Copilot`; never invoke an npm `.cmd` or `.bat` shim
with project text.

## Start the live showcase

Write supplied links to a temporary file. Use the absolute command path when
needed:

```bash
~/.local/bin/showcase \
  --file <temporary-submissions-file> \
  --run-id <safe-event-run-id> \
  --require-live-terminal \
  --yes
```

On macOS, open exactly one real Terminal using that command:

```bash
osascript \
  -e 'tell application "Terminal" to do script "<shell-quoted-absolute-showcase-command>"' \
  -e 'tell application "Terminal" to activate'
```

Shell-quote every generated path and argument. Never place untrusted project
text directly into the AppleScript command; pass it through the temporary file.

On Windows, use one real Windows Terminal or PowerShell window and invoke
`$HOME\.local\bin\showcase.exe` with the same arguments. Do not run the audience
experience through captured tool output.

The new Terminal contains the complete audience experience. Share that one
window. Never auto-open the optional Textual monitor or a second Terminal.
Captured tool output is not the audience showcase; if a real Terminal cannot be
opened, stop before judging and provide the exact manual `showcase` command.

## Run the two-minute practice showcase

Use the same showcase:

```bash
~/.local/bin/showcase \
  --demo \
  --run-id <safe-demo-run-id> \
  --require-live-terminal \
  --yes
```

The demo is deterministic, avoids network metadata calls, exercises the full
intake-to-replay flow, and targets completion within 120 seconds. It is always
illustrative and never an official competition result.

## Showcase direction

The showcase should feel like a punchy startup demo day:

1. Project links enter immediately.
2. A generic sideline reporter describes the action with short, energetic lines.
3. Every project receives a data-rich spotlight and a specific panel reaction.
4. Scores, ranks, prompts, and awards stay sealed.
5. Before the final result, select one of the ten audience-participation cues,
   ask the operator to confirm the room is participating, then reveal.
6. Finish with a concise moment of joy, recap, export, validation, and replay.

Use suspense without a named host personality or publication imitation. Keep
the ceremony concise enough for a two-minute demo.

## Audience safety

- Never expose numeric scores, ranks, judge prompts, unrevealed awards, or the
  sealed Shadow Spec before awards.
- Every accepted project must appear before the ceremony.
- Keep Practice or Official status visible throughout.
- The optional `tui` command is diagnostic-only and must never auto-launch.
- Use `present <run-id> --operator` only after awards when scores are needed
  privately.

## Awards, ties, and feedback

The default reveal is a ranked podium: Builder Bronze, Builder Silver, then the
first-place Copilot Builder Award. Every project receives three brief judge takes
before the reveal, but only the top three receive awards. Exact ties follow the
EventSpec policy: shared placement, a predeclared sealed tiebreaker, or a logged
human decision. Never use entry order as a tiebreaker.

Private feedback may include award rationale, what judges liked, one actionable
next step, a Copilot next move, a bounded frontier experiment, and explicit
evidence status. Project-specific claims must use supplied context; unsupported
suggestions must be labeled hypotheses.

Immediately after the reveal, each podium project also receives a Top-3 growth
card: one improvement move, one optional Copilot-next suggestion, and one
Copilot-use note sourced only from builder-provided evidence. These are
diagnostic/growth content, not additional awards.

## Accessibility

If the organizer asks for a lower-motion showcase, add `--reduced-motion` to the
`showcase` command (or set `CBS_REDUCED_MOTION=1`; the legacy `HJ_REDUCED_MOTION`
is still honored). This keeps the same
single-terminal ceremony but skips optional suspense pauses. An EventSpec may
also set this as its default via `accessibility.reduced_motion`.

## After the run

Report the result status, run ID, bundle path, private feedback path, awards and
winners, replay command, and validation status. Keep run bundles internal unless
a human approves external publishing.
