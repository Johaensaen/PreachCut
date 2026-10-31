# PreachCut

A local tool for editing sermon recordings. Speech recognition and rendering run directly on your computer.

## Getting started

- **Windows:** open `Start.bat`.
- **macOS:** open `Start.command`.
- **Linux:** run `python3 start.py` in the project folder.

Keep the terminal window open while using the app. On the first launch, the required Python packages are installed. On the first analysis run, the local models are downloaded, so an internet connection is required. After that, analysis and export run locally. Total time depends on video length and hardware performance.

The local text model used for highlight suggestions is about 940 MB. Around 3 GB of RAM is recommended. Face detection follows the largest visible face in the frame; with multiple people, this is not always the actual speaker.

During analysis and video rendering, the app temporarily prevents sleep mode on supported systems. The lock is released when the job finishes or is cancelled. Display and energy-saving behavior may vary by operating system.

## Workflow

1. Select the sermon video. Intro and outro files are optional and are appended to the 16:9 long version.
2. Start "Analyze video". The app searches for Bible references and creates three portrait suggestions. The preview begins automatically; the machine can continue working while this is running.
3. Review the low-resolution long preview and three portrait variants. Only select the desired clips and render them in high quality.
4. If needed, adjust verses, slides, and timestamps in the editor and run "Create quick previews" again. You can add memory points while playback is running; the current timestamp is used.

## Notes

- Bible references are detected automatically. Memory points are not detected automatically. Highlight suggestions are generated from the local text model and are not a reliable audio or emotion analysis.
- The app creates three low-resolution portrait previews and one 16:9 preview. Select the portrait clips you want to keep; only those will be rendered in high quality later.
- Face detection tries to center the largest visible person in the portrait crop. With multiple people, it may track the wrong person; without face detection, the crop remains centered. The preview player shows which mode is active.
- Jobs and selections remain stored locally. After a restart, interrupted work can be resumed from "Recent jobs." Browser notifications require permission and stay active as long as the browser remains open.
- The language model processes recordings locally. The interface CSS, icons, and fonts are bundled in the project, so no CDN connection is required for the browser UI.
- To customize the interface, Node.js is only needed for `npm install` and `npm run build:css`. It is not required for normal startup.
- To create an offline package, run `Offline-Paket-erstellen.bat` (Windows) or `Offline-Paket-erstellen.command` (macOS/Linux), then copy the full project folder including the `pakete` and `modelle` directories. The package is tied to the operating system and Python version used during preparation.