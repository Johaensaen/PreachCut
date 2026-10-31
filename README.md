# PreachCut

A local, AI-assisted tool for editing sermon recordings. Speech recognition, Bible reference detection, and video rendering run completely locally on your computer.

> **Note on Language:** PreachCut is currently optimized for **German** sermon recordings (German speech recognition, German Bible book keywords, and German reference patterns).

---

## Features

- **Local Speech Recognition & Verse Detection:** Automatically transcribes German audio and recognizes German Bible references (e.g., *Johannes 3,16*, *1. Korinther 13*).
- **Interactive Multi-View Editing:** Choose between left/right split-screen or full-screen overlays for slides and verses.
- **Dual-Format Output:** Generates a 16:9 long-form video with embedded slides and a cropped 9:16 portrait video optimized for social media highlights.
- **Smart Caching:** Fast re-rendering using local transcription caches without re-running heavy AI analysis.

---

## First-Time Setup & Installation

### Prerequisites
- **Python 3.9 or higher** installed on your system.
- **FFmpeg** (automatically managed via `imageio-ffmpeg` or installed on system PATH).
- An active internet connection for the **very first launch** (to download required Python packages and local AI models).

### Step-by-Step Guide

1. **Get the Code**
   Clone this repository or download and extract the ZIP archive:
   git clone https://github.com/YOUR-USERNAME/PreachCut.git
   cd PreachCut

2. **Launch the Application**
   Run the appropriate startup script for your operating system:
   - **Windows:** Double-click `Start.bat`
   - **macOS:** Double-click `Start.command` *(If prompted with permission warnings, run `chmod +x Start.command` in Terminal once)*
   - **Linux:** Run `python3 start.py` in your terminal

3. **Automatic Dependency Setup**
   On the first launch, the script automatically creates an isolated virtual environment (`.venv`) and installs all required dependencies.

4. **First AI Model Download**
   When you run your first video analysis, the local Whisper model (speech-to-text) and text model (~940 MB) will download automatically into the project directory.

5. **Open in Browser**
   Once started, your default web browser will automatically open:
   http://localhost:8766
   *Keep the terminal window open while using the application.*

---

## Workflow

1. **Upload Media:** Select your sermon video. Optional intro and outro files can be added and are automatically stitched to the 16:9 long version.
2. **Analyze Video:** Click **"High-Speed Analyse starten"**. The app transcribes the audio, detects German Bible references, and prepares timestamps.
3. **Edit Verses & Slides:** Adjust verse timings, set slide layouts (*Left*, *Right*, or *Fullscreen*), or add custom memory points directly while playing the video preview.
4. **Quick Re-previews:** Use **"Schnelle Vorschauen erstellen"** to quickly update slide alignment and timings using cached transcription data without re-running the full AI model.
5. **Render & Export:** Render the final 16:9 long-form video and 9:16 highlight short.

---

## System Requirements & Notes

- **Language Support:** Optimized for **German** speech and German Bible book nomenclature.
- **Hardware & RAM:** Around 3 GB of free RAM is recommended. Total rendering and transcription time depends heavily on your CPU/GPU hardware and video length.
- **Face Detection:** Automatically centers the largest detected face for 9:16 portrait crops. If multiple people are in the frame, tracking may follow the wrong person; unchecking face tracking defaults to a centered crop.
- **Power Management:** During analysis and rendering, the app temporarily prevents system sleep mode on supported OSs.
- **Offline Package:** To create a standalone offline installer for air-gapped machines, run `Offline-Paket-erstellen.bat` (Windows) or `Offline-Paket-erstellen.command` (macOS/Linux). This bundles the full dependencies and local model files into the `pakete/` and `modelle/` folders.
- **UI Customization:** Tailwind CSS styles are pre-compiled and bundled. Node.js/npm is only required if you plan to modify and recompile the frontend styles (`npm run build:css`).

---

## License

Distributed under the MIT License. See `THIRD_PARTY_NOTICES.md` for third-party component licenses.
