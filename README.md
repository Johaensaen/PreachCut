# Gottesdienst-Video-Cutter

Lokaler Videoschnitt für Gottesdienstaufnahmen. Die Spracherkennung und das Rendern laufen auf dem eigenen Rechner.

## Starten

- **Windows:** `Start.bat` öffnen.
- **macOS:** `Start.command` öffnen.
- **Linux:** im Projektordner `python3 start.py` ausführen.

Das Terminalfenster während der Nutzung geöffnet lassen. Beim ersten Start werden benötigte Python-Pakete eingerichtet. Beim ersten Analyselauf werden die lokalen Modelle heruntergeladen; dafür ist eine Internetverbindung erforderlich. Danach laufen Analyse und Schnitt lokal. Die Dauer hängt von Videolänge und Rechner ab.

Das lokale Textmodell für Highlight-Vorschläge ist etwa 940 MB groß; rund 3 GB RAM werden empfohlen. Die Gesichtserkennung folgt der größten erkannten Person im Bild; bei mehreren Personen ist das nicht zwingend der Sprecher.

Während Analyse und Videoschnitt verhindert die Anwendung auf unterstützten Systemen vorübergehend den Ruhemodus. Die Sperre wird nach Ende oder Abbruch des Auftrags aufgehoben. Bildschirm- und Energiespareinstellungen können je nach Betriebssystem abweichen.

## Ablauf

1. Predigtvideo auswählen. Intro und Outro sind optional und werden an die 16:9-Langversion angefügt.
2. „Video analysieren“ starten. Danach werden Bibelstellen gesucht und drei Hochkantvorschläge erstellt. Die Vorschau startet standardmäßig automatisch; der Rechner kann währenddessen weiterarbeiten.
3. Die niedrig aufgelöste Langvorschau und drei Hochkantvarianten prüfen. Nur die gewünschten Clips auswählen und in hoher Qualität rendern.
4. Bei Bedarf Verse, Folien und Zeitpunkte im Editor anpassen und „Schnelle Vorschauen erstellen“ erneut starten. Merksätze lassen sich beim Abspielen hinzufügen; der aktuelle Zeitpunkt wird übernommen.

## Hinweise

- Bibelstellen werden automatisch gesucht. Merksätze werden nicht automatisch erkannt. Highlight-Kategorien sind lokale Textmodell-Vorschläge und keine verlässliche Audio- oder Emotionsanalyse.
- Es entstehen drei niedrig aufgelöste Hochkantvorschauen und eine 16:9-Vorschau. Wähle die gewünschten Hochkantclips aus; nur diese werden anschließend in hoher Qualität gerendert.
- Die Gesichtserkennung versucht, die größte sichtbare Person im Hochkantbild zu zentrieren. Bei mehreren Personen kann sie die falsche Person verfolgen; ohne Gesichtserkennung wird mittig zugeschnitten. Der Vorschau-Player zeigt den verwendeten Modus.
- Aufträge und Auswahl bleiben lokal gespeichert. Nach einem Neustart können unterbrochene Aufträge über „Letzte Aufträge“ erneut gestartet werden. Browser-Benachrichtigungen benötigen Berechtigung und funktionieren, solange der Browser geöffnet bleibt.
- Das Sprachmodell verarbeitet die Aufnahme lokal. CSS, Symbole und Schriftdateien der Oberfläche liegen im Projekt; für die Darstellung im Browser ist keine CDN-Verbindung nötig.
- Zum Ändern der Oberfläche ist Node.js nur für `npm install` und `npm run build:css` erforderlich. Zum normalen Start wird Node.js nicht benötigt.
- Für ein vorbereitetes Offline-Paket `Offline-Paket-erstellen.bat` (Windows) oder `Offline-Paket-erstellen.command` (macOS/Linux) starten und danach den vollständigen Projektordner inklusive `pakete` und `modelle` kopieren. Das Paket ist an das Betriebssystem und die Python-Version gebunden, auf denen es vorbereitet wurde.