"""Per-chat speed settings and the last observed Responses request, scoped to CODEX_HOME."""
from contextlib import closing
import gzip
import io
import json
import sqlite3
import tomllib
import zlib

from bindings import InputError, thread_id

MODES = ('inherit', 'priority', 'default')
TIERS = ('priority', 'default', 'auto', 'flex', 'scale', 'ultrafast')
BODY_LIMIT = 256 * 1024 * 1024


def shared_tier(config):
    profile = config.get('profile')
    overrides = config.get('profiles', {}).get(profile, {}) if isinstance(profile, str) else {}
    tier = overrides.get('service_tier', config.get('service_tier'))
    return 'priority' if tier == 'fast' else tier if tier in TIERS else None


class SpeedStore:
    def __init__(self, home):
        self.home = home
        self.path = home / 'thread-provider-card' / 'speed.sqlite3'

    def _reader(self, sql, tid):
        if not self.path.is_file():
            return None
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=1)) as db:
            return db.execute(sql, (tid,)).fetchone()

    def _writer(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS choices (thread TEXT PRIMARY KEY, mode TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS receipts (thread TEXT PRIMARY KEY, sent INTEGER NOT NULL, tier TEXT, status INTEGER NOT NULL)')
            return db
        except Exception:
            db.close()
            raise

    def mode(self, tid):
        row = self._reader('SELECT mode FROM choices WHERE thread=?', thread_id(tid))
        return row[0] if row and row[0] in MODES else 'inherit'

    def choose(self, tid, mode):
        tid = thread_id(tid)
        if mode not in MODES:
            raise InputError('无效的速度档位。')
        with closing(self._writer()) as db, db:
            if mode == 'inherit':
                db.execute('DELETE FROM choices WHERE thread=?', (tid,))
            else:
                db.execute('INSERT OR REPLACE INTO choices VALUES (?,?)', (tid, mode))

    def snapshot(self, tid):
        tid = thread_id(tid)
        mode = self.mode(tid)
        cfg = tomllib.loads((self.home / 'config.toml').read_text(encoding='utf-8-sig'))
        row = self._reader('SELECT tier,status FROM receipts WHERE thread=?', tid)
        return dict(mode=mode, effectiveTier=shared_tier(cfg) if mode == 'inherit' else mode,
                    lastTier=row[0] if row else None, lastStatus=row[1] if row else None)

    def record(self, tid, sent, tier, status):
        # Only the newest request per chat wins, even when responses arrive out of order.
        try:
            with closing(self._writer()) as db, db:
                db.execute('''INSERT INTO receipts VALUES (?,?,?,?) ON CONFLICT(thread) DO UPDATE SET
                    sent=excluded.sent,tier=excluded.tier,status=excluded.status WHERE excluded.sent >= receipts.sent''',
                           (thread_id(tid), sent, tier if tier in TIERS else None, status))
                db.execute('DELETE FROM receipts WHERE thread IN (SELECT thread FROM receipts ORDER BY sent DESC LIMIT -1 OFFSET 256)')
        except (OSError, sqlite3.Error):
            pass  # Displaying a receipt must never interrupt a request or its stream.


class SpeedPayloadError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def prepare(body, encoding, tier):
    """Keep original bytes/encoding unless this generation needs a different service_tier."""
    encoding = (encoding or 'identity').strip().lower()
    if encoding not in ('identity', 'gzip'):
        if tier is None:
            return body, None
        raise SpeedPayloadError(415, 'Speed selection requires an uncompressed or gzip JSON request.')
    try:
        raw = body
        if encoding == 'gzip':
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                raw = compressed.read(BODY_LIMIT + 1)
            if len(raw) > BODY_LIMIT:
                raise SpeedPayloadError(413, 'Uncompressed request body is too large.')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
    except SpeedPayloadError:
        raise
    except (OSError, EOFError, ValueError, RecursionError, zlib.error):
        if tier is None:
            return body, None
        raise SpeedPayloadError(400, 'Could not apply speed to this Responses JSON body.') from None
    original = data.get('service_tier')
    if tier is None or tier == original:
        return body, original if original in TIERS else None
    data['service_tier'] = tier
    updated = json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return (gzip.compress(updated, compresslevel=1, mtime=0) if encoding == 'gzip' else updated), tier
