#!/usr/bin/env python3
"""
Indício — Análise de evidências de mensagens
Perícia Computacional — Engenharia da Computação
Somente biblioteca padrão Python.
"""
from __future__ import annotations

import json, mimetypes, os, re, shutil, sqlite3, time, urllib.parse, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CASES_DIR = BASE_DIR.parent / "cases"
DEFAULT_RESOURCES = BASE_DIR.parent / "resources"
ACTIVE_CASE_FILE = CASES_DIR / "active_case.json"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
HOST, PORT = "0.0.0.0", 5000
CORE_DATA_EPOCH = datetime(2001, 1, 1)
MSG_TYPE = {0:"text",1:"image",2:"video",3:"audio",4:"contact",5:"location",6:"system",7:"link",8:"document",10:"system",14:"sticker",15:"deleted"}
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 45.0

CASES_DIR.mkdir(parents=True, exist_ok=True)

def cache_get(key):
    item = _cache.get(key)
    if item and (time.time() - item[0]) < CACHE_TTL:
        return item[1]
    return None
def cache_set(key, value):
    _cache[key] = (time.time(), value)
def cache_clear():
    _cache.clear()

def get_active_resources() -> Path:
    if ACTIVE_CASE_FILE.exists():
        try:
            data = json.loads(ACTIVE_CASE_FILE.read_text())
            p = Path(data.get("path", ""))
            if p.exists() and (p / "ChatStorage_anon.sqlite").exists():
                return p
            # also accept ChatStorage.sqlite without _anon
            if p.exists() and any(p.glob("ChatStorage*.sqlite")):
                return p
        except Exception:
            pass
    if DEFAULT_RESOURCES.exists() and any(DEFAULT_RESOURCES.glob("ChatStorage*.sqlite")):
        return DEFAULT_RESOURCES
    return DEFAULT_RESOURCES

def set_active_case(path: Path, name: str = ""):
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_CASE_FILE.write_text(json.dumps({
        "path": str(path.resolve()),
        "name": name or path.name,
        "activated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))
    cache_clear()

def chat_db_path() -> Path:
    root = get_active_resources()
    for name in ("ChatStorage_anon.sqlite", "ChatStorage.sqlite"):
        p = root / name
        if p.exists():
            return p
    # any ChatStorage*.sqlite
    matches = list(root.glob("ChatStorage*.sqlite"))
    return matches[0] if matches else root / "ChatStorage_anon.sqlite"

def contacts_db_path() -> Path:
    root = get_active_resources()
    for name in ("Contacts_anon.sqlite", "Contacts.sqlite"):
        p = root / name
        if p.exists():
            return p
    matches = list(root.glob("Contacts*.sqlite"))
    return matches[0] if matches else root / "Contacts_anon.sqlite"

def media_dir() -> Path:
    root = get_active_resources()
    # common layouts
    for cand in (root / "Media" / "files", root / "Media", root / "media" / "files", root / "media"):
        if cand.exists():
            return cand
    return root / "Media" / "files"

def get_chat_db():
    conn = sqlite3.connect(str(chat_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_contacts_db():
    path = contacts_db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def core_data_to_datetime(ts):
    if ts is None or ts <= 0:
        return None
    try:
        return CORE_DATA_EPOCH + timedelta(seconds=float(ts))
    except (ValueError, TypeError, OverflowError):
        return None

def format_datetime(dt, with_time=True):
    if dt is None:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M") if with_time else dt.strftime("%d/%m/%Y")

def format_time(dt):
    return dt.strftime("%H:%M") if dt else ""

def format_relative_date(dt):
    if dt is None:
        return ""
    today = datetime.now().date()
    d = dt.date()
    if d == today:
        return "Hoje"
    if d == today - timedelta(days=1):
        return "Ontem"
    return dt.strftime("%d/%m/%Y")

def jid_to_display(jid):
    return jid.split("@")[0].replace("~", "") if jid else ""

def resolve_media_path(local_path):
    if not local_path:
        return None
    basename = os.path.basename(local_path)
    md = media_dir()
    for sub in ("Image", "Audio", "image", "audio", "Images", "Videos"):
        candidate = md / sub / basename
        if candidate.exists():
            return f"/media/{sub}/{basename}"
    # flat search
    if md.exists():
        for f in md.rglob(basename):
            if f.is_file():
                rel = f.relative_to(md)
                return f"/media/{rel.as_posix()}"
    return None

def _human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/(1024*1024):.1f} MB"

_contacts_cache = None
_contacts_case = None

def load_contacts():
    global _contacts_cache, _contacts_case
    case = str(get_active_resources())
    if _contacts_cache is not None and _contacts_case == case:
        return _contacts_cache
    contacts = {}
    try:
        conn = get_contacts_db()
        if conn:
            cur = conn.cursor()
            cur.execute("""SELECT c.ZFULLNAME, c.ZFIRSTNAME, p.ZWHATSAPPID, p.ZPHONE
                FROM ZWACONTACT c LEFT JOIN ZWAPHONE p ON p.ZCONTACT=c.Z_PK""")
            for row in cur.fetchall():
                full = row["ZFULLNAME"] or row["ZFIRSTNAME"] or ""
                for key in (row["ZWHATSAPPID"], row["ZPHONE"]):
                    if key:
                        clean = "".join(c for c in str(key) if c.isdigit())
                        if clean:
                            contacts[clean] = full
                        contacts[str(key)] = full
            conn.close()
    except Exception as e:
        print(f"[warn] Contatos: {e}")
    _contacts_cache = contacts
    _contacts_case = case
    return contacts

def get_contact_name(jid_or_phone, fallback=None):
    contacts = load_contacts()
    if not jid_or_phone:
        return fallback or "Desconhecido"
    raw = str(jid_or_phone).split("@")[0].replace("~", "")
    clean = "".join(c for c in raw if c.isdigit())
    return contacts.get(clean) or contacts.get(raw) or fallback or raw or "Desconhecido"

def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)

def file_response(handler, path: Path, content_type=None, download_name=None):
    if not path.exists() or not path.is_file():
        handler.send_error(404)
        return
    data = path.read_bytes()
    ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    if download_name:
        handler.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
    elif ctype.startswith(("image/", "audio/")):
        handler.send_header("Cache-Control", "public, max-age=3600")
    handler.end_headers()
    handler.wfile.write(data)

def text_response(handler, text, content_type="text/plain; charset=utf-8", download_name=None):
    body = text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    if download_name:
        handler.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
    handler.end_headers()
    handler.wfile.write(body)

def case_ready() -> bool:
    return chat_db_path().exists()

# ---------- Case / Upload ----------
def api_case_status():
    root = get_active_resources()
    ready = case_ready()
    name = root.name
    if ACTIVE_CASE_FILE.exists():
        try:
            name = json.loads(ACTIVE_CASE_FILE.read_text()).get("name") or name
        except Exception:
            pass
    return {
        "ready": ready,
        "name": name if ready else None,
        "path": str(root) if ready else None,
        "has_default": DEFAULT_RESOURCES.exists() and any(DEFAULT_RESOURCES.glob("ChatStorage*.sqlite")),
    }

def _find_case_root(extracted: Path) -> Path:
    """Locate folder containing ChatStorage*.sqlite inside extracted tree."""
    for p in [extracted, *extracted.rglob("*")]:
        if p.is_dir() and any(p.glob("ChatStorage*.sqlite")):
            return p
    return extracted

def handle_upload(handler, body: bytes, content_type: str):
    """Parse multipart ZIP upload and activate as current case."""
    if "multipart/form-data" not in content_type:
        return json_response(handler, {"error": "Envie multipart/form-data com arquivo .zip"}, 400)
    m = re.search(r"boundary=(.+)", content_type)
    if not m:
        return json_response(handler, {"error": "Boundary inválido"}, 400)
    boundary = m.group(1).strip().encode()
    parts = body.split(b"--" + boundary)
    zip_bytes = None
    filename = "caso.zip"
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        if b"filename=" in part:
            fm = re.search(br'filename="([^"]+)"', part)
            if fm:
                filename = fm.group(1).decode("utf-8", errors="ignore")
            idx = part.find(b"\r\n\r\n")
            if idx >= 0:
                zip_bytes = part[idx + 4:]
                if zip_bytes.endswith(b"\r\n"):
                    zip_bytes = zip_bytes[:-2]
                break
    if not zip_bytes:
        return json_response(handler, {"error": "Arquivo não encontrado no upload"}, 400)
    if not filename.lower().endswith(".zip"):
        return json_response(handler, {"error": "Envie um arquivo .zip contendo o caso"}, 400)

    case_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_path = CASES_DIR / case_id
    case_path.mkdir(parents=True, exist_ok=True)
    zip_path = case_path / "upload.zip"
    zip_path.write_bytes(zip_bytes)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(case_path / "extracted")
    except zipfile.BadZipFile:
        shutil.rmtree(case_path, ignore_errors=True)
        return json_response(handler, {"error": "ZIP inválido ou corrompido"}, 400)

    root = _find_case_root(case_path / "extracted")
    if not any(root.glob("ChatStorage*.sqlite")):
        shutil.rmtree(case_path, ignore_errors=True)
        return json_response(handler, {"error": "ZIP não contém ChatStorage*.sqlite"}, 400)

    set_active_case(root, name=filename.replace(".zip", ""))
    global _contacts_cache, _contacts_case
    _contacts_cache = None
    _contacts_case = None
    return json_response(handler, {
        "ok": True,
        "name": filename.replace(".zip", ""),
        "message": "Caso carregado com sucesso. Os dados anteriores foram substituídos.",
    })

def activate_default():
    if DEFAULT_RESOURCES.exists():
        set_active_case(DEFAULT_RESOURCES, name="caso_padrao")
        return True
    return False


def _preview_from_msg(msg_type, text):
    """Preview text for chat list (like messenger last line)."""
    t = (text or "").strip()
    if t:
        return t[:120]
    labels = {1: "Imagem", 2: "Vídeo", 3: "Áudio", 4: "Contato", 5: "Localização",
              6: "Evento", 7: "Link", 8: "Documento", 10: "Sistema", 14: "Figurinha"}
    return labels.get(msg_type, "Mídia" if msg_type else "")

def api_chats(query):
    if not case_ready():
        return {"chats": [], "total": 0, "error": "Nenhum caso carregado"}
    key = "chats_all"
    cached = cache_get(key)
    if cached is None:
        conn = get_chat_db(); cur = conn.cursor()
        cur.execute("""SELECT cs.Z_PK AS id, cs.ZPARTNERNAME AS name, cs.ZCONTACTJID AS jid,
            cs.ZSESSIONTYPE AS session_type, cs.ZMESSAGECOUNTER AS message_count,
            cs.ZLASTMESSAGETEXT AS last_text, cs.ZLASTMESSAGEDATE AS last_date,
            cs.ZUNREADCOUNT AS unread, cs.ZLASTMESSAGE AS last_msg_id,
            lm.ZTEXT AS lm_text, lm.ZMESSAGETYPE AS lm_type, lm.ZISFROMME AS lm_from_me
            FROM ZWACHATSESSION cs
            LEFT JOIN ZWAMESSAGE lm ON cs.ZLASTMESSAGE = lm.Z_PK
            WHERE cs.ZHIDDEN=0 OR cs.ZHIDDEN IS NULL
            ORDER BY cs.ZLASTMESSAGEDATE DESC""")
        rows = cur.fetchall(); conn.close()
        chats = []
        for r in rows:
            name = r["name"] or get_contact_name(r["jid"]) or jid_to_display(r["jid"])
            last_dt = core_data_to_datetime(r["last_date"])
            preview = _preview_from_msg(r["lm_type"], r["lm_text"] or r["last_text"])
            prefix = "Você: " if r["lm_from_me"] else ""
            if preview and r["lm_from_me"]:
                preview = prefix + preview
            chats.append({"id": r["id"], "name": name, "jid": r["jid"],
                "is_group": r["session_type"] == 1,
                "message_count": r["message_count"] or 0,
                "last_text": preview,
                "last_type": MSG_TYPE.get(r["lm_type"] if r["lm_type"] is not None else -1, ""),
                "last_date": format_datetime(last_dt) if last_dt else "",
                "last_date_short": format_relative_date(last_dt) if last_dt else "",
                "unread": r["unread"] or 0})
        cache_set(key, chats); cached = chats
    q = (query.get("q") or [""])[0].strip().lower()
    if q:
        cached = [c for c in cached if q in (c["name"] or "").lower() or q in (c["jid"] or "").lower()]
    return {"chats": cached, "total": len(cached)}

def api_chat_info(chat_id):
    conn = get_chat_db(); cur = conn.cursor()
    cur.execute("""SELECT Z_PK AS id, ZPARTNERNAME AS name, ZCONTACTJID AS jid,
        ZSESSIONTYPE AS session_type, ZMESSAGECOUNTER AS message_count
        FROM ZWACHATSESSION WHERE Z_PK=?""", (chat_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); return None
    name = row["name"] or get_contact_name(row["jid"]) or jid_to_display(row["jid"])
    is_group = row["session_type"] == 1
    members = []
    if is_group:
        cur.execute("""SELECT ZCONTACTNAME,ZFIRSTNAME,ZMEMBERJID,ZISADMIN,ZISACTIVE
            FROM ZWAGROUPMEMBER WHERE ZCHATSESSION=? ORDER BY ZCONTACTNAME""", (chat_id,))
        for m in cur.fetchall():
            members.append({"name": m["ZCONTACTNAME"] or m["ZFIRSTNAME"] or get_contact_name(m["ZMEMBERJID"]),
                "jid": m["ZMEMBERJID"], "is_admin": bool(m["ZISADMIN"]), "is_active": bool(m["ZISACTIVE"])})
    conn.close()
    return {"id": row["id"], "name": name, "jid": row["jid"], "is_group": is_group,
            "message_count": row["message_count"] or 0, "members": members}

def _fetch_messages(chat_id, limit, offset, search="", around_id=None):
    conn = get_chat_db(); cur = conn.cursor()
    if search:
        cur.execute("SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND ZTEXT LIKE ?",
                    (chat_id, f"%{search}%"))
    else:
        cur.execute("SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZCHATSESSION=?", (chat_id,))
    total = cur.fetchone()[0]
    sql = """SELECT m.Z_PK AS id, m.ZISFROMME AS is_from_me, m.ZMESSAGETYPE AS msg_type,
        m.ZTEXT AS text, m.ZMESSAGEDATE AS msg_date, m.ZFROMJID AS from_jid, m.ZPUSHNAME AS push_name,
        m.ZSTARRED AS starred, m.ZMESSAGESTATUS AS status,
        gm.ZCONTACTNAME AS member_name, gm.ZFIRSTNAME AS member_first,
        mi.ZMEDIALOCALPATH AS media_path, mi.ZTHUMBNAILLOCALPATH AS thumb_path,
        mi.ZFILESIZE AS file_size, mi.ZMOVIEDURATION AS duration, mi.ZTITLE AS media_title,
        mi.ZLATITUDE AS latitude, mi.ZLONGITUDE AS longitude, mi.ZVCARDNAME AS vcard_name
        FROM ZWAMESSAGE m
        LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER=gm.Z_PK
        LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM=mi.Z_PK
        WHERE m.ZCHATSESSION=?"""
    params = [chat_id]
    if search:
        sql += " AND m.ZTEXT LIKE ?"; params.append(f"%{search}%")
    sql += " ORDER BY m.ZMESSAGEDATE DESC, m.Z_PK DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(sql, params); rows = cur.fetchall(); conn.close()
    messages = []
    for r in rows:
        dt = core_data_to_datetime(r["msg_date"])
        msg_type = MSG_TYPE.get(r["msg_type"], f"unknown_{r['msg_type']}")
        media_url = resolve_media_path(r["media_path"])
        sender_name = None
        if not r["is_from_me"]:
            sender_name = r["member_name"] or r["member_first"] or r["push_name"] or get_contact_name(r["from_jid"])
        messages.append({
            "id": r["id"], "is_from_me": bool(r["is_from_me"]), "type": msg_type, "type_raw": r["msg_type"],
            "text": r["text"] or "", "date": format_datetime(dt) if dt else "", "time": format_time(dt) if dt else "",
            "date_iso": dt.isoformat() if dt else None, "date_separator": format_relative_date(dt) if dt else "",
            "sender": sender_name, "starred": bool(r["starred"]), "status": r["status"],
            "media_url": media_url,
            "download_url": media_url.replace("/media/", "/download/") if media_url else None,
            "thumb_url": resolve_media_path(r["thumb_path"]) if r["thumb_path"] else None,
            "file_size": r["file_size"], "duration": r["duration"], "media_title": r["media_title"],
            "latitude": r["latitude"], "longitude": r["longitude"], "vcard_name": r["vcard_name"],
        })
    messages.reverse()
    return messages, total

def api_messages(chat_id, query):
    limit = min(int((query.get("limit") or ["100"])[0]), 500)
    offset = int((query.get("offset") or ["0"])[0])
    search = (query.get("q") or [""])[0].strip()
    focus = query.get("focus") and query.get("focus")[0]
    # If focus message id provided, load a window around it
    if focus:
        try:
            fid = int(focus)
            conn = get_chat_db(); cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND (ZMESSAGEDATE > (SELECT ZMESSAGEDATE FROM ZWAMESSAGE WHERE Z_PK=?) OR (ZMESSAGEDATE=(SELECT ZMESSAGEDATE FROM ZWAMESSAGE WHERE Z_PK=?) AND Z_PK>?))",
                        (chat_id, fid, fid, fid))
            # Simpler: get sort position
            cur.execute("""SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND Z_PK >= ?""", (chat_id, fid))
            # Load more messages from start including focus - load larger batch
            conn.close()
            messages, total = _fetch_messages(chat_id, min(limit * 5, 500), 0, search)
            return {"messages": messages, "total": total, "limit": limit, "offset": 0,
                    "has_more": total > len(messages), "focus_id": fid}
        except Exception:
            pass
    messages, total = _fetch_messages(chat_id, limit, offset, search)
    return {"messages": messages, "total": total, "limit": limit, "offset": offset,
            "has_more": (offset + limit) < total}

def api_export_txt(chat_id):
    info = api_chat_info(chat_id)
    if not info:
        return ""
    messages, _ = _fetch_messages(chat_id, 100000, 0)
    lines = [f"Conversa: {info['name']}", f"ID: {info['jid']}",
             f"Tipo: {'Grupo' if info['is_group'] else 'Individual'}",
             f"Mensagens: {info['message_count']}",
             f"Exportado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", "=" * 60, ""]
    for m in messages:
        who = "Eu" if m["is_from_me"] else (m["sender"] or "Contato")
        prefix = f"[{m['date']}] {who}: "
        if m["text"]:
            lines.append(prefix + m["text"])
        elif m["media_url"]:
            lines.append(prefix + f"[{m['type'].upper()}]")
        else:
            lines.append(prefix + f"[{m['type'].upper()}]")
    return "\n".join(lines)

def api_export_html(chat_id):
    info = api_chat_info(chat_id)
    if not info:
        return ""
    messages, _ = _fetch_messages(chat_id, 100000, 0)
    rows = []
    for m in messages:
        who = "Eu" if m["is_from_me"] else (m["sender"] or "Contato")
        cls = "me" if m["is_from_me"] else "them"
        content = ""
        if m["media_url"] and m["type"] in ("image", "video"):
            content += f'<img src="{m["media_url"]}" style="max-width:280px;border-radius:6px"/><br/>'
        if m["media_url"] and m["type"] == "audio":
            content += f'<audio controls src="{m["media_url"]}"></audio><br/>'
        if m["text"]:
            content += m["text"].replace("<", "&lt;").replace(">", "&gt;")
        if not content:
            content = f'<em>[{m["type"]}]</em>'
        rows.append(f'<div class="msg {cls}"><div class="meta">{who} · {m["date"]}</div><div class="body">{content}</div></div>')
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"/><title>{info['name']}</title>
<style>body{{font-family:system-ui;background:#12141a;color:#e8eaed;padding:20px;max-width:800px;margin:0 auto}}
.msg{{margin:8px 0;padding:8px 12px;border-radius:8px;max-width:75%}}
.me{{background:#1e3a5f;margin-left:auto}}.them{{background:#252830}}.meta{{font-size:11px;opacity:.7}}</style></head>
<body><h1>{info['name']}</h1><p>{info['message_count']} mensagens</p>{''.join(rows)}</body></html>"""


def api_stats():
    if not case_ready():
        return {"error": "Nenhum caso"}
    cached = cache_get("stats")
    if cached:
        return cached
    conn = get_chat_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ZWACHATSESSION"); chats = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ZWAMESSAGE"); messages = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ZWAMEDIAITEM"); media = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ZWACHATSESSION WHERE ZSESSIONTYPE=1"); groups = cur.fetchone()[0]
    cur.execute("SELECT MIN(ZMESSAGEDATE),MAX(ZMESSAGEDATE) FROM ZWAMESSAGE WHERE ZMESSAGEDATE>100000")
    mn, mx = cur.fetchone()
    cur.execute("SELECT ZMESSAGETYPE,COUNT(*) FROM ZWAMESSAGE GROUP BY ZMESSAGETYPE ORDER BY COUNT(*) DESC")
    by_type = {MSG_TYPE.get(t, str(t)): c for t, c in cur.fetchall()}
    conn.close()
    md = media_dir()
    local_media = sum(1 for _ in md.rglob("*") if _.is_file()) if md.exists() else 0
    result = {"chats": chats, "messages": messages, "media_items": media, "groups": groups,
              "date_from": format_datetime(core_data_to_datetime(mn), False),
              "date_to": format_datetime(core_data_to_datetime(mx), False),
              "local_media_files": local_media, "by_type": by_type}
    cache_set("stats", result)
    return result

def _msg_dates(chat_id=None):
    conn = get_chat_db(); cur = conn.cursor()
    if chat_id:
        cur.execute("SELECT ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND ZMESSAGEDATE>100000", (chat_id,))
    else:
        cur.execute("SELECT ZMESSAGEDATE FROM ZWAMESSAGE WHERE ZMESSAGEDATE>100000")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def api_timeline(query):
    chat_id = query.get("chat_id") and int(query.get("chat_id")[0])
    key = f"timeline_{chat_id or 'all'}"
    cached = cache_get(key)
    if cached:
        return cached
    by_day = defaultdict(int)
    for ts in _msg_dates(chat_id):
        dt = core_data_to_datetime(ts)
        if dt:
            by_day[dt.strftime("%Y-%m-%d")] += 1
    days = sorted(by_day.keys())
    result = {"labels": days, "counts": [by_day[d] for d in days], "total_days": len(days),
              "chat_id": chat_id}
    cache_set(key, result)
    return result

def api_hourly(query):
    chat_id = query.get("chat_id") and int(query.get("chat_id")[0])
    key = f"hourly_{chat_id or 'all'}"
    cached = cache_get(key)
    if cached:
        return cached
    hours = [0] * 24
    focus_ids = [None] * 24  # most recent message id at each hour
    if chat_id:
        conn = get_chat_db(); cur = conn.cursor()
        cur.execute("""SELECT Z_PK, ZMESSAGEDATE FROM ZWAMESSAGE
            WHERE ZCHATSESSION=? AND ZMESSAGEDATE>100000 ORDER BY ZMESSAGEDATE DESC""", (chat_id,))
        for pk, ts in cur.fetchall():
            dt = core_data_to_datetime(ts)
            if not dt:
                continue
            h = dt.hour
            hours[h] += 1
            if focus_ids[h] is None:
                focus_ids[h] = pk
        conn.close()
    else:
        for ts in _msg_dates(None):
            dt = core_data_to_datetime(ts)
            if dt:
                hours[dt.hour] += 1
    result = {
        "labels": [f"{h:02d}h" for h in range(24)],
        "counts": hours,
        "focus_ids": focus_ids,
        "chat_id": chat_id,
    }
    cache_set(key, result)
    return result

def api_wordcloud(query):
    limit = min(int((query.get("limit") or ["80"])[0]), 200)
    chat_id = query.get("chat_id") and int(query.get("chat_id")[0])
    key = f"words_{chat_id or 'all'}_{limit}"
    cached = cache_get(key)
    if cached:
        return cached
    stopwords = set("a o e de da do que em um uma para com não nao os as se na no por mais ao é eu você voce ele ela isso mas foi ser tem tá ta pra pro já ja só so me te the and to of in is it you that was for on are with as i at be this have from or one had by but not what all were we when your can said there an each which she do how their if will up other about out many then them these so some her would make like him into time has look two more go see no way could my than first been call who its now find long down day did get come made may part oi ok kk kkk rsrs haha hehe sim vai vou aqui também tambem muito bem ainda porque pq né ne".split())
    conn = get_chat_db(); cur = conn.cursor()
    if chat_id:
        cur.execute("SELECT ZTEXT FROM ZWAMESSAGE WHERE ZCHATSESSION=? AND ZTEXT IS NOT NULL AND ZTEXT!=''", (chat_id,))
    else:
        cur.execute("SELECT ZTEXT FROM ZWAMESSAGE WHERE ZTEXT IS NOT NULL AND ZTEXT!=''")
    counter = Counter()
    for (text,) in cur.fetchall():
        for w in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text.lower()):
            if w not in stopwords:
                counter[w] += 1
    conn.close()
    top = counter.most_common(limit)
    result = {"words": [{"text": w, "count": c} for w, c in top], "chat_id": chat_id}
    cache_set(key, result)
    return result

def api_all_contacts(query):
    """All chats sorted by message count — for analysis contact picker."""
    q = (query.get("q") or [""])[0].strip().lower()
    data = api_chats({})
    chats = sorted(data["chats"], key=lambda c: c["message_count"], reverse=True)
    if q:
        chats = [c for c in chats if q in (c["name"] or "").lower()]
    return {"contacts": chats, "total": len(chats)}

def api_media_gallery(query):
    kind = (query.get("type") or ["all"])[0]
    q = (query.get("q") or [""])[0].strip().lower()
    limit = min(int((query.get("limit") or ["120"])[0]), 400)
    offset = int((query.get("offset") or ["0"])[0])
    md = media_dir()
    files = []
    if md.exists():
        for sub in ("Image", "Audio", "image", "audio", "Images"):
            folder = md / sub
            if not folder.exists():
                continue
            cat = "image" if sub.lower().startswith("image") else "audio"
            if kind != "all" and kind != cat:
                continue
            for f in folder.iterdir():
                if not f.is_file():
                    continue
                files.append({
                    "name": f.name, "category": cat,
                    "url": f"/media/{sub}/{f.name}",
                    "download_url": f"/download/{sub}/{f.name}",
                    "size": f.stat().st_size, "size_human": _human_size(f.stat().st_size),
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "ext": f.suffix.lower(),
                })
    # Enrich from DB with chat_id + message_id for locate
    if case_ready():
        conn = get_chat_db(); cur = conn.cursor()
        cur.execute("""SELECT mi.ZMEDIALOCALPATH, mi.ZFILESIZE, mi.ZMOVIEDURATION,
            m.Z_PK AS msg_id, m.ZMESSAGEDATE, m.ZCHATSESSION AS chat_id,
            cs.ZPARTNERNAME, cs.ZCONTACTJID
            FROM ZWAMEDIAITEM mi
            LEFT JOIN ZWAMESSAGE m ON mi.ZMESSAGE = m.Z_PK
            LEFT JOIN ZWACHATSESSION cs ON m.ZCHATSESSION = cs.Z_PK
            WHERE mi.ZMEDIALOCALPATH IS NOT NULL""")
        db_map = {}
        for r in cur.fetchall():
            bn = os.path.basename(r["ZMEDIALOCALPATH"] or "")
            if not bn:
                continue
            dt = core_data_to_datetime(r["ZMESSAGEDATE"])
            db_map[bn] = {
                "db_size": r["ZFILESIZE"], "duration": r["ZMOVIEDURATION"],
                "msg_date": format_datetime(dt) if dt else None,
                "chat_name": r["ZPARTNERNAME"] or get_contact_name(r["ZCONTACTJID"]) or "",
                "chat_id": r["chat_id"], "message_id": r["msg_id"],
            }
        conn.close()
        for f in files:
            f.update(db_map.get(f["name"], {}))
    # Filter by chat name (not filename)
    if q:
        files = [f for f in files if q in (f.get("chat_name") or "").lower()]
    files.sort(key=lambda x: x.get("msg_date") or x["mtime"] or "", reverse=True)
    total = len(files)
    page = files[offset: offset + limit]
    return {"items": page, "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total}

def api_global_search(query):
    q = (query.get("q") or [""])[0].strip()
    if not q or len(q) < 2:
        return {"results": [], "total": 0}
    limit = min(int((query.get("limit") or ["50"])[0]), 200)
    conn = get_chat_db(); cur = conn.cursor()
    cur.execute("""SELECT m.Z_PK AS id, m.ZTEXT AS text, m.ZMESSAGEDATE AS msg_date,
        m.ZISFROMME AS is_from_me, m.ZCHATSESSION AS chat_id,
        cs.ZPARTNERNAME AS chat_name, cs.ZCONTACTJID AS jid, m.ZMESSAGETYPE AS msg_type
        FROM ZWAMESSAGE m JOIN ZWACHATSESSION cs ON m.ZCHATSESSION=cs.Z_PK
        WHERE m.ZTEXT LIKE ? ORDER BY m.ZMESSAGEDATE DESC LIMIT ?""", (f"%{q}%", limit))
    results = []
    for r in cur.fetchall():
        dt = core_data_to_datetime(r["msg_date"])
        name = r["chat_name"] or get_contact_name(r["jid"]) or jid_to_display(r["jid"])
        results.append({"id": r["id"], "text": r["text"] or "", "date": format_datetime(dt) if dt else "",
            "chat_id": r["chat_id"], "chat_name": name, "is_from_me": bool(r["is_from_me"]),
            "type": MSG_TYPE.get(r["msg_type"], "text")})
    conn.close()
    return {"results": results, "total": len(results)}


class Handler(BaseHTTPRequestHandler):
    server_version = "Indicio/1.0"
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/case/upload":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            return handle_upload(self, body, self.headers.get("Content-Type", ""))
        if parsed.path == "/api/case/activate-default":
            ok = activate_default()
            return json_response(self, {"ok": ok, "status": api_case_status()})
        self.send_error(404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/case/status":
                return json_response(self, api_case_status())
            if path == "/api/chats":
                return json_response(self, api_chats(query))
            if path == "/api/stats":
                return json_response(self, api_stats())
            if path == "/api/search":
                return json_response(self, api_global_search(query))
            if path == "/api/timeline":
                return json_response(self, api_timeline(query))
            if path == "/api/hourly":
                return json_response(self, api_hourly(query))
            if path == "/api/words":
                return json_response(self, api_wordcloud(query))
            if path == "/api/contacts":
                return json_response(self, api_all_contacts(query))
            if path == "/api/media":
                return json_response(self, api_media_gallery(query))

            m = re.match(r"^/api/chat/(\d+)$", path)
            if m:
                data = api_chat_info(int(m.group(1)))
                if data is None:
                    return self.send_error(404)
                return json_response(self, data)
            m = re.match(r"^/api/messages/(\d+)$", path)
            if m:
                return json_response(self, api_messages(int(m.group(1)), query))
            m = re.match(r"^/api/export/(\d+)/(txt|html)$", path)
            if m:
                cid, fmt = int(m.group(1)), m.group(2)
                info = api_chat_info(cid)
                safe = re.sub(r"[^\w\-]+", "_", (info or {}).get("name") or str(cid))[:40]
                if fmt == "txt":
                    return text_response(self, api_export_txt(cid), download_name=f"conversa_{safe}.txt")
                return text_response(self, api_export_html(cid),
                    content_type="text/html; charset=utf-8", download_name=f"conversa_{safe}.html")

            m = re.match(r"^/(media|download)/(.+)$", path)
            if m:
                mode, rest = m.group(1), urllib.parse.unquote(m.group(2))
                if ".." in rest:
                    return self.send_error(400)
                fpath = media_dir() / rest
                if mode == "download":
                    return file_response(self, fpath, download_name=os.path.basename(rest))
                return file_response(self, fpath)

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                if ".." in rel:
                    return self.send_error(400)
                return file_response(self, STATIC_DIR / rel)
            if path in ("/", "/index.html"):
                return file_response(self, TEMPLATES_DIR / "index.html", "text/html; charset=utf-8")
            self.send_error(404)
        except Exception as e:
            print(f"[error] {e}")
            try:
                json_response(self, {"error": str(e)}, status=500)
            except Exception:
                pass

def main():
    print("=" * 58)
    print("  Indício — Análise de evidências de mensagens")
    print("  Perícia Computacional")
    print("=" * 58)
    st = api_case_status()
    print(f"  Caso ativo: {st.get('name') or '(nenhum)'}")
    print(f"  Pronto: {st['ready']}")
    print(f"  Acesse: http://127.0.0.1:{PORT}")
    print("=" * 58)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
        server.shutdown()

if __name__ == "__main__":
    main()
