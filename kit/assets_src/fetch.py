"""Re-download the music and sound-effect library from kit/music/library.json and kit/sfx/library.json
(the audio files are not in git). Tracks copied from the owner's Downloads have no URL and must be copied by hand.

    python3 kit/assets_src/fetch.py
"""
import json, re, subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"


def curl(url, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-s", "-m", "180", "-L", "-A", UA, "-o", str(out), url], check=True)


def main():
    for t in json.load(open(KIT / "music/library.json")) + json.load(open(KIT / "sfx/library.json")):
        out = KIT / t["file"]
        url = t.get("url")
        if out.exists() or not url:
            continue
        if url.startswith("ncs-instrumental:"):
            page = subprocess.run(["curl", "-s", "-L", "-A", UA, "https://ncs.io/" + url.split(":", 1)[1]], capture_output=True, text=True).stdout
            url = "https://ncs.io" + re.search(r'href="(/track/download/i_[0-9a-f-]+)"', page).group(1)
        if out.suffix == ".wav" and url.endswith(".wav"):
            curl(url, out)
            if out.stat().st_size < 1000:                                   # a few Mixkit sounds only exist as MP3
                curl(url[:-4] + ".mp3", out.with_suffix(".mp3"))
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out.with_suffix(".mp3")), str(out)], check=True)
                out.with_suffix(".mp3").unlink()
        else:
            curl(url, out)
        print("fetched", t["file"])


if __name__ == "__main__":
    main()
