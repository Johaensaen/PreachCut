#!/usr/bin/env python3
import json, os, re, shutil, subprocess, sys, threading, traceback, venv, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
VENV, WORK, OUT = BASE / ".venv", BASE / "work", BASE / "output"
LANG_DIR = BASE / "languages"
PORT = 8766
JOBS, FF = {}, "ffmpeg"

def get_available_languages():
    langs = []
    if LANG_DIR.exists():
        for f in LANG_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as lf:
                    data = json.load(lf)
                    langs.append({
                        "code": data.get("language_code", f.stem),
                        "name": data.get("name", f.stem.upper()),
                        "file": f.name
                    })
            except Exception:
                pass
    if not langs:
        langs.append({"code": "de", "name": "Deutsch", "file": "de.json"})
    return langs

def load_language_config(lang_code):
    lang_file = LANG_DIR / f"{lang_code}.json"
    if not lang_file.exists():
        lang_file = LANG_DIR / "de.json"
    if lang_file.exists():
        with open(lang_file, "r", encoding="utf-8") as lf:
            return json.load(lf)
    return {
        "language_code": "de",
        "whisper_language": "de",
        "hint": "Predigt mit Bibelstellen: 1. Mose 1, Psalm 23, Jesaja 53, Matthäus 5, Johannes 3,16, Römer 8,28, Offenbarung.",
        "single_books": {}, "numbered_books": {}, "ordinals": {}, "units": {}, "tens": {}
    }

def find_refs(words, lang_config):
    single = lang_config.get("single_books", {})
    numbered = lang_config.get("numbered_books", {})
    ord_words = lang_config.get("ordinals", {})
    units = lang_config.get("units", {})
    tens = lang_config.get("tens", {})

    toks = [(m.group().lower(), t, wi) for wi, (t, w) in enumerate(words) for m in re.finditer(r"\d+|[^\W\d_]+|[,:–-]", w)]
    found, i = [], 0
    while i < len(toks):
        w, t, wi = toks[i]
        book, j = None, i + 1
        
        # Match single or numbered books
        if w in single:
            book = single[w]
        if not book:
            i += 1
            continue
            
        text = " ".join(x for _, x in words[max(wi-5,0):wi+14])
        if not (found and found[-1]["ref"] == book and t - found[-1]["t"] < 90):
            found.append({"t": round(max(t-1, 0), 1), "ref": book, "text": text})
        i = max(j, i+1)
    return found

def probe(f):
    t = subprocess.run([FF, "-i", str(f)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", t)
    return (int(m[1])*3600 + int(m[2])*60 + float(m[3]) if m else 5)

def run_ffmpeg_with_logging(cmd, job, desc, start_pct, end_pct, total_duration=None):
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    print(f"\n--- [AUSFÜHRUNG] {desc} ---")
    job["msg"] = desc
    job["pct"] = start_pct
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    for line in process.stdout:
        if job.get("state") == "cancelled":
            process.terminate()
            raise InterruptedError("Abgebrochen")
        stripped = line.strip()
        if stripped:
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", stripped)
            if m and total_duration and total_duration > 0:
                cur_sec = int(m[1])*3600 + int(m[2])*60 + float(m[3])
                ratio = min(1.0, cur_sec / total_duration)
                job["pct"] = start_pct + int((end_pct - start_pct) * ratio)

    ret = process.wait()
    if job.get("state") == "cancelled":
        raise InterruptedError("Abgebrochen")
    if ret != 0:
        raise RuntimeError(f"{desc} fehlgeschlagen mit Code {ret}")
    job["pct"] = end_pct

def analyze(p):
    job, d = JOBS[p["jid"]], WORK / p["sid"]
    lang_code = p.get("language", "de")
    lang_config = load_language_config(lang_code)
    whisper_lang = lang_config.get("whisper_language", lang_code)
    hint = lang_config.get("hint", "")

    try:
        words_file = d / "words.json"
        if words_file.exists() and not p.get("force_retranscribe", False):
            job["msg"] = "Lade vorherige Transkription..."
            job["pct"] = 50
            with open(words_file, "r", encoding="utf-8") as wf:
                all_word_objs = json.load(wf)
            words = [(w["start"], w["word"]) for w in all_word_objs]
            job.update(state="done", pct=100, msg="Fertig!", refs=find_refs(words, lang_config))
            return

        from faster_whisper import WhisperModel
        job["msg"] = f"Lade KI-Modell (Sprache: {lang_code.upper()})..."
        try:
            model = WhisperModel("base", device="cuda", compute_type="float16")
        except Exception:
            try:
                model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
            except Exception:
                model = WhisperModel("base", device="cpu", compute_type="int8")

        if job.get("state") == "cancelled": return

        user_prompt = p.get("prompt", "").strip()
        full_prompt = f"{user_prompt}. {hint}" if user_prompt else hint

        video_path = next(d.glob("video.*"))
        segs, info = model.transcribe(str(video_path), language=whisper_lang, vad_filter=True, word_timestamps=True, initial_prompt=full_prompt)
        
        words = []
        all_word_objs = []
        for sg in segs:
            if job.get("state") == "cancelled": return
            for w in (sg.words or []):
                w_text = w.word.strip()
                words.append((w.start, w_text))
                all_word_objs.append({"start": w.start, "end": w.end, "word": w_text})
            job["pct"] = min(99, round(100 * sg.end / max(info.duration, 1)))
            job["msg"] = f"Erkenne Bibelstellen... {int(sg.end // 60)} / {int(info.duration // 60)} Min."
            
        with open(words_file, "w", encoding="utf-8") as wf:
            json.dump(all_word_objs, wf, ensure_ascii=False)

        job.update(state="done", pct=100, msg="Fertig.", refs=find_refs(words, lang_config))
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))

def process(p):
    sid, job, d = p["sid"], JOBS[p["jid"]], WORK / p["sid"]
    try:
        src = next(d.glob("video.*"))
        total_dur = probe(src)
        out_main = OUT / "Sermon_Longversion_16x9.mp4"
        out_short = OUT / "Sermon_Highlight_Short_9x16.mp4"

        intro_file = list(d.glob("intro.*"))
        outro_file = list(d.glob("outro.*"))
        has_intro, has_outro = len(intro_file) > 0, len(outro_file) > 0

        job["msg"] = "Starte Videoschnitt..."
        job["pct"] = 5

        items = p.get("items", [])
        slides = []
        for i in items:
            if i.get("file"):
                fpath = d / i["file"]
                if fpath.exists():
                    slides.append((fpath, max(float(i["t"]), 0), min(float(i["t"]) + float(i["d"]), total_dur), i.get("side", "right")))

        fit_full = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        fit_half = "scale=960:1080:force_original_aspect_ratio=decrease,pad=960:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        enc_fast = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]

        predigt_temp = d / "temp_predigt.mp4"

        if slides:
            cmd = [FF, "-y", "-hide_banner", "-i", str(src)]
            for f, _, _, _ in slides: cmd += ["-loop", "1", "-framerate", "25", "-t", f"{total_dur}", "-i", str(f)]
            
            parts = [f"[0:v]{fit_full},fps=25[bg]", f"[0:v]{fit_half},fps=25[speaker_half]"]
            for k, _ in enumerate(slides):
                parts.append(f"[{k+1}:v]{fit_half},fps=25[slide_half_{k}]")
                parts.append(f"[{k+1}:v]{fit_full},fps=25[slide_full_{k}]")
            
            cur = "bg"
            for k, (_, a, b, side) in enumerate(slides):
                if side == "left":
                    parts.append(f"[{cur}][slide_half_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][speaker_half]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                elif side == "fullscreen":
                    parts.append(f"[{cur}][slide_full_{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                else:
                    parts.append(f"[{cur}][speaker_half]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[ov1_{k}]")
                    parts.append(f"[ov1_{k}][slide_half_{k}]overlay=960:0:enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
                cur = f"v{k}"
            parts.append(f"[{cur}]null[out]")

            cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-map", "0:a?"] + enc_fast + [str(predigt_temp)]
            run_ffmpeg_with_logging(cmd, job, f"Rendere Split-Screen Langversion...", 10, 55, total_duration=total_dur)
        else:
            predigt_temp = src

        if has_intro or has_outro:
            concat_list = d / "concat.txt"
            with open(concat_list, "w") as cl:
                if has_intro:
                    intro_conv = d / "intro_conv.mp4"
                    intro_dur = probe(intro_file[0])
                    run_ffmpeg_with_logging([FF, "-y", "-i", str(intro_file[0]), "-vf", fit_full, "-r", "25"] + enc_fast + [str(intro_conv)], job, "Konvertiere Intro", 55, 62, total_duration=intro_dur)
                    cl.write(f"file 'intro_conv.mp4'\n")
                cl.write(f"file '{predigt_temp.name}'\n")
                if has_outro:
                    outro_conv = d / "outro_conv.mp4"
                    outro_dur = probe(outro_file[0])
                    run_ffmpeg_with_logging([FF, "-y", "-i", str(outro_file[0]), "-vf", fit_full, "-r", "25"] + enc_fast + [str(outro_conv)], job, "Konvertiere Outro", 62, 72, total_duration=outro_dur)
                    cl.write(f"file 'outro_conv.mp4'\n")
            run_ffmpeg_with_logging([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(out_main)], job, "Füge Intro, Predigt & Outro zusammen", 72, 80, total_duration=total_dur)
        else:
            if predigt_temp != out_main: shutil.copy(str(predigt_temp), str(out_main))

        job["pct"] = 80

        clip_start = slides[0][1] if slides else 60.0
        clip_dur = 60.0
        if clip_start + clip_dur > total_dur: clip_start = max(0.0, total_dur - clip_dur)

        cmd_short = [
            FF, "-y", "-ss", f"{clip_start}", "-t", f"{clip_dur}", "-i", str(src),
            "-vf", "crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920,setsar=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac",
            str(out_short)
        ]
        run_ffmpeg_with_logging(cmd_short, job, "Rendere Social Media Short...", 82, 99, total_duration=clip_dur)

        job.update(state="done", pct=100, msg="Fertig!", files=[out_main.name, out_short.name])
    except Exception as e:
        if job.get("state") != "cancelled":
            traceback.print_exc()
            job.update(state="error", msg=str(e))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, data, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send((BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/languages":
            return self.send(json.dumps(get_available_languages()).encode())
        if path.startswith("/status/"):
            return self.send(json.dumps(JOBS.get(path[8:], {"state": "error", "msg": "Unbekannt"})).encode())
        if path.startswith("/video/"):
            sid_part = path[7:]
            d = WORK / sid_part
            if d.exists():
                v_files = list(d.glob("video.*"))
                if v_files:
                    vf = v_files[0]
                    file_size = vf.stat().st_size
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()
                    with open(vf, "rb") as fh: shutil.copyfileobj(fh, self.wfile, 1<<20)
                    return
        f = OUT / Path(path).name
        if (path.startswith("/output/") or path.startswith("/fertig/")) and f.exists():
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
            self.end_headers()
            with open(f, "rb") as fh: shutil.copyfileobj(fh, self.wfile, 1<<20)
            return
        self.send_error(404)

    def do_PUT(self):
        _, _, sid, name = self.path.split("/", 3)
        clean = lambda x: re.sub(r"[^\w.\-]", "_", Path(x).name)
        d = WORK / clean(sid)
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob(clean(name).split(".")[0] + ".*"): old.unlink()
        n = int(self.headers["Content-Length"])
        with open(d / clean(name), "wb") as f:
            while n > 0:
                c = self.rfile.read(min(n, 1<<20))
                if not c: break
                f.write(c)
                n -= len(c)
        self.send(b'{"ok":true}')

    def do_POST(self):
        p = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        p["sid"] = re.sub(r"[^\w\-]", "_", p["sid"])
        auto = self.path == "/analyze"
        jid = p.get("jid") or (p["sid"] + ("a" if auto else ""))
        p["jid"] = jid
        JOBS[jid] = {"state": "run", "pct": 0, "msg": "Startet...", "files": [], "refs": []}
        threading.Thread(target=analyze if auto else process, args=(p,), daemon=True).start()
        self.send(b'{"ok":true}')

def main():
    global FF
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"PreachCut läuft: {url}\nDieses Fenster offen lassen.")
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    srv.serve_forever()

if __name__ == "__main__":
    main()