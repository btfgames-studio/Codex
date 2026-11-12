it la playlist YouTube et écrit data/playlist.json (lu par le codex : YouTube → « Synchroniser la playlist »).
Lancé par GitHub Actions (fichier .github/workflows/bg3-playlist.yml), une fois par jour ou à la demande."""
import json, os, re, subprocess, sys, time

url = (os.environ.get("PLAYLIST_URL") or "").strip()
m = re.search(r"[?&]list=([\w-]+)", url)
if not m:
    sys.exit("Lien de playlist invalide : il doit contenir « list=… ». Copie-le depuis YouTube → Partager → Copier le lien.")
pid = m.group(1)
if len(pid) < 18:
    print(f"Attention : l'identifiant de playlist « {pid} » semble coupé (trop court).")

cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json", "--no-warnings", "https://www.youtube.com/playlist?list=" + pid]
for attempt in range(3):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        break
    print("Tentative", attempt + 1, "échouée :", r.stderr.strip()[:300])
    time.sleep(20)
else:
    sys.exit("Impossible de lire la playlist. Vérifie qu'elle est « Publique » ou « Non répertoriée » (pas « Privée »).")

data = json.loads(r.stdout)
videos = []
for i, e in enumerate(data.get("entries") or []):
    vid = e.get("id")
    if not vid or e.get("title") in ("[Private video]", "[Deleted video]"):
        continue
    videos.append({"id": vid, "title": e.get("title") or "", "index": i + 1,
                   "short": "/shorts/" in (e.get("url") or ""), "channel": e.get("channel") or e.get("uploader") or ""})
os.makedirs("data", exist_ok=True)
out = {"date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "playlist": {"id": pid, "title": data.get("title") or ""}, "videos": videos}
json.dump(out, open(os.path.join("data", "playlist.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"Playlist « {out['playlist']['title']} » : {len(videos)} vidéos enregistrées dans data/playlist.json")
