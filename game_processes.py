"""Which executable belongs to which catalogue entry.

This is a HINT table, not a fact table. Two things follow from that:

  * The selector shows the mapping in the UI, so a wrong entry is visible rather
    than silent, and one click reassigns the process in front of the user to the
    entry they pick (written to games_user.json, which overrides this file).
  * A title with no reliable executable name here simply has no mapping. The tool
    still works - it just will not auto-select that title. An absent mapping costs
    one click; a wrong mapping silently applies the wrong policy.
"""
from __future__ import annotations

import json
from pathlib import Path

# Files that are launchers, anti-cheat wrappers or crash handlers rather than the
# game itself. If one of these is in front, it is not a signal about the workload.
IGNORED = {
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "galaxyclient.exe",
    "battle.net.exe", "ubisoftconnect.exe", "eadesktop.exe", "goggalaxy.exe",
    "rockstargameslauncher.exe", "playnite.desktopapp.exe", "explorer.exe",
    "start_protected_game.exe", "easyanticheat.exe", "easyanticheat_eos.exe",
    "beservice.exe", "battleye.exe", "vgc.exe", "vgk.exe",
}

# game key -> executable names, lowercase, as GetWindowThreadProcessId reports them
GAME_PROCESSES = {
    # esports / light
    "valorant":      ["valorant-win64-shipping.exe"],
    "cs2":           ["cs2.exe"],
    "lol":           ["league of legends.exe"],
    "dota2":         ["dota2.exe"],
    "rocket":        ["rocketleague.exe"],
    "overwatch2":    ["overwatch.exe"],
    "rainbow6":      ["rainbowsix.exe"],
    # mid-weight
    "fortnite":      ["fortniteclient-win64-shipping.exe"],
    "gtav":          ["gta5.exe", "gta5_enhanced.exe"],
    "apex":          ["r5apex.exe", "r5apex_dx12.exe"],
    "rdr2":          ["rdr2.exe"],
    "helldivers2":   ["helldivers2.exe"],
    "pubg":          ["tslgame.exe"],
    "destiny2":      ["destiny2.exe"],
    "warframe":      ["warframe.x64.exe"],
    "monsterhunterworld": ["monsterhunterworld.exe"],
    "witcher3":      ["witcher3.exe"],
    # AAA / heavy
    "cyberpunk":     ["cyberpunk2077.exe"],
    "cyberpunk_rt":  ["cyberpunk2077.exe"],
    "eldenring":     ["eldenring.exe"],
    "starfield":     ["starfield.exe"],
    "hogwarts":      ["hogwartslegacy.exe"],
    "alanwake2":     ["alanwake2.exe"],
    "bf2042":        ["bf2042.exe"],
    "warzone":       ["cod.exe"],
    "forza5":        ["forzahorizon5.exe"],
    "msfs":          ["flightsimulator.exe", "flightsimulator2024.exe"],
    "bg3":           ["bg3.exe", "bg3_dx11.exe"],
    "tarkov":        ["escapefromtarkov.exe"],
    "rust":          ["rustclient.exe"],
    "mhwilds":       ["monsterhunterwilds.exe"],
    "wukong":        ["b1-win64-shipping.exe"],
    "stalker2":      ["stalker2-win64-shipping.exe"],
    "dd2":           ["dd2.exe"],
    "horizonfw":     ["horizonforbiddenwest.exe"],
    "indianajones":  ["thegreatcircle.exe"],
}

# Titles deliberately left unmapped - the executable name is not known here, and
# guessing it would apply another game's policy. The UI offers a one-click fix.
UNMAPPED = ["thefinals", "marvelrivals", "spiderman2"]

_USER_FILE = "games_user.json"

# how many entries we recognise, for the UI to report honestly
TOTAL_MAPPED = len(GAME_PROCESSES)


def _user_map(path: Path | None = None) -> dict:
    """Overrides the user has made: {"<exe>": "<game key>"}."""
    p = path or (_app_dir() / _USER_FILE)
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items() if isinstance(v, str)}


def _app_dir() -> Path:
    import hags_host
    return hags_host.app_dir()


def save_user_mapping(exe_name: str, game_key: str) -> bool:
    exe = (exe_name or "").lower().strip()
    if not exe:
        return False
    p = _app_dir() / _USER_FILE
    data = _user_map(p)
    data[exe] = game_key
    try:
        p.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return True
    except OSError:
        return False


def reverse_map(user_file: Path | None = None) -> dict:
    """exe name -> game key, with the user's overrides applied last.

    Two catalogue entries can share one executable - Cyberpunk 2077 has a plain
    and a ray-traced entry, both cyberpunk2077.exe. The tie is resolved toward the
    LARGER requirement, because the two errors are not symmetrical: refusing HAGS
    on a card that could just about manage costs a little efficiency, while
    enabling it on a card that is already short of memory costs frame time.
    """
    import hags_policy

    best: dict[str, str] = {}
    for key, exes in GAME_PROCESSES.items():
        need = hags_policy.game_choice(key)[1]
        for exe in exes:
            e = exe.lower()
            if e not in best:
                best[e] = key
                continue
            if need > hags_policy.game_choice(best[e])[1]:
                best[e] = key
    best.update(_user_map(user_file))
    return best


def game_for_process(exe_name: str, user_file: Path | None = None) -> str | None:
    """Catalogue key for an executable name, or None if it is not a game we know."""
    e = (exe_name or "").lower().strip()
    if not e or e in IGNORED:
        return None
    return reverse_map(user_file).get(e)
