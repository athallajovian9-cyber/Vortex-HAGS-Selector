# Vortex HAGS Selector

Hardware-Accelerated GPU Scheduling, decided per game.

Most "HAGS on or off" tools answer the question once, for the whole machine. This
one answers it for **the game you are actually playing**, because turning it on is
not free: HAGS moves GPU scheduling work into the driver, and when your card is
already short of video memory for that title, the cost lands on the resource that
is running out. That shows up as stutter, not as a smoother frame time.

**Official source:** this repository, and the
[Vortex Industries Discord](https://discord.gg/QtyBucygQ6). Anything found
elsewhere is not ours and has not been checked.

## Install

1. Open [Releases](../../releases) and download the newest one.
2. Run **`Vortex_HAGS_Selector.exe`** or **`RUN_HAGS_SELECTOR.bat`**.

No installer, no dependencies, no Python. Windows will ask for administrator
rights, because `HwSchMode` is machine-wide and cannot be written without it.

## What it does

- Reads your **real** video memory from the display class registry, not WMI's
  `AdapterRAM`, which is a 32-bit field that saturates at 4095 MB and cannot tell
  a 6 GB card from a 4 GB one
- Refuses HAGS outright on any card with **2 GB or less**, whatever the generation
- Enables it only where the driver supports it: Turing or newer NVIDIA (RTX
  anything, GTX 16-series, Quadro T-series), RDNA on AMD (RX 5000 and up), Arc on
  Intel. Never on Pascal, Maxwell, Kepler, Polaris or Vega
- Picks the answer **per title** from a catalogue of **39 games** at 1080p, and
  tells you which gate fired: the game's requirement, the 2 GB floor, or the
  architecture
- Turns the setting on and off by itself as you **launch games** - the watcher
  reads the title in front every 2 seconds
- Shows the result it wrote back, read out of the registry, rather than reporting
  success because the write call returned
- Writes `HAGS_Restore.reg` on request, so you can put the setting back without
  this tool, or without Windows booting correctly
- Remembers the value that was there before it ever ran, so RESTORE PREVIOUS puts
  your machine back the way it was

## The watcher

The tool's reason to exist. Turn it on and start a game: the verdict for that
title is applied before you are in the menu.

Two things it deliberately does not do:

- **It does not revert when you quit a game.** Alt-tabbing to a browser or
  Discord is not a workload change, and writing the registry every time you leave
  a window would flip the setting dozens of times an hour for no reason. It acts
  on *entering* a title, and on nothing else.
- **It does not guess.** A title whose executable name is not known here has no
  mapping, and running it changes nothing. If the process in front is one you
  recognise, press **ASSIGN THIS PROCESS TO THE SELECTED TITLE** and it is saved
  to `games_user.json`, which overrides the built-in map from then on.

The console says which of those happened every time, so the setting never changes
without a line explaining it.

## What it changes

```
HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\GraphicsDrivers
    HwSchMode   REG_DWORD   1 = off, 2 = on
```

That is the only value this tool writes. **It takes effect on the next boot** -
Windows reads it once at startup, so a game already running will not see the new
setting until you reboot.

## Files it leaves behind

- `hags_state.json` - the value that was there before the first write, for undo
- `games_user.json` - executable-to-title assignments you made
- `hags_report.txt` - written by `--report` and by `HAGS_REPORT.bat`
- `HAGS_Restore.reg` - written by EXPORT .REG

Nothing is written outside the tool's own folder. No telemetry, no network calls,
no updater.

## Command line

```
Vortex_HAGS_Selector.exe              the window
Vortex_HAGS_Selector.exe --watch      start with the watcher already on
Vortex_HAGS_Selector.exe --report     write hags_report.txt beside the exe and exit
Vortex_HAGS_Selector.exe --selftest   headless checks, exit code 0 or 1
```

Because the build has no console attached, `--report` writes the file instead of
printing to a terminal. `HAGS_REPORT.bat` runs it and then shows you the file.

## The 39 titles

Esports and light: VALORANT, Counter-Strike 2, League of Legends, Dota 2, Rocket
League, Overwatch 2, Rainbow Six Siege.

Mid-weight: THE FINALS, Marvel Rivals, Fortnite, GTA V, Apex Legends, Red Dead
Redemption 2, Helldivers 2, PUBG, Destiny 2, Warframe, Monster Hunter: World,
The Witcher 3.

AAA and heavy: Cyberpunk 2077, Cyberpunk 2077 (ray tracing), Elden Ring,
Starfield, Hogwarts Legacy, Alan Wake 2, Battlefield 2042, Call of Duty: Warzone,
Forza Horizon 5, Microsoft Flight Simulator, Baldur's Gate 3, Escape from Tarkov,
Rust, Monster Hunter Wilds, Black Myth: Wukong, S.T.A.L.K.E.R. 2, Dragon's Dogma 2,
Horizon Forbidden West, Marvel's Spider-Man 2, Indiana Jones and the Great Circle.

The figures are **1080p memory guidance, not vendor minimums**, and they are
deliberately conservative. Being told to leave HAGS off on a card that could just
about cope costs a little efficiency; being told to turn it on when the card is
already paging costs frame time. The two errors are not the same size, so the
catalogue errs toward the second one never happening. Three titles - THE FINALS,
Marvel Rivals and Spider-Man 2 - ship with no executable mapping on purpose: their
process names are not known here, and a guessed name applies another game's policy.

## One writer

The rule is not reimplemented in this tool. It is `hags_policy.py`, the same file
the Vortex Optimizer and the Presentation Governor call, with 82 tests. All three
cannot disagree about what HAGS should be doing on a given card, which is the
failure this avoids: two tools writing the same value, one enabling and one with a
hardcoded disable, resolving by launch order so whichever ran last silently won.

## Notes

- Portable. Nothing is written outside the tool's folder.
- The source sits in this repo, with `build.sh` and the two test files.
- Questions and bug reports: the [Discord](https://discord.gg/QtyBucygQ6), in
  `#help` and `#bug-reports`.

## Disclaimer

This changes a real Windows setting. It is reversible - `HAGS_Restore.reg`, or
RESTORE PREVIOUS, or set `HwSchMode` back to 1 by hand - but read what it does
first. Provided as is, with no warranty.
