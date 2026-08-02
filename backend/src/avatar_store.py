"""
Avatar Store -- passwordless persistence for chat avatars.

Each user is identified by an opaque UUID stored client-side
(IndexedDB / localStorage). A memorable 3-word recovery code is the
account-portable handle: type it on a fresh browser to restore the
uuid. Recovery codes are bcrypt-hashed at rest and the recover
endpoint is per-IP rate-limited (10 attempts / hour).

Data lives in SQLite at <project_root>/data/avatars.db; uploaded
images at <project_root>/images/avatars/<uuid>.<ext>.
"""

import hashlib
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

try:
    import bcrypt  # type: ignore

    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


# Curated 256-word list. 8 bits per word x 3 words = ~24 bits of
# entropy. Combined with the IP rate limit on /recover (10 attempts
# per hour) the worst-case search cost is ~16M hours, which is fine
# for "protect my avatar" but not for anything more sensitive.
_WORDS = [
    "able",
    "acid",
    "aged",
    "also",
    "area",
    "army",
    "arts",
    "aunt",
    "auto",
    "away",
    "baby",
    "back",
    "ball",
    "band",
    "bank",
    "base",
    "bath",
    "beam",
    "bean",
    "bear",
    "bell",
    "belt",
    "best",
    "bike",
    "bird",
    "blue",
    "boat",
    "body",
    "bolt",
    "bone",
    "book",
    "boot",
    "born",
    "bowl",
    "brew",
    "bulb",
    "burn",
    "bush",
    "busy",
    "cake",
    "calf",
    "calm",
    "camp",
    "card",
    "care",
    "case",
    "cash",
    "cast",
    "cave",
    "cell",
    "chef",
    "chip",
    "city",
    "clay",
    "clip",
    "club",
    "coal",
    "coat",
    "code",
    "coin",
    "cold",
    "comb",
    "cone",
    "cook",
    "cope",
    "copy",
    "cord",
    "core",
    "cork",
    "corn",
    "cost",
    "cove",
    "crab",
    "crew",
    "crop",
    "cube",
    "cure",
    "curl",
    "cute",
    "dare",
    "dash",
    "dawn",
    "deep",
    "deer",
    "desk",
    "diet",
    "dock",
    "doll",
    "door",
    "dove",
    "drag",
    "drew",
    "drop",
    "drum",
    "duck",
    "dusk",
    "dust",
    "duty",
    "earn",
    "east",
    "easy",
    "eddy",
    "edge",
    "envy",
    "even",
    "exam",
    "face",
    "fade",
    "fair",
    "farm",
    "fast",
    "feel",
    "fern",
    "ferr",
    "feud",
    "file",
    "film",
    "find",
    "fine",
    "fire",
    "fish",
    "flag",
    "flax",
    "flex",
    "flop",
    "flow",
    "foam",
    "fold",
    "fond",
    "food",
    "fork",
    "form",
    "fort",
    "four",
    "free",
    "frog",
    "fuel",
    "full",
    "fund",
    "fuse",
    "gain",
    "gait",
    "gale",
    "game",
    "gate",
    "gear",
    "gift",
    "give",
    "glad",
    "glee",
    "glow",
    "goal",
    "goat",
    "gold",
    "golf",
    "good",
    "gram",
    "grew",
    "grin",
    "grit",
    "grip",
    "grow",
    "gulf",
    "gull",
    "hail",
    "hair",
    "half",
    "hall",
    "hand",
    "harp",
    "hawk",
    "haze",
    "head",
    "heap",
    "help",
    "herb",
    "hero",
    "high",
    "hike",
    "hill",
    "hint",
    "hive",
    "hold",
    "hole",
    "home",
    "hoof",
    "hope",
    "hose",
    "host",
    "hour",
    "huge",
    "hunt",
    "icon",
    "idea",
    "iron",
    "isle",
    "item",
    "jade",
    "jazz",
    "jeep",
    "jest",
    "joke",
    "jolt",
    "joy",
    "judo",
    "jump",
    "june",
    "kart",
    "keen",
    "kelp",
    "kept",
    "kept",
    "kind",
    "king",
    "kite",
    "kiwi",
    "knee",
    "knit",
    "knob",
    "knot",
    "lace",
    "lake",
    "lamp",
    "lane",
    "lash",
    "lava",
    "lawn",
    "leaf",
    "lean",
    "lens",
    "lift",
    "lime",
    "line",
    "link",
    "lion",
    "list",
    "loaf",
    "loft",
    "long",
    "loom",
    "loop",
    "loud",
    "love",
    "luck",
    "lung",
    "made",
    "mail",
    "main",
    "make",
    "many",
    "mark",
    "mash",
    "mask",
    "math",
    "maze",
    "meal",
]
# Trim duplicates while preserving order (kept/kept slipped in above)
_WORDS = list(dict.fromkeys(_WORDS))
# Backfill so we have exactly 256 unique words. Anything left over
# uses prefixed numerics so the list size is fully deterministic.
_BACKFILL_BASE = [
    "mind",
    "mint",
    "mist",
    "moat",
    "mold",
    "moon",
    "moss",
    "moth",
    "much",
    "mule",
    "must",
    "myth",
    "nail",
    "name",
    "navy",
    "near",
    "neat",
    "neck",
    "nest",
    "news",
    "next",
    "nice",
    "nine",
    "noon",
    "nose",
    "note",
    "oak",
    "oats",
    "ocean",
    "odor",
    "ohm",
    "oil",
    "okra",
    "once",
    "only",
    "open",
    "opus",
    "oral",
    "orca",
    "oven",
    "page",
    "pail",
    "pair",
    "palm",
    "pane",
    "park",
    "pass",
    "past",
    "path",
    "peak",
    "pear",
    "peat",
    "pelt",
    "perk",
    "phlox",
    "pick",
    "pier",
    "pike",
    "pill",
    "pine",
    "ping",
    "pink",
    "pint",
    "pipe",
    "plan",
    "play",
    "plug",
    "plum",
    "plus",
    "poem",
    "poet",
    "pole",
    "pond",
    "pool",
    "pope",
    "post",
    "pour",
    "pram",
    "pray",
    "prep",
    "prim",
    "prop",
    "puck",
    "puff",
    "pull",
    "pulp",
    "pump",
    "punt",
    "pure",
    "push",
    "quad",
    "quay",
    "quiz",
    "race",
    "rage",
    "rail",
    "rain",
    "rake",
    "ramp",
    "rank",
    "rare",
    "rash",
    "raze",
    "read",
    "real",
    "reap",
    "reed",
    "reef",
    "rein",
    "rely",
    "rent",
    "rice",
    "ride",
    "rift",
    "ring",
    "rink",
    "rise",
    "risk",
    "road",
    "robe",
    "rock",
    "rode",
    "roll",
    "roof",
    "rook",
    "room",
    "root",
    "rope",
    "rose",
    "ruby",
    "rude",
    "rule",
    "rune",
    "rust",
    "safe",
    "sail",
    "salt",
    "same",
    "sand",
    "sane",
    "sash",
    "sauce",
    "save",
    "scar",
    "scrap",
    "seal",
    "seam",
    "seed",
    "seek",
    "self",
    "send",
    "ship",
    "shop",
    "show",
    "shy",
    "side",
    "silk",
    "sing",
    "sink",
    "site",
    "size",
    "skim",
    "skin",
    "skip",
    "slab",
    "slap",
    "sled",
    "slim",
    "slip",
    "slot",
    "snap",
    "snow",
    "soap",
    "sock",
    "soda",
    "soft",
    "soil",
    "sole",
    "solo",
    "song",
    "soon",
    "sort",
    "soul",
    "soup",
    "spa",
    "spar",
    "spin",
    "spry",
    "spur",
    "stem",
    "stop",
    "sun",
    "swan",
    "tape",
    "team",
    "tide",
    "tile",
    "time",
    "tint",
    "toad",
    "tone",
    "tool",
    "torch",
    "tour",
    "town",
    "trap",
    "tree",
    "trim",
    "trip",
    "tuft",
    "tuna",
    "turf",
    "tusk",
    "twig",
    "type",
    "user",
    "vase",
    "veil",
    "vein",
    "vine",
    "vivid",
    "vow",
    "wave",
    "wax",
    "well",
    "whim",
    "whip",
    "wing",
    "wink",
    "wire",
    "wise",
    "wolf",
    "wood",
    "wool",
    "word",
    "wren",
    "yarn",
    "yard",
    "year",
    "yoga",
    "yolk",
    "yurt",
    "zebra",
    "zero",
    "zest",
    "zinc",
    "zone",
    "zoom",
]
_WORDS.extend(w for w in _BACKFILL_BASE if w not in _WORDS)
# Force exactly 256 by trimming or padding with a deterministic suffix.
if len(_WORDS) > 256:
    _WORDS = _WORDS[:256]
elif len(_WORDS) < 256:
    pad = 256 - len(_WORDS)
    _WORDS.extend(f"word{i:03d}" for i in range(pad))

WORDLIST_SIZE = len(_WORDS)
if WORDLIST_SIZE != 256:
    raise RuntimeError("Avatar recovery word list must contain exactly 256 entries")


def generate_code() -> str:
    """Pick three words at random. ~24 bits of entropy."""
    return "-".join(secrets.choice(_WORDS) for _ in range(3))


def _hash_code(code: str) -> str:
    """Hash the recovery code so it can be safely stored at rest."""
    if _HAS_BCRYPT:
        return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    # Fallback: salted SHA-256. Weaker than bcrypt but adequate for
    # the threat model (recovery codes have ~24 bits of entropy and
    # /recover is rate-limited per IP).
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + code).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def _verify_code(code: str, code_hash: str) -> bool:
    """Constant-time verify of a recovery code against its stored hash."""
    if code_hash.startswith("sha256$"):
        try:
            _, salt, expected = code_hash.split("$", 2)
        except ValueError:
            return False
        actual = hashlib.sha256((salt + code).encode("utf-8")).hexdigest()
        return secrets.compare_digest(expected, actual)
    if _HAS_BCRYPT:
        try:
            return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    return False


def gravatar_hash(email: str) -> str:
    """Hash an email per Gravatar spec (SHA-256 of lowercased+trimmed)."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


class AvatarStore:
    """Thread-safe SQLite-backed avatar metadata store.

    Schema:
        uuid          TEXT PRIMARY KEY (opaque per-user handle)
        type          TEXT ('uploaded' | 'gravatar')
        code_hash     TEXT (bcrypt or salted sha256 of recovery code)
        avatar_path   TEXT (relative path for uploaded type)
        gravatar_hash TEXT (sha256 of email for gravatar type)
        emby_user_id  TEXT (linked Emby identity, optional)
        created_at    TEXT (ISO8601)
        last_seen     TEXT (ISO8601, bumped on use)

    The serving layer (avatar router) reads `type` and one of
    `avatar_path` / `gravatar_hash` to produce the image response.
    """

    def __init__(self, db_path: Path, avatars_dir: Path, logger):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._avatars_dir = Path(avatars_dir)
        self._avatars_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._logger = logger
        self._init_schema()

    @property
    def avatars_dir(self) -> Path:
        return self._avatars_dir

    def readiness_check(self) -> bool:
        """Verify the database and required avatar storage are usable."""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return self._db_path.parent.is_dir() and self._avatars_dir.is_dir()
        except (OSError, sqlite3.Error):
            return False

    def _connect(self):
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS avatars (
                        uuid          TEXT PRIMARY KEY,
                        type          TEXT NOT NULL,
                        code_hash     TEXT NOT NULL,
                        avatar_path   TEXT,
                        gravatar_hash TEXT,
                        emby_user_id  TEXT,
                        created_at    TEXT NOT NULL,
                        last_seen     TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_avatars_emby_user_id "
                    "ON avatars(emby_user_id) WHERE emby_user_id IS NOT NULL"
                )
            finally:
                conn.close()

    def create_uploaded(self, image_bytes: bytes, ext: str) -> tuple[str, str]:
        """Save an uploaded image and register it. Returns (uuid, code).

        Writes the bytes to <avatars_dir>/<uuid>.<ext> and records the
        relative path on the row. The caller is responsible for
        validating the image type and size beforehand.
        """
        new_uuid = str(uuid.uuid4())
        # Normalise extension so the on-disk filename is predictable.
        ext = ext.lstrip(".").lower() or "bin"
        target = self._avatars_dir / f"{new_uuid}.{ext}"
        target.write_bytes(image_bytes)
        relative_path = target.name  # avatars_dir is the root for serving
        return self._insert(
            new_uuid,
            avatar_type="uploaded",
            avatar_path=relative_path,
        )

    def create_gravatar(self, email: str) -> tuple[str, str]:
        """Register a Gravatar association. Returns (uuid, plaintext code)."""
        new_uuid = str(uuid.uuid4())
        return self._insert(
            new_uuid,
            avatar_type="gravatar",
            gravatar_hash=gravatar_hash(email),
        )

    def _insert(
        self,
        new_uuid: str,
        *,
        avatar_type: str,
        avatar_path: str | None = None,
        gravatar_hash: str | None = None,
    ) -> tuple[str, str]:
        code = generate_code()
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO avatars
                      (uuid, type, code_hash, avatar_path, gravatar_hash,
                       emby_user_id, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (new_uuid, avatar_type, _hash_code(code), avatar_path, gravatar_hash, now, now),
                )
            finally:
                conn.close()
        self._logger.info(f"Created {avatar_type} avatar {new_uuid[:8]}... (bcrypt={_HAS_BCRYPT})")
        return new_uuid, code

    def get(self, avatar_uuid: str) -> dict | None:
        """Look up by uuid. Returns a row dict or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM avatars WHERE uuid = ?", (avatar_uuid,)
                ).fetchone()
            finally:
                conn.close()
        return dict(row) if row else None

    def recover_by_code(self, code: str) -> str | None:
        """Return the uuid whose stored code_hash matches, or None.

        Scans every row; OK at hundreds-of-users scale. If the store
        grows beyond that we add a per-prefix index.
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT uuid, code_hash FROM avatars").fetchall()
            finally:
                conn.close()
        for row in rows:
            if _verify_code(code, row["code_hash"]):
                self.touch(row["uuid"])
                return row["uuid"]
        return None

    def touch(self, avatar_uuid: str) -> None:
        """Bump last_seen so cleanup leaves active users alone."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE avatars SET last_seen = ? WHERE uuid = ?",
                    (now, avatar_uuid),
                )
            finally:
                conn.close()

    def link_emby_user(self, avatar_uuid: str, emby_user_id: str) -> bool:
        """Bind an Emby user id to this avatar (idempotent).

        Returns True on success, False if the row is missing or the
        emby_user_id is already linked to a different uuid.
        """
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT uuid FROM avatars WHERE emby_user_id = ?",
                    (emby_user_id,),
                ).fetchone()
                if existing and existing["uuid"] != avatar_uuid:
                    return False
                updated = conn.execute(
                    "UPDATE avatars SET emby_user_id = ? WHERE uuid = ?",
                    (emby_user_id, avatar_uuid),
                ).rowcount
            finally:
                conn.close()
        return updated > 0

    def find_by_emby_user(self, emby_user_id: str) -> str | None:
        """Return the avatar uuid linked to an Emby user id, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT uuid FROM avatars WHERE emby_user_id = ?",
                    (emby_user_id,),
                ).fetchone()
            finally:
                conn.close()
        return row["uuid"] if row else None

    def delete(self, avatar_uuid: str) -> bool:
        """Remove a row. Caller deletes the on-disk file separately."""
        with self._lock:
            conn = self._connect()
            try:
                deleted = conn.execute(
                    "DELETE FROM avatars WHERE uuid = ?", (avatar_uuid,)
                ).rowcount
            finally:
                conn.close()
        return deleted > 0
