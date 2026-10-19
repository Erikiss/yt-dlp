# YouTube-Untertitel: ein Link, eine Startzelle

[![In Colab öffnen](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Erikiss/yt-dlp/blob/subtitle-colab/colab/YouTube_Untertitel.ipynb)

**Version 1.1:** Behebt den gemeldeten Fehler `unsupported operand type(s) for /: 'NoneType' and 'float'`. yt-dlp berechnete Vorschaubild-Zeitangaben trotz fehlender Videolänge. Der Untertitel-Einstieg überspringt diese unbenötigten Storyboards in einer eigenen Extractor-Instanz. Explizite YouTube-Anmelde-/Zugriffsfehler werden auch im Metadatenmodus nicht mehr unterdrückt; Fehlermeldungen werden auf kleinen Bildschirmen umgebrochen. Die Sicherungen vorhandener Transkriptionsläufe bleiben kompatibel.

## Sofort starten

1. **In Colab öffnen** anklicken; falls nötig bei Google anmelden.
2. Den Video-Link in **YouTube_Link** einfügen und **▶** drücken. Beim ersten Ausführen eines GitHub-Notebooks kann Colab einmal nachfragen.
3. ZIP herunterladen – oder SRT, VTT, TXT einzeln auswählen. Für das nächste Video denselben Schritt wiederholen.

Keine Kommandozeile, kein API-Key und kein lokales Installieren nötig. Das Notebook enthält den vollständigen Anwendungscode und lässt sich auch als Kopie in Drive speichern. Der Link funktioniert direkt auf diesem Branch; ein Merge ist nicht erforderlich.

## Was passiert?

- Vorhandene Untertitel in der Originalsprache werden bevorzugt; danach YouTube-Autountertitel. Wenn die Originalsprache nicht ermittelbar ist, wird die gewählte vorhandene Spur ausdrücklich bezeichnet.
- Fehlen Untertitel, lädt yt-dlp die Tonspur und Whisper erzeugt Untertitel. Falls eine Tonspur nicht einzeln verfügbar ist, kann der Download ein Video mit Ton enthalten.
- Der Modus **Nur vorhandene Untertitel** verhindert jede KI-Transkription. **KI neu erzeugen** nutzt Whisper auch bei vorhandenen Untertiteln.
- Vorhandene Untertitel benötigen keine GPU. Whisper nutzt bei `auto` **turbo auf GPU** und **small auf CPU**. Für lange Videos ist eine T4 sinnvoll; eine A100 ist nicht nötig. Die Laufzeit wird von diesem Notebook nicht automatisch umgestellt.
- Keine Übersetzung, Zusammenfassung oder künstliche Längenbegrenzung. Erkennungsfehler bleiben möglich, besonders bei Fachbegriffen, Musik und überlappender Sprache.
- Laufende/angekündigte Livestreams und Playlists werden nicht verarbeitet. Ein Videolink mit Playlist-Zusatz verarbeitet nur dieses Video.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `untertitel.srt` | Untertitel mit Zeitangaben für Videoplayer |
| `untertitel.vtt` | Untertitel für Webplayer |
| `transkript.txt` | Vollständiger Text in Absätzen, ohne Zeitstempel |
| `transkript_zeitstempel.txt` | Vollständiger Text mit Zeitstempeln |
| `info.json` | Titel, Herkunft, erkannte Sprache und Abschlussstatus |
| `original.json3` / `original.vtt` | Unveränderte YouTube-Untertitel, wenn abgerufen |
| `untertitel.zip` | Die fertigen Ausgabedateien zusammen |

Rollende Wiederholungen werden beim Umwandeln nur für zeitlich überlappende Untertitelzeilen reduziert. Die unveränderten Originaldaten bleiben erhalten. Bei ungewöhnlichen YouTube-Spuren kann eine manuelle Nachbearbeitung sinnvoll sein.

## Lange Videos, Drive und Wiederaufnahme

**In_Google_Drive_sichern** speichert in `Meine Ablage/YouTube_Untertitel`. Google fragt dafür nach dem Zugriff auf Drive. Ohne diese Option liegt alles in `/content/YouTube_Untertitel` und verschwindet beim Zurücksetzen/Löschen der Colab-Laufzeit.

Whisper liest jeweils etwa zehn Minuten Audio statt die ganze mehrstündige Datei in den Arbeitsspeicher zu laden. Drei Sekunden Kontext um Abschnittsgrenzen helfen bei angeschnittenen Wörtern. Nach jedem abgeschlossenen Abschnitt werden `fortschritt.json` und ausdrücklich als `.partial` bezeichnete Dateien gesichert. Die Originaltonspur wird für YouTube-Transkriptionen unter `_audio` zwischengespeichert, bei aktivierter Drive-Option ebenfalls dauerhaft. Sie ist nicht im ZIP enthalten.

Nach einem Abbruch dieselben Einstellungen, denselben Link bzw. dieselbe Datei und denselben Ausgabeort nutzen. Fertige Abschnitte werden anhand des Inhalts der Audiodatei und des Modells wiederverwendet. Bei einer anders kodierten Tonspur wird sicherheitshalber neu begonnen. Bei `auto` wechselt das Modell zwischen CPU und GPU; für die Wiederaufnahme über verschiedene Hardwaretypen hinweg dasselbe explizite Modell wählen. Ein abgebrochener Download kann gegebenenfalls erneut nötig sein. Ein noch nicht abgeschlossener Abschnitt muss neu gerechnet werden. Eine CPU kann für zehn Minuten Audio erheblich länger als zehn Minuten brauchen.

**Colab hat Laufzeit- und Ressourcenlimits.** Diese Lösung hebt sie nicht auf. Sie hält auch das Handy nicht künstlich wach und verhindert keinen Sitzungsabbruch. Nach Gebrauch eine nicht mehr benötigte GPU-Laufzeit manuell trennen.

## Wenn YouTube blockiert

YouTube kann Zugriffe aus Rechenzentren mit 403, 429, Bot-/Anmeldeprüfungen oder PO-Token-Anforderungen blockieren. Auch mit korrektem Code ist daher kein Erfolg für jeden Link garantiert. Das Notebook meldet diesen Fall gesondert und gibt ihn nicht als „keine Untertitel“ aus. Es verwendet keine Proxys, Cookies oder Maßnahmen zum Umgehen von Zugriffssperren.

Alternativ **Datei_hochladen** anhaken und eine eigene Audio-/Videodatei wählen. Dann arbeitet Whisper unabhängig von YouTube. Für sehr große Dateien ist ein manueller Upload in Colabs Dateibereich bzw. eine bereits in Drive liegende Datei praktischer als der Formularupload, der die Datei zunächst im Speicher hält. Das portable Python-Skript unterstützt dafür `--file`.

Auf iPhone/iPad Colab möglichst in Safari öffnen. Falls der automatische Download nicht startet, einen Downloadknopf benutzen oder die fertige Datei im linken Colab-Dateibereich herunterladen. Die Darstellung der Downloadknöpfe wurde nicht in einer echten iOS-/Colab-Sitzung getestet.

## Außerhalb von Colab

Voraussetzungen: Python 3.10+, FFmpeg; für GPU-Whisper die passenden CUDA-12-/cuDNN-9-Bibliotheken. Für reine vorhandene Untertitel ist FFmpeg nicht erforderlich.

```bash
python -m pip install 'yt-dlp[default,deno] @ git+https://github.com/Erikiss/yt-dlp.git@897341241f2bfb2439fe0367f4c7c9ccd29a3828'
python colab/subtitle_tool.py 'https://www.youtube.com/watch?v=VIDEO_ID' --mode subtitles

# Optional: Sprache erkennen
python -m pip install 'faster-whisper>=1.2,<2'
python colab/subtitle_tool.py --file lecture.mp3 --model small
```

## Wartung und Prüfung

yt-dlp wird aus **diesem Fork**, Quellstand `897341241f2bfb2439fe0367f4c7c9ccd29a3828`, mit den dazugehörigen EJS- und Deno-Abhängigkeiten installiert. Der feste Stand macht die Quelle nachvollziehbar, benötigt nach YouTube-Änderungen aber gegebenenfalls ein Update. Den Commit in `notebook_ui.py` und in der Notebook-Einleitung von `build_notebook.py` aktualisieren und neu bauen. Das Notebook braucht keine Laufzeit-Downloads des Anwendungscodes; nur Pakete und gegebenenfalls das Whisper-Modell werden geladen.

```bash
python -m unittest discover -s colab -p 'test_subtitle_tool.py' -v
python colab/build_notebook.py
```

Die Offlineprüfungen decken URL-Validierung, Sprachwahl, rollende Wiederholungen, lange Transkripte, ZIP/SRT/TXT-Ausgaben, Zugriffsfehler und unterbrochene/fertiggestellte Whisper-Sicherungen ab. Die Whisper-Prüfung simuliert das Modell; sie misst keine Erkennungsqualität und prüft keinen echten GPU-Lauf. Ein vollständiger Live-Durchlauf in Google Colab muss mit einem tatsächlich zugänglichen Video erfolgen.

Primärdokumentation: [yt-dlp](https://github.com/yt-dlp/yt-dlp#readme), [YouTube-JavaScript-Runtime/EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Colab-FAQ](https://research.google.com/colaboratory/faq.html).

Diese persönliche Bedienoberfläche wurde auf Anforderung für den Fork erstellt. Sie ist kein Beitrag an das Upstream-Projekt.
