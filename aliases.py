import os, io, datetime
import pandas as pd
from pathlib import Path
from difflib import get_close_matches

BASE_DIR = os.path.dirname(__file__)
FILES = Path(BASE_DIR) / "files"
ALIASES_CSV = FILES / "player_aliases.csv"
FILES.mkdir(exist_ok=True)

ALIAS_COLUMNS = ["username","real_name","norm_username","norm_real_name","source","last_seen","confidence"]

def _normalize(s: str) -> str:
    return (s or "").strip().lower()

def load_aliases() -> pd.DataFrame:
    if not ALIASES_CSV.exists():
        df = pd.DataFrame(columns=ALIAS_COLUMNS)
        df.to_csv(ALIASES_CSV, index=False)
        return df
    df = pd.read_csv(ALIASES_CSV, dtype=str).fillna("")
    # Backfill columns if Datei älter ist
    for c in ALIAS_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df

def save_aliases(df: pd.DataFrame):
    tmp = ALIASES_CSV.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(ALIASES_CSV)

def upsert_alias(username: str, real_name: str, source="manual", confidence=0.9):
    u = username.strip()
    r = real_name.strip()
    today = datetime.date.today().isoformat()
    df = load_aliases()
    norm_u = _normalize(u); norm_r = _normalize(r)

    # existiert schon?
    mask = (df["norm_username"] == norm_u)
    if mask.any():
        i = df[mask].index[0]
        df.loc[i, ["real_name","norm_real_name","source","last_seen","confidence"]] = [r, norm_r, source, today, str(confidence)]
    else:
        row = {
            "username": u, "real_name": r,
            "norm_username": norm_u, "norm_real_name": norm_r,
            "source": source, "last_seen": today, "confidence": str(confidence)
        }
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_aliases(df)

def suggest_real_name(username: str, k: int = 5):
    # Erst aus Events (höchste Priorität)
    best, others = suggest_from_events(username, k=k)
    if best:
        return best, others

    # Fallback: Alias-CSV (bestehende Logik)
    df = load_aliases()
    norm_u = _normalize(username)

    hit = df[df["norm_username"] == norm_u]
    if not hit.empty:
        rn = hit.iloc[0]["real_name"]
        return rn, []

    candidates = df["norm_username"].tolist()
    close = get_close_matches(norm_u, candidates, n=k, cutoff=0.72)
    others = df[df["norm_username"].isin(close)]["real_name"].tolist()

    if not others:
        rn_candidates = df["norm_real_name"].tolist()
        close_rn = get_close_matches(norm_u, rn_candidates, n=k, cutoff=0.72)
        others = df[df["norm_real_name"].isin(close_rn)]["real_name"].tolist()

    best = others[0] if others else ""
    rest = others[1:5] if len(others) > 1 else []
    return best, rest

def bulk_seed_from_players_csv(players_csv_path: str, username_col="Player", realname_col=None, source="import"):
    """
    Initial-Befüllung aus vorhandenen CSVs (z. B. merged.csv_players.csv).
    Wenn es schon eine Spalte mit echtem Namen gibt, diese nutzen.
    """
    if not Path(players_csv_path).exists():
        return 0
    dfp = pd.read_csv(players_csv_path)
    count = 0
    for _, row in dfp.iterrows():
        username = str(row.get(username_col, "")).strip()
        if not username: 
            continue
        real_name = str(row.get(realname_col, "")).strip() if realname_col and realname_col in dfp.columns else ""
        if real_name:
            upsert_alias(username, real_name, source=source, confidence=0.8)
            count += 1
    return count

from collections import Counter
from pathlib import Path

EVENTS_DIR = Path(__file__).parent / "events"


def suggest_from_events(username: str, k: int = 5):
    """
    Sucht Nickname→Realname Zuordnungen in events/*.txt
    Gibt (best, others) zurück
    """
    norm_u = _normalize(username)
    counter = Counter()

    if not EVENTS_DIR.exists():
        return "", []

    for file in EVENTS_DIR.glob("*.txt"):
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for line in lines[1:]:  # erste Zeile = URL
            if "=" not in line:
                continue
            nick, real = line.split("=", 1)
            if _normalize(nick) == norm_u and real.strip():
                counter[real.strip()] += 1

    if not counter:
        return "", []

    most_common = counter.most_common(k)
    best = most_common[0][0]
    others = [name for name, _ in most_common[1:]]

    return best, others
