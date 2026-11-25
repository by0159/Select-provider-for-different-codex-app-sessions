"""Credential operations for the native desktop card. URL/key return through child stdio only."""
import os
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from bindings import Bindings, InputError, thread_id
from speed import SpeedStore


def action(home, store, req):
    label = req.get('label')
    if not isinstance(label, str) or not label.strip():
        raise InputError('请先打开一个已有会话。')
    db = sqlite3.connect((home / 'state_5.sqlite').as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        rows = db.execute("""SELECT id,cwd FROM threads WHERE archived=0 AND agent_path IS NULL
            AND coalesce(nullif(name,''),title)=? ORDER BY updated_at DESC""", (label,)).fetchall()
    finally:
        db.close()
    if not rows:
        raise InputError('尚未找到这段会话。新会话请先发一条消息。')
    if len(rows) > 1 and not req.get('id'):
        return {'choices':[{'id':r[0], 'project':Path(r[1] or '').name} for r in rows]}
    tid = thread_id(req.get('id') or rows[0][0])
    if not any(r[0]==tid for r in rows):
        raise InputError('会话已改变，请重新打开卡片。')
    op = req.get('op')
    if op in ('speed_read', 'speed_save'):
        if req.get('id') != tid:
            raise InputError('请先选定会话。')
        speed = SpeedStore(home)
        if op == 'speed_save':
            speed.choose(tid, req.get('mode'))
        return speed.snapshot(tid)
    if op in ('save','clear'):
        if req.get('id') != tid: raise InputError('请先选定会话。')
        if op=='clear' or (not req.get('url') and not req.get('key')):
            store.clear(tid)
        else:
            store.save(tid,req.get('url'),req.get('key'))
    elif op!='read': raise InputError('不支持的操作。')
    record=store.get(tid)
    return {'id':tid,'url':record['url'] if record else '',
            'key':record['key'] if record else ''}


if __name__=='__main__':
    try:
        req=json.loads(sys.stdin.buffer.read(16384)); result=action(Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve(),Bindings(),req)
    except InputError as exc: result={'error':str(exc)}
    except Exception: result={'error':'暂时无法读取会话或 Windows 凭据管理器。'}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=True).encode('ascii'))
