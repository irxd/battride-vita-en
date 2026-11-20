# Plan: Battride War Sousei English patch

Status: **Phase 1, format research** (2026-11-20)

## Goal

A full English patch for the Vita version (PCSG00675, update 1.02): menus, items, help, story and battle
dialogue, and images with text. It's delivered the same way as the Shin Gundam Musou patch: rePatch folder, xdelta
patches, browser web patcher, optional English home-screen name.

## Starting point

| Source | What it gives us |
|---|---|
| Official English release | **None.** Genesis came out only in Japan (PS4/PS3/Vita). Every line needs a new translation. |
| froid_san fan patch v0.35 alpha (2019) | Partial: some menus, items, shop. No dialogue, no source code. Proves rePatch works with modified files. Reference only. |
| Kamen Rider: Climax Fighters (PS4, 2017, Asia English) | Same developer (Eighting), reuses Genesis models. Source of **official English names** for riders, forms and attacks. Optional: needs a PS4 dump. |
| Shin Gundam Musou patch (`D:\Personal\shin-gundam-musou-en`) | Pipeline to reuse: decrypt script, fself/unfself, eboot hook approach, font widths + word wrap, sha1-keyed JSON, release script, web patcher, title rename. |

## Findings so far

- Dump: game 1.00 (`app`, NoNpDrm) and update 1.02 (`patch`). Both decrypt with psvpfsparser using the game's
  work.bin key (`scripts/decrypt_vita.ps1`).
- `nativeVITA/` holds loose files: 675 `.fpk`, 315 `.tex` (GXT textures), 345 `.spm` (models), 516 `.ssa`, 61 `.mp4`
  movies, shaders, and single tables (`.gpd`, `.redb`, `.boot`, `.fgr`, …).
- **No plaintext Japanese** (UTF-8, UTF-16LE or Shift-JIS) in any loose file. Text is inside FPK2 archives.
- **FPK2 header** (little endian, 28 bytes):
  `"FPK2", u16 0x0204, u16 0, u32 ~0x104000–0x10F000 (differs per file, probably not a size), u32 file count,
  u32 archive size, u32 hash/key?, u32 hash/key?`. The data after the header has entropy ~7.96 from the first
  byte, so it's **encrypted or compressed with an obfuscated index**. The decryption code is in the eboot.
- Likely text archives: `_fpk/string.fpk` (0x39b entries), `drama.fpk` (story scenes), `mission/TALK.fpk`
  (battle dialogue), `ui/*.fpk` (menus and UI images), `seq.fpk`.
- Update 1.02 replaces 89 files, including all of the text archives above. **Build from the 1.02 files.**
- Font: `font/FOT-NewRodinPro-DB.fnt` (header says 0x0e50 = 3664 glyphs) + textures in `font/vita/`. It's a bitmap
  font, so English needs proportional widths (as in the Gundam project).
- 61 movies in `movie/etc/` (opening, ending, chapter scenes). Check whether they have burned-in Japanese text.
- `eboot.bin` is still an encrypted SELF after PFS decryption.

## Phases

### Phase 1: Get at the data
- [x] Decrypt game + update (`scripts/decrypt_vita.ps1`)
- [ ] **Get `eboot.bin.elf`** for 1.02 (and 1.00): FAGDec on the Vita, or Vita3K ELF dump. *Needs the user.*
- [ ] Reverse the FPK2 loader in the eboot: the cipher/key derivation (header fields), index layout, compression
- [ ] `tools/fpk.py`: unpack and repack FPK2 byte for byte (round-trip test on every archive)
- [ ] Check whether the game accepts a repacked archive via rePatch (Vita3K first, then hardware)

### Phase 2: Text formats
- [ ] Find the text formats inside `string.fpk`, `drama.fpk`, `TALK.fpk`, `ui/*.fpk`, `seq.fpk`
- [ ] Extractors and inserters, plus a full dump of all strings to a local (ignored) folder
- [ ] Count lines and characters per category to size the translation work
- [ ] Look at the froid_san patch output to see which files it changed (confirms the text locations)

### Phase 3: Font and display
- [ ] Parse `.fnt` + GXT glyph textures. Draw proportional Latin glyphs into the atlas
- [ ] eboot hooks (fself) as needed: proportional width, word wrap, shrink-to-fit
- [ ] First on-device test: a few menu strings in English

### Phase 4: Translation
- [ ] Terminology glossary: rider, form, attack and character names (Climax Fighters English, else the common fan
      names). Stored without Japanese, keyed by hash.
- [ ] Menus, items, help, tutorials (highest visibility)
- [ ] Battle dialogue (`TALK.fpk`) and mission messages
- [ ] Story scenes (`drama.fpk`)
- [ ] Review pass for line length and wrapping on device

### Phase 5: Images and movies
- [ ] List UI textures (`.tex`/GXT in `ui/`, `gtc/`) with Japanese text. GXT decode/encode tool
- [ ] Redraw the important ones (title, menu headers, YES/NO, chapter cards)
- [ ] Movies: subtitles or leave as they are, depending on what they contain

### Phase 6: DLC
- [ ] Dump and decrypt DLC (`addcont/PCSG00675`). *Needs the user.* Find which DLCs have text.

### Phase 7: Release
- [ ] `scripts/make_release.py`: build, xdelta, round-trip check, zip
- [ ] Web patcher (`docs/`), README with install steps, screenshots
- [ ] Optional English game name (`rename_title.py`)

## Open questions for the user

- eboot ELF: FAGDec dump from the Vita, or should we use Vita3K?
- DLC: which DLC do you own or have installed? (The old fan patch required all free DLC.)
- Climax Fighters: do you have a PS4 dump? If not, the glossary uses common fan names.
- Translation source: machine translation + review, or your own translation, or a mix?
