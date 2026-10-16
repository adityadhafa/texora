# Product — Texora

Texora is an offline-first desktop app for high-accuracy OCR of mathematical and scientific
documents (printed and handwritten), with Mathpix-class UX but running locally with no cloud quota
and no PDF page cap.

## What it is
- Local, offline-by-default. Zero telemetry. Any network egress is explicit and opt-in.
- Unlimited PDF pages (10 or 10,000) via streaming + per-page SQLite checkpoint/resume.
- Converts documents and screen snips to LaTeX, Markdown, DOCX (editable OMML), HTML, MathML,
  AsciiMath, JSON, and searchable PDF.

## Who it's for
- A single technical end user on their own machine (Windows primary, Linux/macOS secondary) for
  personal use. Not a SaaS, not multi-user.

## Principles
- **Honesty over hype.** No "Mathpix-level" claims unless benchmarks support them. Report real
  numbers in `docs/BENCHMARKS.md`.
- **Never fabricate output.** A region that can't be recognized is marked `needs_review`/`failed`,
  never guessed and shown as confident. No mocked OCR in production paths.
- **No work lost.** Crash/kill/reboot mid-job resumes from the last completed page.
- **Privacy first.** Loopback-only engine, session token, keys in the OS vault, clear warnings
  before any data leaves the machine.
- **Permissive-first.** Prefer Apache/MIT/BSD components; copyleft/non-commercial pieces are opt-in,
  never bundled as the shipped default.

## Milestones (each must be runnable)
M1 skeleton + CI installer · M2 snip-tool formula OCR · M3 PDF pipeline + MD/LaTeX ·
M4 jobs + checkpoint/resume + 5,000-page proof · M5 ensemble + review UI · M6 tables + DOCX/OMML +
handwriting · M7 benchmarks + tuned defaults · M8 i18n/polish/installer.

## Definition of done
Install via normal installer with no manual Python; OCR a 1,000+ page math PDF end-to-end; resume
after a kill; exports compile/open; benchmarks + license docs exist and are honest.
