"""PubPartner stepping stones: sentence-sized memories that are recalled by overlap.

What this is
------------
Every private message a person sends is split into sentences (``pubpartner_stone_text``).
Each sentence is stored as a *stone* with six questions asked of it (who, what, where,
when, why, how). A question is either answered with the person's exact words or marked
unknown. Stones are recalled by overlapping circles of words, names, roles and places,
weighted by how rare each is for this person, so a word everyone uses carries almost no
weight and a name or an unusual word carries a lot. Each recalled stone says *why* it was
recalled.

What this is not
----------------
- It does not decide what is true. A stone is what the person said, when, and how they
  said it (statement, question, tentative, hypothetical). Whether a lasting fact has been
  confirmed is the vessel's job (claims and evidence), not this module's.
- It does not edit Jeremy (``jeremy_cricket`` is shared and pinned). It sits beside it, and
  ``fuse`` merges the two lists.
- It does not call a model, a network or an embedding service. Meaning-based recall,
  co-occurrence trails beyond one step, confidence bands and verify-or-ask behaviour are
  separate, later work (see docs/PUBPARTNER_RECALL_STONES_2026-11-28.md).

Privacy
-------
One SQLite file per (user, friend). Recall can never cross users or friends, because there is
no query that spans files. Callers admit only private-audience messages; this module enforces
the part it can: it ingests ``kind == "message"`` only.

Rebuild
-------
Stones are derived from the verbatim vault, which stays the source of truth. ``sync_from_vault``
rebuilds or backfills them; deleting the stones folder loses nothing that the vault does not hold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # package import (hosted app) and flat import (tests, CLI) both work
    from .pubpartner_stone_text import (
        SLOTS, StoneDraft, capitalized_candidates, grounding_problems, read_message, terms as text_terms,
    )
except ImportError:  # pragma: no cover - exercised when run as a script
    from pubpartner_stone_text import (  # type: ignore
        SLOTS, StoneDraft, capitalized_candidates, grounding_problems, read_message, terms as text_terms,
    )

READER_VERSION = 1
SCHEMA_VERSION = 1

# How much a match in each circle counts. A name is the strongest anchor a memory has.
KIND_WEIGHT = {"w": 1.0, "n": 1.6, "r": 1.2, "p": 1.2}
MODALITY_WEIGHT = {"statement": 1.0, "quoted": 0.8, "tentative": 0.85, "hypothetical": 0.6, "question": 0.55}
EXPIRED_SITUATIONAL_WEIGHT = 0.25
MIN_SCORE = 0.6
# Rarity is measured against the person's other memories, plus this many imagined unrelated ones. Without the prior, a
# person's first few memories would all look "common" (a word in 2 of 2 memories is in every memory) and nothing would ever
# come back until they had written a lot. With it, a young store behaves like a store that already holds some unrelated things.
IDF_PRIOR = 20.0
SINGLE_WORD_MIN_SCORE = 1.0   # one ordinary word alone must be fairly rare to bring a memory back
RING_WEIGHT = 0.6
MAX_QUERY_TERMS = 32
MAX_ROWS_PER_TERM = 5000
JEREMY_WEIGHT = 0.5
STONE_WEIGHT = 1.0
RRF_K = 60

_SOURCE_ID_RE = re.compile(r"src_\d+_[0-9a-f]{12}_[0-9a-f]{8}")


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("._-")
    return (cleaned or fallback)[:48]


def _file_stem(value: str, fallback: str) -> str:
    """Readable and collision-proof: two different ids that slug alike still get different files."""
    digest = hashlib.sha256(str(value or fallback).encode("utf-8")).hexdigest()[:10]
    return f"{_slug(value, fallback)}-{digest}"


def _idf(total: int, df: int) -> float:
    """How much a word that appears in ``df`` of ``total`` memories tells one memory from another (BM25 form, smoothed)."""
    return math.log(1.0 + (total - df + 0.5 + IDF_PRIOR) / (df + 0.5))


def _date(epoch: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(max(0.0, float(epoch))))


# ------------------------------------------------------------------------------- shapes

@dataclass
class Recalled:
    """One stone brought back, with the reasons."""

    stone_id: int
    source_id: str
    session_id: str
    excerpt: str
    answers: Dict[str, Any]
    modality: str
    temporal: str
    importance: int
    created_at: float
    score: float
    ring: int                      # 1 = overlaps the query itself; 2 = shares a name or role with a ring-1 stone
    matched: List[str] = field(default_factory=list)
    via: str = ""                  # for ring 2: the name or role that links it
    expired: bool = False          # a "today" statement whose day has passed
    unresolved: bool = False       # opens with he/she/it/they and no name: who is not known
    project_id: str = ""
    room_id: str = ""

    def stated(self, slot: str) -> List[str]:
        answer = self.answers.get(slot) or {}
        if answer.get("state") != "stated":
            return []
        return [str(f.get("text", "")) for f in answer.get("fragments", []) if f.get("text")]


@dataclass(frozen=True)
class FusionItem:
    key: str
    source_id: str
    payload: Any


# ------------------------------------------------------------------------------- store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', room_id TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, ingested_at REAL NOT NULL, reader_version INTEGER NOT NULL,
    stone_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stones (
    stone_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
    excerpt TEXT NOT NULL, answers_json TEXT NOT NULL,
    modality TEXT NOT NULL, temporal TEXT NOT NULL, importance INTEGER NOT NULL,
    unresolved INTEGER NOT NULL DEFAULT 0, expires_after REAL,
    created_at REAL NOT NULL, session_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '', room_id TEXT NOT NULL DEFAULT '',
    reading TEXT NOT NULL, term_count INTEGER NOT NULL DEFAULT 0,
    surfaced_count INTEGER NOT NULL DEFAULT 0, last_surfaced_at REAL,
    UNIQUE (source_id, ordinal)
);
CREATE TABLE IF NOT EXISTS terms (
    stone_id INTEGER NOT NULL REFERENCES stones(stone_id) ON DELETE CASCADE,
    term TEXT NOT NULL, kind TEXT NOT NULL,
    PRIMARY KEY (stone_id, term, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS terms_by_term ON terms (term);
CREATE TABLE IF NOT EXISTS names (key TEXT PRIMARY KEY, display TEXT NOT NULL, mentions INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS stones_by_source ON stones (source_id);
"""

_CHUNK = 400


def _chunks(values: Sequence[Any], size: int = _CHUNK) -> Iterable[Sequence[Any]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


class StoneStore:
    """The stones of one person for one friend. Each call opens and closes its own connection."""

    def __init__(self, path: Path, *, user_id: str, friend_id: str) -> None:
        self.path = Path(path)
        self.user_id = user_id
        self.friend_id = friend_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('user_id', ?), ('friend_id', ?)",
                             (user_id, friend_id))
            elif version > SCHEMA_VERSION:
                raise RuntimeError(f"stones database {self.path} is from a newer version ({version}); refusing to touch it")
            conn.commit()

    # -- plumbing

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    # -- writing

    def has_source(self, source_id: str) -> bool:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone() is not None

    def ingest(
        self,
        *,
        source_id: str,
        session_id: str,
        text: str,
        created_at: float,
        language: str = "en",
        project_id: str = "",
        room_id: str = "",
        sha256: str = "",
        kind: str = "message",
    ) -> Dict[str, Any]:
        """Read one message into stones. Idempotent: a source already read is left alone."""
        if kind != "message":
            return {"status": "skipped", "reason": f"kind {kind!r} is not conversation", "stones": 0}
        if not isinstance(text, str) or not text.strip():
            return {"status": "skipped", "reason": "empty", "stones": 0}
        if sha256 and hashlib.sha256(text.encode("utf-8")).hexdigest() != sha256:
            return {"status": "refused", "reason": "text does not match the recorded sha256", "stones": 0}
        with closing(self._connect()) as conn:
            if conn.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone():
                return {"status": "already_ingested", "stones": 0}
            candidates = sorted(capitalized_candidates(text))[:2000]
            known = set()
            for chunk in _chunks(candidates):
                marks = ",".join("?" * len(chunk))
                known.update(row[0] for row in conn.execute(f"SELECT key FROM names WHERE key IN ({marks})", list(chunk)))
            drafts = read_message(text, language=language, known_names=known)
            problems: List[str] = []
            good: List[StoneDraft] = []
            for draft in drafts:
                found = grounding_problems(text, draft)
                if found:
                    problems.extend(found)  # an ungrounded answer is never stored; the stone is dropped, not repaired
                else:
                    good.append(draft)
            now = time.time()
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone():
                    conn.execute("ROLLBACK")
                    return {"status": "already_ingested", "stones": 0}
                conn.execute(
                    "INSERT INTO sources (source_id, session_id, project_id, room_id, sha256, created_at, ingested_at, reader_version, stone_count)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (source_id, session_id, project_id, room_id, sha256, float(created_at), now, READER_VERSION, len(good)),
                )
                for draft in good:
                    expires = (float(created_at) + draft.expires_after_seconds) if draft.expires_after_seconds else None
                    cursor = conn.execute(
                        'INSERT INTO stones (source_id, ordinal, start, "end", excerpt, answers_json, modality, temporal, importance,'
                        " unresolved, expires_after, created_at, session_id, project_id, room_id, reading, term_count)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (source_id, draft.ordinal, draft.start, draft.end, draft.excerpt,
                         json.dumps(draft.answers_dict(), ensure_ascii=False), draft.modality, draft.temporal,
                         int(draft.importance), 1 if draft.unresolved_reference else 0, expires, float(created_at),
                         session_id, project_id, room_id, draft.reading, len(draft.word_terms)),
                    )
                    stone_id = cursor.lastrowid
                    rows = ([(stone_id, t, "w") for t in draft.word_terms] + [(stone_id, t, "n") for t in draft.name_terms]
                            + [(stone_id, t, "r") for t in draft.role_terms] + [(stone_id, t, "p") for t in draft.place_terms])
                    conn.executemany("INSERT OR IGNORE INTO terms (stone_id, term, kind) VALUES (?,?,?)", rows)
                    display = dict(draft.new_names)
                    for key in draft.name_terms:
                        conn.execute(
                            "INSERT INTO names (key, display, mentions) VALUES (?,?,1)"
                            " ON CONFLICT(key) DO UPDATE SET mentions = mentions + 1",
                            (key, display.get(key, key)),
                        )
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        result: Dict[str, Any] = {"status": "ingested", "stones": len(good)}
        if problems:
            result["dropped_ungrounded"] = problems[:10]
        return result

    def mark_surfaced(self, stone_ids: Iterable[int], *, now: Optional[float] = None) -> int:
        ids = sorted({int(i) for i in stone_ids})
        if not ids:
            return 0
        stamp = time.time() if now is None else float(now)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                conn.execute(
                    f"UPDATE stones SET surfaced_count = surfaced_count + 1, last_surfaced_at = ? WHERE stone_id IN ({marks})",
                    [stamp, *chunk],
                )
            conn.execute("COMMIT")
        return len(ids)

    # -- reading

    def status(self) -> Dict[str, Any]:
        with closing(self._connect()) as conn:
            one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
            stones = one("SELECT COUNT(*) FROM stones")
            stated = {slot: 0 for slot in SLOTS}
            for (blob,) in conn.execute("SELECT answers_json FROM stones"):
                try:
                    answers = json.loads(blob)
                except ValueError:
                    continue
                for slot in SLOTS:
                    if (answers.get(slot) or {}).get("state") == "stated":
                        stated[slot] += 1
            return {
                "path": str(self.path), "sources": one("SELECT COUNT(*) FROM sources"), "stones": stones,
                "names": one("SELECT COUNT(*) FROM names"), "terms": one("SELECT COUNT(*) FROM terms"),
                "slots_stated": stated, "reader_version": READER_VERSION,
                "latest_source_at": conn.execute("SELECT MAX(created_at) FROM sources").fetchone()[0],
            }

    def stones_for_source(self, source_id: str) -> List[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM stones WHERE source_id = ? ORDER BY ordinal", (source_id,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["answers"] = json.loads(item.pop("answers_json"))
            out.append(item)
        return out

    def recall(
        self,
        query: str,
        *,
        limit: int = 6,
        now: Optional[float] = None,
        project_id: Optional[str] = None,
        room_id: Optional[str] = None,
        skip_if_in: Sequence[str] = (),
        ring2_limit: int = 2,
        min_score: float = MIN_SCORE,
    ) -> List[Recalled]:
        """Stones whose circles overlap ``query``, rarest overlaps first, with the reasons.

        Ring 1 is overlap with the query itself. Ring 2 is one step out: lasting facts that share a
        name or role with a top ring-1 stone ("the Dodgers lost" brings back what is known about
        Sam, whose team they are). ``project_id`` / ``room_id`` limit recall to one project or room
        (used by hosts that isolate memory); leave them out to recall across the same friend.
        """
        limit = max(0, int(limit))
        query_terms = text_terms(query)[:MAX_QUERY_TERMS]
        if not limit or not query_terms:
            return []
        stamp = time.time() if now is None else float(now)
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            total = max(1, conn.execute("SELECT COUNT(*) FROM stones").fetchone()[0])
            idf: Dict[str, float] = {}
            df_of: Dict[str, int] = {}
            for term in query_terms:
                df = conn.execute("SELECT COUNT(DISTINCT stone_id) FROM terms WHERE term = ?", (term,)).fetchone()[0]
                if df <= 0:
                    continue
                if df > max(200, total // 2) and len(query_terms) > 1:
                    continue  # appears nearly everywhere: it cannot tell this memory from any other
                df_of[term] = df
                idf[term] = _idf(total, df)
            if not idf:
                return []
            raw: Dict[int, Dict[str, float]] = {}
            strong: Dict[int, bool] = {}
            for term in idf:
                for row in conn.execute("SELECT stone_id, kind FROM terms WHERE term = ? LIMIT ?", (term, MAX_ROWS_PER_TERM)):
                    weight = idf[term] * KIND_WEIGHT.get(row["kind"], 1.0)
                    bucket = raw.setdefault(row["stone_id"], {})
                    bucket[term] = max(bucket.get(term, 0.0), weight)
                    if row["kind"] in ("n", "r", "p"):
                        strong[row["stone_id"]] = True
            candidates = [(sum(hits.values()), stone_id) for stone_id, hits in raw.items()]
            candidates.sort(reverse=True)
            candidates = candidates[:max(60, limit * 12)]
            rows = self._fetch(conn, [stone_id for _, stone_id in candidates], project_id, room_id)
            ring1: List[Recalled] = []
            for base, stone_id in candidates:
                row = rows.get(stone_id)
                if row is None or any(row["excerpt"] in text for text in skip_if_in if text):
                    continue
                score = self._score(base, row, stamp)
                lone_word = len(raw[stone_id]) == 1 and not strong.get(stone_id)
                if score < (max(min_score, SINGLE_WORD_MIN_SCORE) if lone_word else min_score):
                    continue
                ring1.append(self._recalled(row, score, 1, sorted(raw[stone_id], key=lambda t: -raw[stone_id][t]), "", stamp))
            ring1.sort(key=lambda r: (-r.score, -r.stone_id))
            ring1 = ring1[:limit]
            ring2: List[Recalled] = []
            if ring2_limit > 0 and ring1:
                ring2 = self._ring_two(conn, ring1, total, stamp, project_id, room_id, skip_if_in, ring2_limit, min_score)
        return ring1 + ring2

    # -- recall internals

    @staticmethod
    def _fetch(conn: sqlite3.Connection, ids: Sequence[int], project_id: Optional[str], room_id: Optional[str]) -> Dict[int, sqlite3.Row]:
        rows: Dict[int, sqlite3.Row] = {}
        for chunk in _chunks(list(ids)):
            marks = ",".join("?" * len(chunk))
            sql = f"SELECT * FROM stones WHERE stone_id IN ({marks})"
            params: List[Any] = list(chunk)
            if project_id is not None:
                sql += " AND project_id = ?"
                params.append(project_id)
            if room_id is not None:
                sql += " AND room_id = ?"
                params.append(room_id)
            for row in conn.execute(sql, params):
                rows[row["stone_id"]] = row
        return rows

    @staticmethod
    def _multiplier(row: sqlite3.Row, stamp: float) -> float:
        factor = 0.7 + 0.06 * int(row["importance"])
        factor *= MODALITY_WEIGHT.get(row["modality"], 1.0)
        if row["unresolved"]:
            factor *= 0.9
        temporal = row["temporal"]
        if temporal == "situational":
            expires = row["expires_after"]
            if expires is not None and stamp > float(expires):
                factor *= EXPIRED_SITUATIONAL_WEIGHT
        elif temporal != "lasting":
            age_days = max(0.0, stamp - float(row["created_at"])) / 86400.0
            factor *= 0.85 + 0.15 * math.exp(-age_days / 180.0)
        return factor

    def _score(self, base: float, row: sqlite3.Row, stamp: float) -> float:
        length_norm = 1.0 + 0.04 * max(0, int(row["term_count"]) - 10)
        return (base / length_norm) * self._multiplier(row, stamp)

    @staticmethod
    def _recalled(row: sqlite3.Row, score: float, ring: int, matched: List[str], via: str, stamp: float) -> Recalled:
        expires = row["expires_after"]
        return Recalled(
            stone_id=row["stone_id"], source_id=row["source_id"], session_id=row["session_id"], excerpt=row["excerpt"],
            answers=json.loads(row["answers_json"]), modality=row["modality"], temporal=row["temporal"],
            importance=int(row["importance"]), created_at=float(row["created_at"]), score=round(score, 4), ring=ring,
            matched=matched, via=via, expired=bool(row["temporal"] == "situational" and expires is not None and stamp > float(expires)),
            unresolved=bool(row["unresolved"]), project_id=row["project_id"], room_id=row["room_id"],
        )

    def _ring_two(
        self, conn: sqlite3.Connection, ring1: Sequence[Recalled], total: int, stamp: float,
        project_id: Optional[str], room_id: Optional[str], skip_if_in: Sequence[str], want: int, min_score: float,
    ) -> List[Recalled]:
        seen = {item.stone_id for item in ring1}
        anchors: Dict[str, int] = {}  # name or role term -> its document frequency
        for item in ring1[:3]:
            for (term,) in conn.execute("SELECT term FROM terms WHERE stone_id = ? AND kind IN ('n','r')", (item.stone_id,)):
                anchors.setdefault(term, 0)
        scored: Dict[int, Tuple[float, str]] = {}
        for term in anchors:
            df = conn.execute("SELECT COUNT(DISTINCT stone_id) FROM terms WHERE term = ? AND kind IN ('n','r')", (term,)).fetchone()[0]
            if df <= 0 or df > max(40, total // 4):
                continue  # a name attached to a large share of everything links nothing in particular
            weight = _idf(total, df) * RING_WEIGHT
            for (stone_id,) in conn.execute(
                "SELECT stone_id FROM terms WHERE term = ? AND kind IN ('n','r') LIMIT ?", (term, MAX_ROWS_PER_TERM)
            ):
                if stone_id in seen:
                    continue
                if stone_id not in scored or weight > scored[stone_id][0]:
                    scored[stone_id] = (weight, term)
        if not scored:
            return []
        rows = self._fetch(conn, list(scored), project_id, room_id)
        out: List[Recalled] = []
        for stone_id, (weight, term) in scored.items():
            row = rows.get(stone_id)
            if row is None or row["modality"] in ("question", "hypothetical"):
                continue  # a question someone asked, or a what-if, is not something known about the person
            if any(row["excerpt"] in text for text in skip_if_in if text):
                continue
            lasting_boost = 1.5 if row["temporal"] == "lasting" else 1.0
            score = weight * lasting_boost * self._multiplier(row, stamp)
            if score >= min_score * 0.5:
                out.append(self._recalled(row, score, 2, [], term, stamp))
        out.sort(key=lambda r: (-r.score, -r.stone_id))
        return out[:want]


# ---------------------------------------------------------------------------- library

class StoneLibrary:
    """All stone stores under one data folder, found by (user, friend)."""

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "pubpartner" / "stones"
        self._open: Dict[Tuple[str, str], StoneStore] = {}

    def path_for(self, user_id: str, friend_id: str) -> Path:
        return self.root / _file_stem(user_id or "anon", "anon") / f"{_file_stem(friend_id or 'friend', 'friend')}.sqlite3"

    def store(self, user_id: str, friend_id: str) -> StoneStore:
        key = (user_id or "anon", friend_id or "friend")
        found = self._open.get(key)
        if found is None:
            found = StoneStore(self.path_for(*key), user_id=key[0], friend_id=key[1])
            self._open[key] = found
        return found

    def stores_on_disk(self) -> List[Path]:
        return sorted(self.root.glob("*/*.sqlite3")) if self.root.exists() else []

    def sync_state(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.root / "_sync.sqlite3"), timeout=15, isolation_level=None)
        conn.execute("CREATE TABLE IF NOT EXISTS seen (user_dir TEXT NOT NULL, session_dir TEXT NOT NULL, file TEXT NOT NULL,"
                     " outcome TEXT NOT NULL, at REAL NOT NULL, store_path TEXT NOT NULL DEFAULT '',"
                     " PRIMARY KEY (user_dir, session_dir, file)) WITHOUT ROWID")
        return conn


# ----------------------------------------------------------------------- vault rebuild

def sync_from_vault(
    library: StoneLibrary,
    vault: Any,
    *,
    audience_of: Callable[[Any], Optional[str]],
    time_budget_s: float = 5.0,
    max_sources: int = 5000,
    retry_unverified: bool = False,
) -> Dict[str, Any]:
    """Read vault messages that have no stones yet. Safe to call often; stops at the time budget.

    ``audience_of(record)`` must return ``"private"`` only when the turn is known to have been private.
    Anything else (``None`` included) is not read, so a message whose audience cannot be shown is never
    admitted to private memory. Every outcome is remembered, so the next call picks up where this one stopped.
    """
    deadline = time.monotonic() + max(0.0, float(time_budget_s))
    counts = {"ingested": 0, "stones": 0, "already": 0, "not_private": 0, "unverified": 0, "not_message": 0,
              "no_friend": 0, "unreadable": 0, "refused": 0}
    root = Path(vault.root)
    complete = True
    if not root.exists():
        return {"complete": True, **counts}
    with closing(library.sync_state()) as state:
        # A stones file that was deleted loses its messages' "already read" marks, so they are read again.
        for (store_path,) in state.execute("SELECT DISTINCT store_path FROM seen WHERE store_path != ''").fetchall():
            if not Path(store_path).exists():
                state.execute("DELETE FROM seen WHERE store_path = ?", (store_path,))
        seen_total = 0
        for user_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for session_dir in sorted(p for p in user_dir.iterdir() if p.is_dir()):
                done = {
                    row[0]: row[1] for row in state.execute(
                        "SELECT file, outcome FROM seen WHERE user_dir = ? AND session_dir = ?", (user_dir.name, session_dir.name))
                }
                for record_file in sorted(session_dir.glob("src_*.json")):
                    previous = done.get(record_file.name)
                    if previous is not None and not (retry_unverified and previous == "unverified"):
                        continue
                    if time.monotonic() > deadline or seen_total >= max_sources:
                        complete = False
                        break
                    seen_total += 1
                    outcome, store_path = _sync_one(library, vault, user_dir.name, session_dir.name, record_file, audience_of, counts)
                    if outcome:
                        state.execute("INSERT OR REPLACE INTO seen (user_dir, session_dir, file, outcome, at, store_path) VALUES (?,?,?,?,?,?)",
                                      (user_dir.name, session_dir.name, record_file.name, outcome, time.time(), store_path))
                if not complete:
                    break
            if not complete:
                break
    return {"complete": complete, **counts}


def _sync_one(library: StoneLibrary, vault: Any, user_dir: str, session_dir: str, record_file: Path,
              audience_of: Callable[[Any], Optional[str]], counts: Dict[str, int]) -> Tuple[Optional[str], str]:
    """Returns ``(outcome, stones file)``: the outcome to remember, or None to look again next time (a read that failed
    may be a passing fault). The stones file is named only when the message went into one."""
    try:
        record = vault.load(user_id=user_dir, session_id=session_dir, source_id=record_file.stem)
    except Exception:
        counts["unreadable"] += 1
        return None, ""  # the vault refused it (hash mismatch, missing sidecar); never read around that
    if record.kind != "message":
        counts["not_message"] += 1
        return "not_message", ""
    friend_id = str((record.metadata or {}).get("friend_id") or "")
    if not friend_id:
        counts["no_friend"] += 1
        return "no_friend", ""
    audience = audience_of(record)
    if audience is None:
        counts["unverified"] += 1
        return "unverified", ""
    if audience != "private":
        counts["not_private"] += 1
        return "not_private", ""
    store = library.store(record.user_id, friend_id)
    result = store.ingest(
        source_id=record.source_id, session_id=record.session_id, text=record.text, created_at=record.created_at,
        language=record.language, project_id=str((record.metadata or {}).get("project_id") or ""),
        room_id=str((record.metadata or {}).get("room_id") or ""), sha256=record.sha256, kind=record.kind,
    )
    status = result["status"]
    if status == "ingested":
        counts["ingested"] += 1
        counts["stones"] += int(result["stones"])
        return "ingested", str(store.path)
    if status == "already_ingested":
        counts["already"] += 1
        return "ingested", str(store.path)
    counts["refused"] += 1
    return None, ""


# ------------------------------------------------------------------------------ fusion

def fuse(
    stones: Sequence[FusionItem],
    jeremy: Sequence[FusionItem],
    *,
    limit: int,
    exclude_source_ids: Iterable[str] = (),
    stone_weight: float = STONE_WEIGHT,
    jeremy_weight: float = JEREMY_WEIGHT,
) -> List[Any]:
    """Merge two ranked lists into one (weighted reciprocal rank fusion) and drop what repeats itself.

    - A Jeremy memory that is only a pointer to a message already represented by a recalled stone is
      dropped: the stone is the sentence that mattered, the pointer is the whole message.
    - A Jeremy memory that points at a source in ``exclude_source_ids`` (the message being answered right
      now) is dropped: it matches itself and says nothing the person did not just say.
    - When Jeremy has anything left, it keeps at least one slot per three, so memories only Jeremy holds
      are never starved out.
    Returns the payloads, best first.
    """
    limit = max(0, int(limit))
    if not limit:
        return []
    excluded = set(exclude_source_ids)
    covered = {item.source_id for item in stones if item.source_id}
    kept_jeremy: List[FusionItem] = []
    seen_text = set()
    for item in jeremy:
        referenced = set(_SOURCE_ID_RE.findall(item.key)) if item.key else set()
        if item.source_id:
            referenced.add(item.source_id)
        if referenced & excluded or referenced & covered:
            continue
        if item.key in seen_text:
            continue
        seen_text.add(item.key)
        kept_jeremy.append(item)
    scored: List[Tuple[float, int, str, Any]] = []
    for rank, item in enumerate(stones):
        scored.append((stone_weight / (RRF_K + rank), 0, "s", item.payload))
    for rank, item in enumerate(kept_jeremy):
        scored.append((jeremy_weight / (RRF_K + rank), 1, "j", item.payload))
    scored.sort(key=lambda row: (-row[0], row[1]))
    reserve = min(len(kept_jeremy), max(1, limit // 3)) if kept_jeremy else 0
    chosen: List[Tuple[float, int, str, Any]] = []
    jeremy_taken = 0
    stone_cap = limit - reserve
    stone_taken = 0
    for row in scored:
        if len(chosen) >= limit:
            break
        if row[2] == "s":
            if stone_taken >= stone_cap and jeremy_taken < reserve:
                continue
            stone_taken += 1
        else:
            jeremy_taken += 1
        chosen.append(row)
    return [row[3] for row in chosen]


# ------------------------------------------------------------------------ explanations

_TEMPORAL_NOTE = {
    "lasting": "described as lasting",
    "situational": "about that day",
    "dated": "about a specific time",
    "unknown": "",
}
_MODALITY_NOTE = {
    "question": "asked as a question",
    "hypothetical": "said as a what-if",
    "tentative": "said tentatively",
    "quoted": "contains a quotation",
    "statement": "",
}


def explain(item: Recalled, *, max_chars: int = 240) -> str:
    """One plain line saying why this came back and how far to trust it. Exact words only; nothing inferred."""
    parts: List[str] = []
    if item.ring == 1 and item.matched:
        parts.append("matched " + ", ".join(item.matched[:4]))
    elif item.ring == 2 and item.via:
        parts.append("same name or role: " + item.via)
    parts.append("said " + _date(item.created_at))
    note = _TEMPORAL_NOTE.get(item.temporal, "")
    if item.expired:
        note = "was about that day, may be out of date"
    for text in (note, _MODALITY_NOTE.get(item.modality, "")):
        if text:
            parts.append(text)
    if item.unresolved:
        parts.append("he/she/it/they not tied to a person here")
    known = []
    for slot in ("who", "where", "when", "why", "how"):
        words = item.stated(slot)
        if words:
            suffix = " (motive, not a result)" if slot == "why" and (item.answers.get("why") or {}).get("mode") == "motive" else ""
            known.append(f"{slot}: {'; '.join(words)[:60]}{suffix}")
    if known:
        parts.append(" | ".join(known))
    line = " | ".join(parts)
    return line if len(line) <= max_chars else line[:max_chars - 1] + "…"


# --------------------------------------------------------------------------------- CLI

def _cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pubpartner_stones", description="Inspect PubPartner stepping stones.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "search"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--user", required=True)
        p.add_argument("--friend", required=True)
        if name == "search":
            p.add_argument("--query", required=True)
            p.add_argument("--limit", type=int, default=6)
    args = parser.parse_args(argv)
    library = StoneLibrary(Path(args.data_dir))
    if not library.path_for(args.user, args.friend).exists():
        print(json.dumps({"ok": False, "error": "no stones for this user and friend yet"}))
        return 1
    store = library.store(args.user, args.friend)
    if args.command == "status":
        print(json.dumps({"ok": True, **store.status()}, indent=2, ensure_ascii=False))
        return 0
    rows = store.recall(args.query, limit=args.limit)
    print(json.dumps({"ok": True, "results": [
        {"stone_id": r.stone_id, "ring": r.ring, "score": r.score, "excerpt": r.excerpt, "why": explain(r)} for r in rows
    ]}, indent=2, ensure_ascii=False))
    return 0


__all__ = [
    "Recalled", "FusionItem", "StoneStore", "StoneLibrary", "sync_from_vault", "fuse", "explain",
    "READER_VERSION", "MIN_SCORE", "JEREMY_WEIGHT", "STONE_WEIGHT",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())

