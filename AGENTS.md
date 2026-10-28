# Instructions for Codex and other coding agents

## Read project context first

Before planning, editing code, running hardware playback or making compatibility claims, read [docs/context.md](docs/context.md). It is the shared handoff for every session. Follow the links there when more detail is needed, and inspect the current code and Git state before relying on historical observations.

## Keep the context current — mandatory

Update `docs/context.md` during the work, not just when asked:

- After each meaningful milestone: an architectural decision, behavior change, completed subsystem, hardware observation, significant test result, new limitation or blocker.
- Whenever the next step or an important assumption changes.
- Before handing work back to the user, ending a substantive session or committing/publishing changes that affect the recorded project state. Include the context update in the same commit when applicable.
- If interrupted, record incomplete work and the exact next step before stopping when possible.

Use a dated, concise progress entry and refresh the current-state sections. Keep verified software behavior, user-reported hardware observations and untested expectations distinct. State which checks actually ran, their result and remaining validation; never present an old test result as a new run. Do not make a context-only edit for a trivial read-only question if nothing changed.

Keep this file useful as a current handoff, not an unbounded transcript. Condense stale progress entries while preserving important decisions and unresolved issues. If documentation and code disagree, investigate and correct the context rather than silently treating it as authoritative evidence.

## Keep user instructions accurate — mandatory

Whenever a project update changes installation, downloads, prerequisites, commands, connection/pairing, controls, settings, recovery or supported behavior, review the README's Download, How to use and Operating the player sections. Update every affected instruction in the same change/commit before handoff or publication. Do not leave obsolete commands or UI labels for a future documentation pass.

Verify documented command names, flags, paths, defaults and button labels against the current scripts/code. Update related setup guides and `docs/context.md` when affected. Keep download links and version-specific examples aligned with the release they actually describe, and clearly distinguish unreleased behavior on `main` from published builds. Do not claim a feature is available until the linked build contains it. Check relative links, placeholders, Markdown and Git whitespace; run functional checks only where the change warrants them, and state what was actually tested.

## Project constraints

- Preserve original media bytes, HDR metadata and compressed TrueHD passthrough. Do not introduce transcoding, audio resampling or audio speed changes as a synchronization fix.
- Route TV transport actions through the Windows coordinator and its shared synchronization barrier. Do not make the TV independently seek or resume.
- Keep positioning brand-independent, experimental and still in testing. Do not claim universal TV/HDR-profile support or proven physical lip-sync.
- Preserve any existing locked release artifacts. Do not overwrite published release versions to ship new behavior.
- Keep private addresses, personal paths, credentials, endpoint IDs, raw hardware logs and signing keys out of source, context, commits and release assets. Use the configured GitHub noreply identity for public commits; do not retrieve credentials manually.
- Run checks appropriate to the change. Documentation-only edits need link/content and diff checks, not hardware playback or a fresh application build.
