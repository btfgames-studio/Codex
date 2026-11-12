# Robot Playlist BG3 : lit la playlist YouTube et ecrit data/playlist.json
# (lu par le codex : onglet YouTube, bouton Synchroniser la playlist).
# Lance par GitHub Actions (.github/workflows/bg3-playlist.yml), une fois par jour ou a la demande.
# Methode 1 : page de la playlist. Methode 2 : flux RSS (15 dernieres). Methode 3 : yt-dlp.
import html, json, os, re, subprocess, sys, time
import requests

url = (os.environ.get("PLAYLIST_URL") or "").strip()
m = re.search(r"[?&]list=([\w-]+)", url) or re.fullmatch(r"\s*([\w-]{10,})\s*", url)
if not m:
    sys.exit("Lien de playlist invalide : il doit contenir list=...")
pid = m.group(1)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}

def walk(o, found):
    if isinstance(o, dict):
        r = o.get("playlistVideoRenderer")
        if isinstance(r, dict) and r.get("videoId"):
            t = r.get("title") or {}
            title = (t.get("runs") or [{}])[0].get("text") or t.get("simpleText") or ""
            found.append({"id": r["videoId"], "title": title})
        for v in o.values():
            walk(v, found)
    elif isinstance(o, list):
        for v in o:
            walk(v, found)

def from_page():
    r = requests.get("https://www.youtube.com/playlist", params={"list": pid, "hl": "fr"}, headers=H, cookies=COOKIES, timeout=60)
    r.raise_for_status()
    mm = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", r.text, re.S) or re.search(r"ytInitialData\"\]\s*=\s*(\{.*?\});", r.text, re.S)
    title = ""
    found = []
    if mm:
        data = json.loads(mm.group(1))
        walk(data, found)
        try:
            title = data["metadata"]["playlistMetadataRenderer"]["title"]
        except Exception:
            pass
    if not found:
        ids = []
        for v in re.findall(r'"videoId":"([\w-]{11})"', r.text):
            if v not in ids:
                ids.append(v)
        found = [{"id": v, "title": ""} for v in ids]
    return title, found

def from_rss():
    r = requests.get("https://www.youtube.com/feeds/videos.xml", params={"playlist_id": pid}, headers=H, timeout=60)
    r.raise_for_status()
    title = html.unescape((re.search(r"<title>(.*?)</title>", r.text) or [None, ""])[1])
    found = []
    for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        vid = re.search(r"<yt:videoId>([\w-]{11})</yt:videoId>", entry)
        t = re.search(r"<title>(.*?)</title>", entry, re.S)
        if vid:
            found.append({"id": vid.group(1), "title": html.unescape(t.group(1)) if t else ""})
    return title, found

def from_ytdlp():
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-single-json", "--no-warnings", "https://www.youtube.com/playlist?list=" + pid], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    data = json.loads(r.stdout)
    return data.get("title") or "", [{"id": e["id"], "title": e.get("title") or ""} for e in (data.get("entries") or []) if e.get("id")]

title, videos, used = "", [], ""
for name, fn in (("page de la playlist", from_page), ("flux RSS", from_rss), ("yt-dlp", from_ytdlp)):
    try:
        t, v = fn()
        print(f"{name} : {len(v)} videos trouvees")
        if len(v) > len(videos):
            title, videos, used = t or title, v, name
        if name == "page de la playlist" and v:
            break
    except Exception as e:
        print(f"{name} : echec ({e})")
if not videos:
    sys.exit("Impossible de lire la playlist par aucune des trois methodes.")

videos = [dict(v, index=i + 1) for i, v in enumerate(videos) if v["title"] not in ("[Private video]", "[Deleted video]", "Vidéo privée", "Vidéo supprimée")]
os.makedirs("data", exist_ok=True)
old = {}
if os.path.exists("data/playlist.json"):
    try:
        old = {v["id"]: v for v in json.load(open("data/playlist.json", encoding="utf-8")).get("videos", [])}
    except Exception:
        old = {}
for v in videos:
    if not v["title"] and v["id"] in old:
        v["title"] = old[v["id"]].get("title", "")
out = {"date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "playlist": {"id": pid, "title": title}, "source": used, "videos": videos}
json.dump(out, open("data/playlist.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"Playlist {title!r} : {len(videos)} videos enregistrees (methode : {used})")
