import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

HIGHLIGHT_MODEL = "qwen2-1_5b-instruct-q4_0.gguf"
HIGHLIGHT_MODEL_URL = "https://huggingface.co/Qwen/Qwen2-1.5B-Instruct-GGUF/resolve/main/qwen2-1_5b-instruct-q4_0.gguf"
HIGHLIGHT_MODEL_SIZE = 937532800
HIGHLIGHT_MODEL_MD5 = "a8c5a783105f87a481543d4ed7d7586d"
FACE_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
STYLE_TITLES = {
    "teaching": "Lehre & Bibelbezug",
    "key_message": "Kernaussage",
    "emotional": "Emotionaler Moment (Textvorschlag)"
}

def _file_md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _download(url, target, progress, expected_size=None, expected_md5=None):
    target = Path(target)
    temporary = target.with_suffix(target.suffix + ".part")
    offset = temporary.stat().st_size if temporary.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        append = offset > 0 and response.status == 206
        if offset and not append:
            offset = 0
        total = expected_size or (int(response.headers.get("Content-Length", 0)) + offset)
        digest = hashlib.md5()
        if append:
            with open(temporary, "rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    digest.update(chunk)
        written = offset
        with open(temporary, "ab" if append else "wb") as destination:
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress:
                    progress(f"Lade {target.name} herunter...", written, total)
    if expected_size and written != expected_size:
        raise ValueError(f"Unerwartete Modelldateigröße: {written} statt {expected_size} Bytes")
    if expected_md5 and digest.hexdigest() != expected_md5:
        temporary.unlink(missing_ok=True)
        raise ValueError("Prüfsumme des heruntergeladenen Modells stimmt nicht")
    temporary.replace(target)

def ensure_face_model(model_dir, progress=None):
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / FACE_MODEL
    if not target.exists() or target.stat().st_size < 50000:
        if progress:
            progress("Lade lokales Sprecher-Erkennungsmodell...", 0, 1)
        _download(FACE_MODEL_URL, target, None)
    return target

def prepare_models(model_dir, progress=None):
    model_dir = Path(model_dir)
    highlight_model = _download_highlight_model(model_dir, progress)
    face_model = ensure_face_model(model_dir, progress)
    return highlight_model, face_model

def _download_highlight_model(model_dir, progress):
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / HIGHLIGHT_MODEL
    if target.exists() and target.stat().st_size == HIGHLIGHT_MODEL_SIZE and _file_md5(target) == HIGHLIGHT_MODEL_MD5:
        return target
    if progress:
        progress("Lade Qwen-Textmodell (ca. 940 MB, einmalig)...", 0, HIGHLIGHT_MODEL_SIZE)
    _download(HIGHLIGHT_MODEL_URL, target, progress, HIGHLIGHT_MODEL_SIZE, HIGHLIGHT_MODEL_MD5)
    return target

def _timestamped_transcript(words, max_chars=14000):
    lines = []
    chunk, chunk_start, chunk_end = [], 0.0, 0.0
    for word in words:
        text = word.get("word", "").strip()
        if not text:
            continue
        start = float(word.get("start", 0))
        end = float(word.get("end", start))
        if chunk and (start - chunk_start >= 18 or len(chunk) >= 55):
            lines.append(f"[{chunk_start:.0f}-{chunk_end:.0f}] {' '.join(chunk)}")
            chunk = []
        if not chunk:
            chunk_start = start
        chunk.append(text)
        chunk_end = end
    if chunk:
        lines.append(f"[{chunk_start:.0f}-{chunk_end:.0f}] {' '.join(chunk)}")
    if not lines:
        return ""
    stride = max(1, math.ceil(sum(len(line) + 1 for line in lines) / max_chars))
    selected = lines[::stride]
    if selected[-1] != lines[-1]:
        selected.append(lines[-1])
    return "\n".join(selected)

def _fallback_candidates(words, refs, duration):
    starts = [float(ref.get("t", 0)) for ref in refs[:1]]
    starts.extend([duration * 0.38, duration * 0.68])
    styles = list(STYLE_TITLES)
    candidates = []
    for index, style in enumerate(styles):
        clip_duration = min(45.0, max(1.0, duration))
        start = max(0.0, min(starts[index] if index < len(starts) else duration * (index + 1) / 4, max(0.0, duration - clip_duration)))
        excerpt = " ".join(
            word.get("word", "") for word in words
            if start <= float(word.get("start", 0)) <= start + clip_duration
        )
        candidates.append({
            "style": style,
            "title": STYLE_TITLES[style],
            "t": round(start, 1),
            "d": round(clip_duration, 1),
            "quote": excerpt[:360],
            "source": "Zeitbasierte Vorauswahl"
        })
    return candidates

def suggest_highlights(words, refs, duration, model_dir, progress=None):
    fallback = _fallback_candidates(words, refs, duration)
    transcript = _timestamped_transcript(words)
    if not transcript:
        return fallback
    try:
        model_path = _download_highlight_model(model_dir, progress)
        from gpt4all import GPT4All
        model = GPT4All(
            model_name=model_path.name,
            model_path=str(model_path.parent),
            allow_download=False,
            device="cpu",
            n_ctx=4096,
            n_threads=max(1, min(8, __import__("os").cpu_count() or 2))
        )
        model.config["systemPrompt"] = "<|im_start|>system\nDu analysierst deutsche Predigttranskripte. Erfinde keine Zitate.<|im_end|>\n"
        model.config["promptTemplate"] = "<|im_start|>user\n{0}<|im_end|>\n<|im_start|>assistant\n{1}<|im_end|>"
        if progress:
            progress("Erstelle drei lokale Highlight-Vorschläge...", 0, 1)
        prompt = (
            "Analysiere dieses deutsche Predigt-Transkript. Wähle genau drei verschiedene, zusammenhängende "
            "Stellen von jeweils 25 bis 55 Sekunden: style teaching (Erklärung/Lehre), key_message "
            "(prägnante Kernaussage) und emotional (emotional formulierte Aussage anhand des Textes; "
            "Audio-Stimmung ist nicht verfügbar). Nutze ausschließlich vorhandene Zeitbereiche. "
            "Gib nur ein JSON-Array mit Objekten {style,start_seconds,end_seconds,quote} aus. "
            "quote muss ein kurzes wörtliches Zitat aus dem Transkript sein. Keine erfundenen Worte.\n\n"
            f"Transkript mit Zeitbereichen:\n{transcript}"
        )
        try:
            with model.chat_session():
                response = model.generate(prompt, max_tokens=500, temp=0.1, top_p=0.8)
        finally:
            model.close()
        match = re.search(r"\[.*\]", response, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else []
        valid = {}
        for item in parsed:
            style = item.get("style")
            if style not in STYLE_TITLES or style in valid:
                continue
            start = float(item.get("start_seconds", 0))
            end = float(item.get("end_seconds", start + 45))
            clip_duration = min(55.0, max(25.0, end - start))
            if not math.isfinite(start) or not math.isfinite(clip_duration):
                continue
            clip_duration = min(clip_duration, max(1.0, duration))
            start = max(0.0, min(start, max(0.0, duration - clip_duration)))
            nearby = [word for word in words if abs(float(word.get("start", 0)) - start) <= 3]
            if nearby:
                start = max(0.0, float(min(nearby, key=lambda word: abs(float(word.get("start", 0)) - start))["start"]))
            excerpt = " ".join(
                word.get("word", "") for word in words
                if start <= float(word.get("start", 0)) <= start + clip_duration
            )
            valid[style] = {
                "style": style,
                "title": STYLE_TITLES[style],
                "t": round(start, 1),
                "d": round(min(clip_duration, max(1.0, duration - start)), 1),
                "quote": excerpt[:360],
                "source": "Lokales Textmodell"
            }
        return [valid.get(style, fallback[index]) for index, style in enumerate(STYLE_TITLES)]
    except Exception as error:
        if isinstance(error, InterruptedError):
            raise
        if progress:
            progress(f"Textmodell nicht verfügbar; nutze Zeitvorschläge ({error})", 0, 1)
        return fallback

def track_speaker_centers(source, ffmpeg, start, duration, face_model, temp_root):
    import cv2

    with tempfile.TemporaryDirectory(prefix="crop-", dir=temp_root) as directory:
        pattern = str(Path(directory) / "frame-%04d.jpg")
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start}", "-t", f"{duration}",
            "-i", str(source), "-vf", "fps=1,scale=640:-2", "-q:v", "5", pattern
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        frames = sorted(Path(directory).glob("frame-*.jpg"))
        if not frames:
            return []
        detector = cv2.FaceDetectorYN.create(str(face_model), "", (640, 360), 0.55, 0.3, 5000)
        centers = []
        previous = None
        for frame_path in frames:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                centers.append(None)
                continue
            height, width = frame.shape[:2]
            detector.setInputSize((width, height))
            _, faces = detector.detect(frame)
            detections = [] if faces is None else list(faces)
            if detections:
                scored = []
                for face in detections:
                    x, y, face_width, face_height = face[:4]
                    center = float(x + face_width / 2) / width
                    area_score = float(face_width * face_height * face[14])
                    scored.append((center, area_score))
                if previous is None:
                    chosen = max(scored, key=lambda item: item[1])[0]
                else:
                    nearby = [item for item in scored if abs(item[0] - previous) < 0.28]
                    chosen = min(nearby, key=lambda item: abs(item[0] - previous))[0] if nearby else max(scored, key=lambda item: item[1])[0]
                previous = chosen
                centers.append(chosen)
            else:
                centers.append(None)
        known = [index for index, center in enumerate(centers) if center is not None]
        if not known:
            return []
        for index, center in enumerate(centers):
            if center is None:
                nearest = min(known, key=lambda known_index: abs(known_index - index))
                centers[index] = centers[nearest]
        smoothed = []
        for center in centers:
            bounded = min(0.95, max(0.05, float(center)))
            smoothed.append(bounded if not smoothed else smoothed[-1] * 0.65 + bounded * 0.35)
        return smoothed

def vertical_crop_filter(centers, width):
    if not centers:
        center_expr = "iw/2"
    else:
        center_expr = f"{centers[-1]:.5f}*iw"
        for index in range(len(centers) - 2, -1, -1):
            start, end = centers[index], centers[index + 1]
            center_expr = f"if(lt(t,{index + 1}),{start:.5f}*iw+({end - start:.5f}*iw)*(t-{index}),{center_expr})"
    crop_width = "min(iw,ih*9/16)"
    crop_x = f"max(0,min(iw-{crop_width},({center_expr})-{crop_width}/2))"
    height = round(width * 16 / 9)
    return f"crop=w='{crop_width}':h=ih:x='{crop_x}':y=0,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"