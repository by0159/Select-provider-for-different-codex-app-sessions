"""Per-thread routes in Windows Credential Manager. The default is resolved on every request."""
import ipaddress
import json
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

import ctypes as ct
from ctypes import wintypes as wt

PREFIX = 'ThreadProviderCard/Bindings/v1/'
HEADER_NAMES = ('thread-id', 'thread_id', 'x-codex-thread-id')
SESSION_NAMES = ('session-id', 'session_id', 'x-codex-session-id')


class InputError(ValueError):
    pass


def thread_id(value):
    if not isinstance(value, str):
        raise InputError('请选择会话。')
    try:
        result = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise InputError('会话 ID 无效。') from None
    if result != value.lower():
        raise InputError('请使用完整会话 ID。')
    return result


def route_id(headers):
    for group in (HEADER_NAMES, SESSION_NAMES):
        values = {thread_id(v) for k in group for v in headers.get_all(k, [])}
        if len(values) > 1:
            raise InputError('请求包含冲突的会话 ID。')
        if values:
            return values.pop()
    return None


def address(value):
    if not isinstance(value, str):
        raise InputError('请填写提供方的 API 基础地址。')
    value = value.strip()
    if not value or len(value) > 1200 or any(c.isspace() or ord(c)<32 for c in value) or any(c in value for c in '\\?#'):
        raise InputError('请输入完整的 API 基础地址，不含查询参数。')
    try:
        u = urlsplit(value)
        host, port = u.hostname, u.port
        if not host or u.username is not None or u.password is not None or not value.isascii():
            raise ValueError
    except ValueError:
        raise InputError('地址格式无效。') from None
    try:
        local = ipaddress.ip_address(host.strip('[]')).is_loopback
    except ValueError:
        local = host.lower() == 'localhost'
    if u.scheme != 'https' and not (local and u.scheme == 'http'):
        raise InputError('远程提供方需使用 HTTPS，本机提供方可使用 HTTP。')
    path = u.path.rstrip('/')
    if path.endswith('/responses'):
        path = path[:-len('/responses')]
    return urlunsplit((u.scheme, u.netloc, path or '/v1', '', ''))


# WinCred blobs stay on this Windows account. The public project uses its own namespace.
class Credential(ct.Structure):
    _fields_ = [('Flags', wt.DWORD), ('Type', wt.DWORD), ('TargetName', wt.LPWSTR),
                ('Comment', wt.LPWSTR), ('LastWritten', wt.FILETIME), ('BlobSize', wt.DWORD),
                ('Blob', ct.c_void_p), ('Persist', wt.DWORD), ('AttributeCount', wt.DWORD),
                ('Attributes', ct.c_void_p), ('TargetAlias', wt.LPWSTR), ('UserName', wt.LPWSTR)]


cred = ct.WinDLL('Advapi32', use_last_error=True)
PC = ct.POINTER(Credential)
cred.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.POINTER(PC)]
cred.CredWriteW.argtypes = [PC, wt.DWORD]
cred.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
cred.CredFree.argtypes = [ct.c_void_p]
cred.CredFree.restype = None


class Bindings:
    def __init__(self, prefix=PREFIX):
        self.prefix = prefix

    def get(self, tid):
        entry = PC()
        if not cred.CredReadW(self.prefix + thread_id(tid), 1, 0, ct.byref(entry)):
            if ct.get_last_error() == 1168:
                return None
            raise OSError('Windows Credential Manager read failed')
        try:
            raw = ct.string_at(entry.contents.Blob, entry.contents.BlobSize)
            return json.loads(raw.decode('utf-16-le'))
        finally:
            cred.CredFree(entry)

    def save(self, tid, url, key):
        if not isinstance(key, str) or not re.fullmatch(r'[!-~]+', key):
            raise InputError('请填写有效的 API Key。')
        raw = json.dumps({'url': address(url), 'key': key}, separators=(',', ':')).encode('utf-16-le')
        if len(raw) > 2560:
            raise InputError('地址与 Key 超过 Windows 凭据的长度限制。')
        buf = ct.create_string_buffer(raw)
        entry = Credential(Type=1, TargetName=self.prefix + thread_id(tid), BlobSize=len(raw),
                           Blob=ct.cast(buf,ct.c_void_p), Persist=2)
        if not cred.CredWriteW(ct.byref(entry), 0):
            raise OSError('Windows Credential Manager write failed')

    def clear(self, tid):
        if not cred.CredDeleteW(self.prefix + thread_id(tid), 1, 0) and ct.get_last_error() != 1168:
            raise OSError('Windows Credential Manager delete failed')
