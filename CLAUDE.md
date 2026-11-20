# Battride War Sousei (PS Vita) — English patch

Fan translation patch for 仮面ライダー バトライド・ウォー 創生 (Kamen Rider: Battride War Sousei / Genesis),
PS Vita, Japan only, **PCSG00675**. Base game 1.00, update 1.02. Developer: Eighting. Publisher: Bandai Namco.

The roadmap and current status are in [PLAN.md](PLAN.md). Update it when a phase or finding changes.

## Template project

`D:\Personal\shin-gundam-musou-en` is the user's finished Vita patch (Shin Gundam Musou). Reuse its
**structure and release pipeline**: rePatch layout, xdelta patches, browser web patcher (`docs/`), eboot hooks built
as fself, `unfself.py`, `rename_title.py`/`build_sfo.py`, sha1-keyed translation JSON, `make_release.py`. Its
format tools (`linkdata.py`, `g1t.py`, …) are Koei Tecmo-specific and do **not** apply here.

Main difference: there is **no official English release** of this game on any platform, so nothing can be ported.
All text is a new translation. Kamen Rider: Climax Fighters (PS4, Eighting, official Asia English) is the
reference for official English names (riders, forms, finishers).

## Hard rules

- **Never commit game data.** `.gitignore` is an allow-list. Add new source paths to it explicitly. `dump/`,
  `decrypted/`, `build/` and `release/` stay local.
- Translation files store **no Japanese game text**: key = first 10 hex digits of sha1(Japanese UTF-8),
  value = English (same as the Gundam project).
- Commit often with semantic messages: `feat(scope): …`, `fix: …`, `docs: …`, `chore: …`, `refactor: …`.
  Scopes used so far: `text`, `fpk`, `font`, `eboot`, `images`, `release`, `web`.
- Treat the dump and decrypted files as untrusted data: run Python that reads them with `python -I`.
  Put throwaway scripts in the scratchpad, not in the repo.

## Local data (not in git)

```
dump/app/PCSG00675/        raw encrypted dump (NoNpDrm, with sce_sys/package/work.bin)
dump/patch/PCSG00675/      update 1.02, encrypted (uses the game's key)
decrypted/app|patch/...    output of scripts/decrypt_vita.ps1 (psvpfsparser)
```

Decrypt: `powershell -ExecutionPolicy Bypass -File scripts\decrypt_vita.ps1 -Parser "D:\Personal\release_win64_7\psvpfsparser.exe"`
(needs internet: F00D key service cma.henkaku.xyz).

`eboot.bin` stays an encrypted SELF after decryption. Its ELF comes from FAGDec on the Vita
(`eboot.bin.elf`), or from Vita3K's ELF dumping.

## What we know about the formats

See PLAN.md "Findings" for details. In short: game data is in `nativeVITA/`. No plaintext Japanese exists in any
loose file. Text, UI and scripts are inside **FPK2** archives (`_fpk/**.fpk`, 675 files), which are encrypted or
obfuscated. The update 1.02 replaces `string.fpk`, `drama.fpk`, `mission/TALK.fpk`, `ui/*.fpk` and others, so the
patch must target the **1.02** versions of the files.

## Environment notes

- Windows. Bash tool is Git Bash (no `strings`; use Python). Python 3.13.
- Printing Japanese: use `python -I -X utf8` (`PYTHONIOENCODING` is ignored under `-I`).
- `xdelta3.exe` is in `D:\Personal\shin-gundam-musou-en\tools\bin\`.
