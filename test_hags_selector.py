"""Tests for the HAGS Selector: the vendored rule, the executable map, the host layer.

The rule itself is tested by Vortex_Suite/test_hags_policy.py and is not retested
here. What matters here is the part this tool adds:

  * the vendored copy of the rule must behave identically to the canonical one,
    because a copy that quietly drifts is worse than no copy - the Optimizer and
    this tool would then apply different answers to the same machine;
  * every executable in the map must name a real catalogue entry, and no entry in
    UNMAPPED may have one (an absent mapping costs a click, a wrong mapping
    silently applies another game's policy);
  * the tie between two catalogue entries sharing one executable must resolve to
    the larger requirement, and that rule must be exercised, not just described;
  * the host layer must not raise when it cannot read the machine.

RUN
    python3 test_hags_selector.py
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import game_processes as gp
import hags_host as host
import hags_policy as P

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS  " + name)
    else:
        failed += 1
        print("  FAIL  " + name + ("   -> " + str(extra) if extra else ""))


def rule(t):
    print("")
    print("  ---- " + t + " ----")


def load_canonical():
    """The suite's copy of the rule, loaded beside the vendored one."""
    path = HERE.parent / "hags_policy.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("canonical_hags_policy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------- the two copies must agree
rule("the vendored rule matches the canonical one")

C = load_canonical()
if C is None:
    print("  SKIP  canonical hags_policy.py not found (running outside the suite)")
else:
    check("the catalogue is identical",
          P.GAMES == C.GAMES,
          sorted(set(P.GAMES) ^ set(C.GAMES)))
    check("the categories are identical", P.GAME_CATEGORIES == C.GAME_CATEGORIES)
    check("the VRAM floor is identical", P.MIN_VRAM_MB == C.MIN_VRAM_MB)
    check("the mode constants are identical",
          (P.HAGS_OFF, P.HAGS_ON) == (C.HAGS_OFF, C.HAGS_ON))

    # same answer for every title, on a spread of cards - not just the same table
    cards = [("NVIDIA GeForce GTX 1650", 4096),
             ("NVIDIA GeForce GT 130", 512),
             ("NVIDIA GeForce RTX 3080", 10240),
             ("AMD Radeon RX 580", 8192),
             ("AMD Radeon RX 6700 XT", 12288),
             ("Intel Arc A750", 8192),
             ("Intel UHD Graphics 630", 128)]
    disagreements = []
    for gpu, vram in cards:
        for key in P.GAMES:
            a = P.hags_mode_for_game(gpu, vram, key)
            b = C.hags_mode_for_game(gpu, vram, key)
            if a != b:
                disagreements.append((gpu, vram, key, a, b))
    check("every card and title pair gets the same verdict from both copies",
          not disagreements, disagreements[:3])


# ----------------------------------------------------- the catalogue and map
rule("the executable map")

keys = set(P.GAMES)
strays = sorted(k for k in gp.GAME_PROCESSES if k not in keys)
check("every mapped key names a real catalogue entry", not strays, strays)

unmapped_strays = sorted(k for k in gp.UNMAPPED if k not in keys)
check("every deliberately-unmapped key names a real catalogue entry",
      not unmapped_strays, unmapped_strays)

overlap = sorted(set(gp.UNMAPPED) & set(gp.GAME_PROCESSES))
check("a title is not both mapped and unmapped", not overlap, overlap)

check("executable names are lowercase and look like files",
      all(e.endswith(".exe") and e == e.lower()
          for exes in gp.GAME_PROCESSES.values() for e in exes),
      [e for exes in gp.GAME_PROCESSES.values() for e in exes
       if not (e.endswith(".exe") and e == e.lower())][:3])

check("the catalogue is populated", len(P.GAMES) - 1 > 20, len(P.GAMES) - 1)
check("at least half the catalogue auto-detects",
      gp.TOTAL_MAPPED >= (len(P.GAMES) - 1) // 2,
      f"{gp.TOTAL_MAPPED}/{len(P.GAMES) - 1}")

# ------------------------------------------------------------- resolution
rule("resolving an executable to a title")

rm = gp.reverse_map()
check("the reverse map is not empty", bool(rm), len(rm))

check("a known executable resolves",
      gp.game_for_process("cs2.exe") == "cs2", gp.game_for_process("cs2.exe"))
check("resolution is case-insensitive",
      gp.game_for_process("CS2.EXE") == "cs2")
check("surrounding whitespace does not defeat it",
      gp.game_for_process("  cs2.exe  ") == "cs2")
check("a store launcher is not a game", gp.game_for_process("steam.exe") is None)
check("an anti-cheat wrapper is not a game",
      gp.game_for_process("start_protected_game.exe") is None)
check("the desktop shell is not a game", gp.game_for_process("explorer.exe") is None)
check("an unknown executable is not guessed at",
      gp.game_for_process("totally-unknown.exe") is None)
check("empty input is not guessed at", gp.game_for_process("") is None)
check("None input does not raise", gp.game_for_process(None) is None)

# the tie rule, exercised rather than described
rule("two entries sharing one executable")

shared = {}
for k, exes in gp.GAME_PROCESSES.items():
    for e in exes:
        shared.setdefault(e, []).append(k)
dupes = {e: ks for e, ks in shared.items() if len(ks) > 1}
check("the tie case exists in the map (this rule has something to decide)",
      bool(dupes), dupes)

for exe, ks in dupes.items():
    picked = rm.get(exe)
    heaviest = max(ks, key=lambda k: P.game_choice(k)[1])
    check("shared executable " + exe + " resolves to the heaviest requirement",
          picked == heaviest,
          f"picked {picked}, heaviest {heaviest} of {ks}")
    check("  and the tie really is between different requirements",
          len({P.game_choice(k)[1] for k in ks}) > 1,
          [P.game_choice(k)[1] for k in ks])


# --------------------------------------------------------------- host layer
rule("the host layer")

try:
    gpu = host.gpu_name_from_registry()
    check("the GPU probe answers without raising", True, gpu or "(nothing reported)")
except Exception as e:
    check("the GPU probe answers without raising", False, e)

try:
    exe, pid = host.foreground_exe()
    check("the foreground probe answers without raising", True, f"{exe} pid={pid}")
except Exception as e:
    check("the foreground probe answers without raising", False, e)

try:
    mode = host.read_hags()
    check("reading HwSchMode answers without raising",
          mode is None or isinstance(mode, int), mode)
except Exception as e:
    check("reading HwSchMode answers without raising", False, e)

check("the state word never claims ON unless the mode was 2",
      "ON" not in host.hags_state_word(1)
      and "ON" in host.hags_state_word(2)
      and "ON" not in host.hags_state_word(None),
      [host.hags_state_word(m) for m in (None, 1, 2)])

check("app_dir points at a real directory", host.app_dir().is_dir(), host.app_dir())

# the report must be buildable without a display
rule("the report path")
try:
    import vortex_hags_selector as SEL
    txt = SEL.build_report()
    check("the report builds without a display", len(txt) > 200, len(txt))
    check("the report names the GPU", "GPU" in txt)
    check("the report states a verdict", "Verdict" in txt)
    check("the report lists every title",
          all(P.GAMES[k][0] in txt for k in P.GAMES),
          [P.GAMES[k][0] for k in P.GAMES if P.GAMES[k][0] not in txt][:3])
except Exception as e:
    check("the report builds without a display", False, repr(e))

print("")
print("  RESULT  passes=" + str(passed) + "  fails=" + str(failed))
sys.exit(1 if failed else 0)
