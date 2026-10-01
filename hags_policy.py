"""
HAGS policy: should Hardware-Accelerated GPU Scheduling be enabled on this GPU?

The rule the old code used was wrong in both directions. It treated a GTX 1650 as
"weak silicon" (it is Turing and supports HAGS properly) and it treated anything that
was not an RTX or an RX 6/7/9 as incapable - so almost every card got HAGS switched
OFF, and a GTX 1650 specifically was on a literal deny list.

Two things decide it, and either can refuse:

  1. VRAM. 2 GB or less does not get HAGS, whatever the generation. HAGS moves
     scheduling work into the driver and needs somewhere to put it; on a card that
     small it costs more than it saves.

  2. Generation support. HAGS is a driver feature with a hard floor:
        NVIDIA   Turing and newer.  RTX anything, GTX 16-series, Quadro T-series.
                 Pascal, Maxwell, Kepler and Tesla (GT 130, GTX 1080, GT 1030) do
                 not support it, and writing mode 2 there does nothing but leave a
                 setting on that cannot work.
        AMD      RDNA only. The four-digit RX 5000 series and up. Polaris and Vega
                 (RX 580, RX 570, Vega 56) do not.
        Intel    Arc (Xe HPG). Integrated graphics do not.

VRAM is read from the display class registry first. `Win32_VideoController.AdapterRAM`
is reported as a 32-bit value that saturates at 4095 MB, so it cannot tell a 6 GB card
from a 4 GB one - which matters a great deal when the threshold is 2 GB.

RUN THE TESTS
    python3 test_hags_policy.py
"""
import os
import re

# HwSchMode values in HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers
HAGS_OFF = 1
HAGS_ON = 2

KEY_GRAPHICS_DRV = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"

# below or equal to this, HAGS is refused outright
MIN_VRAM_MB = 2048

# the display adapters class GUID, where per-adapter memory size lives
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


# --------------------------------------------------------------- GPU probing

def vram_mb_from_registry() -> int | None:
    """Real VRAM in MB, from HardwareInformation.qwMemorySize.

    A REG_QWORD, so unlike WMI's 32-bit AdapterRAM it does not saturate at 4 GB.
    Returns None if it cannot be read.
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError:
        return None
    best = None
    try:
        for i in range(64):
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            if not re.fullmatch(r"\d{4}", sub):
                continue          # 0000, 0001 ... but also Configuration/Properties
            try:
                k = winreg.OpenKey(root, sub)
                try:
                    qw, _ = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")
                    mb = int(qw) // (1024 * 1024)
                    if mb > 0 and (best is None or mb > best):
                        best = mb
                finally:
                    winreg.CloseKey(k)
            except OSError:
                continue
    finally:
        winreg.CloseKey(root)
    return best


def vram_mb_from_wmi() -> int | None:
    """Fallback. Saturated at 4095 MB on cards with more, hence the fallback order."""
    try:
        import subprocess
    except ImportError:
        return None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_VideoController | "
             "Sort-Object -Property AdapterRAM -Descending | "
             "Select-Object -First 1 -ExpandProperty AdapterRAM)"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        v = (r.stdout or "").strip()
        if v.isdigit():
            return int(v) // (1024 * 1024)
    except Exception:
        pass
    return None


def detect_vram_mb() -> int | None:
    return vram_mb_from_registry() or vram_mb_from_wmi()


# ------------------------------------------------------------------- policy

def hags_supported(gpu_name: str) -> tuple[bool, str]:
    """Is HAGS a feature this GPU's driver has at all?

    Returns False for anything unrecognised. Being conservative is the right way
    round here: enabling HAGS on silicon that cannot do it leaves a setting that
    lies, while leaving it off on capable hardware costs little and the user can
    turn it on themselves.
    """
    g = (gpu_name or "").strip().lower()
    if not g:
        return False, "no GPU reported"
    if g in ("unknown", "n/a", "none", "microsoft basic display adapter"):
        return False, f"no usable GPU reported ({gpu_name})"

    # ---------------- NVIDIA ----------------
    if any(k in g for k in ("nvidia", "geforce", "quadro", "rtx", "gtx", "gts", "gt ")):
        if "rtx" in g:
            return True, "NVIDIA RTX (Turing or newer)"
        if re.search(r"gtx\s*16\d0", g):
            return True, "NVIDIA GTX 16-series (Turing)"
        if re.search(r"quadro\s*t\d", g):
            return True, "NVIDIA Quadro T-series (Turing)"
        return False, ("NVIDIA pre-Turing (Pascal, Maxwell, Kepler or Tesla) - "
                       "this driver does not support HAGS")

    # ---------------- AMD ----------------
    m = re.search(r"rx\s*(\d{4})", g)
    if m:
        if int(m.group(1)) >= 5000:
            return True, "AMD RDNA (RX 5000 series or newer)"
        return False, ("AMD pre-RDNA (Polaris or Vega) - "
                       "this driver does not support HAGS")
    if any(k in g for k in ("radeon", "amd", "ati ")):
        return False, "AMD pre-RDNA or unrecognised generation - not enabling"

    # ---------------- Intel ----------------
    if "arc" in g:
        return True, "Intel Arc (Xe HPG)"
    if "intel" in g:
        return False, "Intel integrated graphics - HAGS unsupported"

    return False, f"unrecognised GPU ({gpu_name}) - not enabling"


def hags_mode_for(gpu_name: str, vram_mb: int | None = None) -> tuple[int, bool, str]:
    """(mode to write, whether that means enabled, why).

    VRAM is checked first and on its own. A modern card with 2 GB is refused just as
    a 2009 card is, because the reason is different from the generation reason and
    the user should be told which one applied.
    """
    if vram_mb is not None and vram_mb > 0 and vram_mb <= MIN_VRAM_MB:
        return HAGS_OFF, False, (f"{vram_mb} MB VRAM - at or below {MIN_VRAM_MB} MB, "
                                 "HAGS would cost more than it saves")
    ok, why = hags_supported(gpu_name)
    if ok and vram_mb is None:
        return HAGS_ON, True, why + " (VRAM not reported, generation only)"
    return (HAGS_ON if ok else HAGS_OFF), ok, why


def hags_mode_for_game(gpu_name: str, vram_mb: int | None, game_key: str = "none",
                       ) -> tuple[int, bool, str]:
    """The full decision, including the game being played.

    Order matters, and it is deliberate:

      1. The game's requirement. If the card is short of the memory that title
         wants, HAGS goes off whatever the GPU is - this is the case the user
         asked for, and it is the one where HAGS actively hurts.
      2. The 2 GB floor, for anything else.
      3. Whether the driver supports HAGS at all.
    """
    label, need, _cat = game_choice(game_key)
    if need > 0 and vram_mb is not None and 0 < vram_mb < need:
        return HAGS_OFF, False, (f"{label} wants about {need} MB of video memory and this "
                                 f"card has {vram_mb} MB - HAGS stays off while it is short")
    return hags_mode_for(gpu_name, vram_mb)


def describe_action(gpu_name: str, vram_mb: int | None = None) -> str:
    mode, ok, why = hags_mode_for(gpu_name, vram_mb)
    return f"HAGS {'ENABLED' if ok else 'LEFT OFF'} (mode {mode}) - {why}"


# ============================================================================
#  GAME VRAM TARGETS
#
#  Why this exists: HAGS is not free. It moves scheduling into the driver, and
#  when the card is already short on video memory for the game being played, that
#  overhead lands on exactly the resource that is running out - which shows up as
#  stutter, not as a smoother frame time.
#
#  So the game being played becomes part of the decision. Pick a title and, if
#  the card does not have the memory that title wants, HAGS is turned off.
#
#  The figures are approximate VRAM GUIDANCE for 1080p, not vendor minimums, and
#  they are deliberately conservative - being told to leave HAGS off on a card
#  that could just about cope costs a little efficiency, while being told to turn
#  it on when the card is already paging costs frame time.
# ============================================================================
GAMES = {
    "none":        ("Not playing a specific game", 0,    ""),
    # esports and light titles - comfortably inside 2 GB
    "valorant":    ("VALORANT",                    2048, "esports"),
    "cs2":         ("Counter-Strike 2",            2048, "esports"),
    "lol":         ("League of Legends",           2048, "esports"),
    "dota2":       ("Dota 2",                      2048, "esports"),
    "rocket":      ("Rocket League",               2048, "esports"),
    "overwatch2":  ("Overwatch 2",                 2048, "esports"),
    "rainbow6":    ("Rainbow Six Siege",           3072, "esports"),
    # mid-weight
    "thefinals":   ("THE FINALS",                  4096, "mid"),
    "marvelrivals":("Marvel Rivals",               4096, "mid"),
    "fortnite":    ("Fortnite",                    4096, "mid"),
    "gtav":        ("GTA V",                       4096, "mid"),
    "apex":        ("Apex Legends",                6144, "mid"),
    "rdr2":        ("Red Dead Redemption 2",       6144, "mid"),
    "helldivers2": ("Helldivers 2",                6144, "mid"),
    "pubg":        ("PUBG: Battlegrounds",         6144, "mid"),
    "destiny2":    ("Destiny 2",                   6144, "mid"),
    "warframe":    ("Warframe",                    4096, "mid"),
    "monsterhunterworld": ("Monster Hunter: World", 6144, "mid"),
    "witcher3":    ("The Witcher 3",               6144, "mid"),
    # AAA and heavy
    "cyberpunk":   ("Cyberpunk 2077",              6144, "aaa"),
    "cyberpunk_rt":("Cyberpunk 2077 (ray tracing)",12288, "aaa"),
    "eldenring":   ("Elden Ring",                  8192, "aaa"),
    "starfield":   ("Starfield",                   8192, "aaa"),
    "hogwarts":    ("Hogwarts Legacy",             8192, "aaa"),
    "alanwake2":   ("Alan Wake 2",                 8192, "aaa"),
    "bf2042":      ("Battlefield 2042",            8192, "aaa"),
    "warzone":     ("Call of Duty: Warzone",       8192, "aaa"),
    "forza5":      ("Forza Horizon 5",             8192, "aaa"),
    "msfs":        ("Microsoft Flight Simulator",  8192, "aaa"),
    "bg3":         ("Baldur's Gate 3",             8192, "aaa"),
    "tarkov":      ("Escape from Tarkov",          8192, "aaa"),
    "rust":        ("Rust",                        8192, "aaa"),
    "mhwilds":     ("Monster Hunter Wilds",        8192, "aaa"),
    "wukong":      ("Black Myth: Wukong",          8192, "aaa"),
    "stalker2":    ("S.T.A.L.K.E.R. 2",            8192, "aaa"),
    "dd2":         ("Dragon's Dogma 2",            8192, "aaa"),
    "horizonfw":   ("Horizon Forbidden West",      8192, "aaa"),
    "spiderman2":  ("Marvel's Spider-Man 2",       8192, "aaa"),
    "indianajones":("Indiana Jones and the Great Circle", 8192, "aaa"),
}

GAME_CATEGORIES = [("esports", "Esports / light"),
                   ("mid", "Mid-weight"),
                   ("aaa", "AAA / heavy")]


def game_choice(key):
    """(label, required_mb, category) for a key, falling back to 'not playing'."""
    return GAMES.get((key or "none").lower(), GAMES["none"])


def games_in(category):
    return [(k, v[0], v[1]) for k, v in GAMES.items() if v[2] == category]

