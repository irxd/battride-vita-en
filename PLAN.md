# Plan: Battride War Sousei English patch

Status: **Phase 4, first translation pass complete** (2026-11-20). 9,246 of 9,377 unique lines are translated. What
remains is the credits staff names (table 10, kept in Japanese on purpose) and two dash placeholders. Next: on-device
overflow review, then Phase 5 (images) and Phase 7 (release).

## Goal

A full English patch for the Vita version (PCSG00675, update 1.02): menus, items, help, story and battle
dialogue, and images with text. It's delivered the same way as the Shin Gundam Musou patch: rePatch folder, xdelta
patches, browser web patcher, optional English home-screen name.

## Starting point

| Source | What it gives us |
|---|---|
| Official English release | **None.** Genesis came out only in Japan (PS4/PS3/Vita). Every line needs a new translation. |
| froid_san fan patch v0.35 alpha (2019) | Partial: some menus, items, shop. No dialogue, no source code. Reference only. |
| Kamen Rider: Climax Fighters (PS4, 2017, Asia English) | Same developer (Eighting). Source of **official English names**. The user will provide a dump later. |
| Shin Gundam Musou patch (`D:\Personal\shin-gundam-musou-en`) | Pipeline to reuse: decrypt script, fself, sha1-keyed JSON, release script, web patcher, title rename. |

## Findings

- Dump: game 1.00 (`app`, NoNpDrm) and update 1.02 (`patch`). Both decrypt with psvpfsparser using the game's
  work.bin key (`scripts/decrypt_vita.ps1`). Update 1.02 replaces 89 files, including all text archives: **build from
  the 1.02 files**. `eboot.bin` stays an encrypted SELF; the ELFs from FAGDec are in `eboot/`.
- **FPK2 is solved** (`tools/fpk.py`): encrypted entry table (custom cipher, verified against the eboot under Unicorn),
  CRC-32/BZIP2 per entry, zlib data. All 675 archives rebuild byte-identical. **Repacked archives load fine in Vita3K**
  (the unexplained header bytes 0x14-0x27 are not checked).
- **Text = `STA\0` string tables** (`tools/sta.py`), UTF-8, hard `\n` breaks, inline `<COLOR=0x...>` tags, button
  icons U+E000-U+E00F, `%d`/`%s`. `_fpk/string.fpk` has every line; `drama/chr/**` and `chr/**` repeat some of them.
  The renderer also knows a `<SIZE=...>` tag but ignores its value (tested 12, 0.8, 80).
- **Font** (`tools/font.py`): `FOT-NewRodinPro-DB.fnt` has proportional ASCII already. For English the ASCII glyph
  records are scaled to **85%** (quad size, offsets, advance; same texture), which fits ~18% more text and stays
  legible (Vita3K screenshots). Space advance 4.5. The header size field does nothing.
- **Layout rules** in `tools/build_text.py`, checked in Vita3K:
  - A table's multi-line strings share one box: width = widest Japanese line in the table; large tables (20+
    multi-line strings) also share a line limit.
  - **Mission dialogue box** (string.fpk tables 55+): 2 lines of up to ~340 px (325 used) whatever the Japanese
    line breaks were. Spoken lines wrap to it; one-line banners don't.
  - The build reports `LINES` (too many lines, must fix) and `WIDE` (one-line label wider than the Japanese; only a
    problem if it overflows on screen).
- **Not text** (done as images/movies, Phase 5): the boot notice (ご注意), YES/はい buttons, main menu items, mission
  kill counter banner (37体倒せ!!), story intro narration (movie msn/STR_000_000, centred text on black).
- Vita3K reads only `ux0/app` (merge the update in) and needs the NoNpDrm license in `ux0/license` for the
  encrypted `sce_module` files: `scripts/vita3k_install.py`. `scripts/vita3k_drive.ps1` drives the game with key
  presses and screenshots (Circle = C confirms in game, Cross = X confirms system dialogs). The 3D stages don't render
  in this Vita3K build, but all UI does.

## Phases

### Phase 1: Get at the data
- [x] Decrypt game + update, get the eboot ELFs, reverse FPK2, `tools/fpk.py` with round-trip tests
- [x] Repacked archive loads in Vita3K
- [ ] Confirm on hardware (user)

### Phase 2: Text formats
- [x] STA format, full string dump (`extracted/string_dump.txt`, local), counts

### Phase 3: Font and display
- [x] English renders with the stock font (proportional ASCII); 85% Latin glyphs; narrow space
- [x] Word wrap to box widths; overflow report
- [ ] On-device check by the user (overflowing text)

### Phase 4: Translation (`text/string/*.json`)
- [x] Menus, options, contents, tutorials, tips, difficulty, shop, credits headers
- [x] Rider, form, enemy, support character names; skills, figure effects, special move list (table 43)
- [x] Character descriptions, figure descriptions, unlock messages, battle cries, story intro (table 27)
- [x] Mission dialogue, banners, story, battle lines and navigator commentary: tables 55-938
- [ ] Staff names in the credits (table 10) are still Japanese (readings of real names not guessed)
- [x] Glossary: naming decisions below and the Climax Fighters section (official spellings)
- [ ] Review pass on device

### Phase 5: Images and movies
UI textures are GXT (all swizzled DXT1/DXT5) inside `ui/*.fpk`; sprite rectangles come from the SpriteStudio
layouts (SSAD files, PART > AREA). `tools/gxt.py` decodes/encodes, `tools/build_images.py` clears each sprite
rectangle and draws the English with Windows fonts (Impact, Arial, Times), re-encoding only touched blocks.
- [x] Boot notice (title 0004), Yes/No (common 0016)
- [x] Main menu items and header (menu 0352), screen headers (common 0083), options labels (menu 0369)
- [x] Pause/customize menu labels, Start/Quit Mission, shop tabs (texture/menu 0005)
- [x] 54 mission objective cut-ins (action 0064-0117), battle HUD labels (action 0153/0154/0155/0157)
- [x] 61 rider name plates (menu 0091-0151), ranking record labels (menu 0306)
- [x] Portrait name tags (menu 0158-0201), rider name list (menu 0248), HUD counter suffixes removed
- [ ] Left as is: 6-7 px label atlases no SSAD layout references (menu 0305/0308, result 0306/0307/0308,
      action 0201, common 0014), 秒 in result 0192, stylised finisher kanji in result effects (artwork)
- [x] Movies (`tools/build_movies.py`, cues in `text/movies/*.json`, no Japanese stored): 29 of 61 movies have
      burned-in subtitles (none in the string tables). 3 story chapter movies (etc/CHP_*, 'Speaker「line」' on a
      black bar) and 26 mission movies (small centred text) are re-rendered: each English cue covers the Japanese
      (black bar / dark rounded box) via ffmpeg overlay, re-encoded with h264_nvenc (Main@3.1, B-frames, GOP 30,
      ~1 Mbps, moov first, audio copied; h264_mf/amf/qsv fail in the bundled ffmpeg). Opening/Ending have no
      subtitles. Release impact: the re-encoded movies are ~129 MB, so their xdelta patches are about that size.
- [ ] Movies: in-game playback of a re-encoded movie not yet seen (Vita3K can't get past the 3D stages)
- [x] Intro narration before Story Mode chapter 1 = movie msn/STR_000_000 (centred lines on black; the subtitle
      scan only looked at the bottom band): 4 cues
### Phase 6: DLC
- [x] DLC = three 0-byte unlock flags. The characters ship in update 1.02. No DLC text.

### Phase 7: Release
- [x] `scripts/make_release.py`: build, xdelta, round-trip check, zip (`python -P scripts/make_release.py <ver>`)
- [x] Web patcher (`docs/`), README with install steps; `scripts/apply_patches.py` pure-Python patcher
- [x] Optional English game name (`tools/rename_title.py`)
- [ ] Screenshots, browser test of the web patcher, hardware test of the install steps

## Climax Fighters reference (official English names)

`tools/ps4pkg.py` opens the PS4 fake PKG (passcode zeros, checked against ENTRY_KEYS), `tools/psarc.py` reads
`archive.psarc`, and the text is JSON TextAssets (`keys`/`values`, one table per language) inside
`Media/level9.resS`. Pairing the Japanese and English tables by key gives ~2,100 official JP→EN pairs
(`dump/cf/cf_ja_en.json`, local only). 211 of our names already matched; adopted CF spellings:
W forms with spaces (Cyclone Joker, Fang Joker, Cyclone Joker Extreme), Grand Form / Grand Crash / Grand Impact,
Shining Clash, Axel Form (Faiz) and Axel moves, Ax Form, Garuru, Sagouzo, Rekkadan, Rekkaken,
Ongekida: Kaenrenda no Kata / Ikkihasei no Kata, Boisterous (Den-O Sword moves), Bicker Finallusion,
Fang Streiser, Gush Cross, A-Slasher, Accel Glanzer, Cavaliend.
Kept ours: Dimension Kick (CF typo), Clock Up, Breakdance, Jimber Lemon Arms, Omega Drive: Boost, UI labels.

## Decisions

- Translation: done by Claude. The user tests on hardware and reports overflowing text.
- Names: official English romanizations (Kuuga, Den-O, OOO, Gaim...). 必殺技 = "Special Move", 超必殺技 = "Finisher",
  ライダーソウル = "Rider Souls", タッグパートナー = "tag partner", ボルテージ = "Voltage". Climax Fighters names can
  replace them later.
- Climax Fighters PS4 dump: the user will provide it later.
