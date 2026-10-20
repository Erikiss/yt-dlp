# YouTube-Untertitel: ein Link, eine Startzelle

[![In Colab öffnen](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Erikiss/yt-dlp/blob/subtitle-colab/colab/YouTube_Untertitel.ipynb)

[**Schnelle GPU-Voreinstellung öffnen (A100, Turbo, Videolink bereits eingetragen)**](https://colab.research.google.com/github/Erikiss/yt-dlp/blob/subtitle-colab/colab/YouTube_Untertitel_GPU.ipynb)

**Version 1.5:** Separates GPU-Notebook mit A100 als gewünschter Hardware, `turbo`, Batch 32, Beam 1 und automatischem ZIP-Download. Der Link zur Aufzeichnung `nWCutquolHk` ist bereits eingetragen und ihr Ende bestätigt. Einfach ▶ drücken; Colab kann eine Anmeldung oder Ausführungsbestätigung verlangen. Die GPU-Zuteilung hängt von Colab ab. Falls keine GPU verbunden ist, fordert das Notebook die Auswahl unter **Laufzeit → Laufzeittyp ändern** an, bevor Downloads beginnen. Der normale CPU-Lauf kann im bisherigen Notebook weiterlaufen.

Der Schnellmodus verwendet `BatchedInferencePipeline`: Innerhalb jedes Zehn-Minuten-Abschnitts werden mehrere Audioteile gleichzeitig auf der GPU verarbeitet. `beam_size=1`, `best_of=1` und `temperature=0` reduzieren die Textsuche. Wortzeitstempel, Sprachaktivitätserkennung und Kontext an den Abschnittsgrenzen bleiben aktiv. Bei GPU-Speichermangel wird ausschließlich der unvollständige Abschnitt mit halbierter Batchgröße erneut gerechnet; Ergebnisse eines fehlgeschlagenen Versuchs werden verworfen. Schnellmodus und Normalmodus haben getrennte Sicherungen. Die normalen Sicherungen aus Version 1.3/1.4 bleiben kompatibel. Der Schnellmodus kann andere Erkennungsfehler liefern; er ist kein Nachweis einer auf jeder Hardware maximalen Geschwindigkeit.

Downloadzeit, Modellvorbereitung sowie Audioaufbereitung und Spracherkennung pro Abschnitt werden getrennt ausgegeben. Nach jedem gesicherten Abschnitt erscheint eine grobe Restzeitschätzung anhand des in diesem Lauf gemessenen Tempos. Standardmäßig bleiben die Dateien im temporären Colab-Speicher; der fertige ZIP-Download wird automatisch angestoßen. Dauerhafte Drive-Sicherung ist vor dem Start optional zuschaltbar. Die Laufzeit wird nicht automatisch beendet.

**Version 1.4:** Behebt `TypeError: open() got an unexpected keyword argument 'metadata_errors'` beim Start von Whisper. `faster-whisper==1.2.1` wird zusammen mit `av==18.1.0` installiert; PyAV 19 hat das von dieser Whisper-Version verwendete Argument entfernt ([Upstream-Fehlerbericht](https://github.com/SYSTRAN/faster-whisper/issues/1589)). Vor dem Modellstart wird der echte Audio-Decoder mit einer kurzen WAV-Datei geprüft. Die Einrichtung erkennt auch eine bereits ausgeführte ältere Notebook-Version. Workerfehler werden mit ihrer tatsächlichen Meldung zurückgegeben. Vorhandene Audio- und Transkriptionssicherungen bleiben kompatibel.

**Eine laufende Sitzung mit Version 1.3 reparieren:** Eine zusätzliche Codezelle mit `%pip install -q "faster-whisper==1.2.1" "av==18.1.0"` ausführen und anschließend die bisherige Startzelle erneut starten. Die Laufzeit dafür nicht zurücksetzen: Die Tonspur unter `/content` bleibt dann erhalten. Whisper läuft in einem neuen Unterprozess und lädt dort die korrigierten Pakete; ein Neustart der Colab-Laufzeit ist dafür nicht erforderlich.

**Version 1.3:** Vorhandene Untertitel werden zuerst über `youtube-transcript-api==1.2.4` angefragt. Dieser Weg benötigt keine Audio-/Videoformate und berücksichtigt die Originalsprache sowie den Live-Status aus derselben Playerantwort. Falls er scheitert, folgt yt-dlp. Ein Playerfehler beendet die Metadatensuche nicht mehr vor der Untertitelauswertung; wenn auch dort keine Untertitel abrufbar sind, bleibt der Playerfehler in der Diagnose erhalten. Im Metadatenlauf werden keine HLS-/DASH-Manifeste geladen. Fehler zeigen je Abrufweg den Typ und die tatsächliche Meldung; URL-Abfrageparameter werden entfernt. Zwei Abrufwege garantieren keinen Zugriff aus jeder Cloud-Umgebung. Der konkret gemeldete Videolink konnte hier bisher nicht erfolgreich als Transkript abgerufen werden.

**Version 1.2:** Beendete Streams (`was_live`/`post_live`) haben Vorrang vor einem widersprüchlichen `is_live`-Flag. Ein Endzeitpunkt in den YouTube-Metadaten korrigiert veraltete Live-Angaben schon vor der Formatauswahl. Wenn YouTube trotzdem weiter „live“ meldet, kann man **Stream_bereits_beendet** bestätigen. Vorhandene Untertitel werden dann abgerufen. Für noch nicht fertig verarbeitete/so bestätigte Aufzeichnungen werden nur endliche HTTP(S)-Mediendateien mit bekannter Dateigröße für Whisper gewählt; rollende Manifest-Ausschnitte werden nicht als vollständige Aufzeichnung ausgegeben. Die verfügbare Tonspur wird bei bekannter Gesamtdauer auf deutliche Verkürzung geprüft. Ein zu kurzer Download wird als `audio.incomplete.*` abgelegt, damit ein neuer Versuch die fertige Tonspur erneut abrufen kann.

**Version 1.1:** Behebt den gemeldeten Fehler `unsupported operand type(s) for /: 'NoneType' and 'float'`. yt-dlp berechnete Vorschaubild-Zeitangaben trotz fehlender Videolänge. Der Untertitel-Einstieg überspringt diese unbenötigten Storyboards in einer eigenen Extractor-Instanz. Explizite YouTube-Anmelde-/Zugriffsfehler werden auch im Metadatenmodus nicht mehr unterdrückt; Fehlermeldungen werden auf kleinen Bildschirmen umgebrochen. Die Sicherungen vorhandener Transkriptionsläufe bleiben kompatibel.

## Sofort starten

1. **In Colab öffnen** anklicken; falls nötig bei Google anmelden.
2. Den Video-Link in **YouTube_Link** einfügen und **▶** drücken. Beim ersten Ausführen eines GitHub-Notebooks kann Colab einmal nachfragen.
3. ZIP herunterladen – oder SRT, VTT, TXT einzeln auswählen. Für das nächste Video denselben Schritt wiederholen.

Keine Kommandozeile, kein API-Key und kein lokales Installieren nötig. Das Notebook enthält den vollständigen Anwendungscode und lässt sich auch als Kopie in Drive speichern. Der Link funktioniert direkt auf diesem Branch; ein Merge ist nicht erforderlich.

## Was passiert?

- Zuerst versucht `youtube-transcript-api` vorhandene Untertitel abzurufen. Bei einem Fehler oder einer leeren Spur folgt yt-dlp aus diesem Fork. Beide Wege bevorzugen manuelle Untertitel in der Originalsprache vor YouTube-Autountertiteln. Wenn die Originalsprache nicht ermittelbar ist, wird das ausdrücklich bezeichnet.
- Fehlen Untertitel, lädt yt-dlp die Tonspur und Whisper erzeugt Untertitel. Falls eine Tonspur nicht einzeln verfügbar ist, kann der Download ein Video mit Ton enthalten.
- Der Modus **Nur vorhandene Untertitel** verhindert jede KI-Transkription. **KI neu erzeugen** nutzt Whisper auch bei vorhandenen Untertiteln.
- Vorhandene Untertitel benötigen keine GPU. Whisper nutzt bei `auto` **turbo auf GPU** und **small auf CPU**. Für lange Videos reicht auch eine T4. Das separate GPU-Notebook hinterlegt A100 als gewünschte Colab-Hardware; die tatsächliche Zuteilung übernimmt Colab. Der Code stellt eine bereits laufende Sitzung nicht automatisch um.
- Keine Übersetzung, Zusammenfassung oder künstliche Längenbegrenzung. Erkennungsfehler bleiben möglich, besonders bei Fachbegriffen, Musik und überlappender Sprache.
- `/live/VIDEO_ID` ist auch für beendete Aufzeichnungen gültig. Ein noch als live gemeldetes Video wird erst nach Bestätigung **Stream_bereits_beendet** als Aufzeichnung versucht. Eine dauerhafte Liveaufnahme und Playlists werden nicht verarbeitet. Ein Videolink mit Playlist-Zusatz verarbeitet nur dieses Video.

Kurz nach dem Ende können die fertige Tonspur oder automatische Untertitel noch fehlen. YouTube erstellt automatische Untertitel für die Aufzeichnung neu; die Live-Untertitel werden nicht einfach übernommen ([YouTube-Hilfe](https://support.google.com/youtube/answer/6373554?hl=de)). Die Bestätigung „Stream bereits beendet“ ändert diese Verfügbarkeit nicht. Fehlen die nötigen Daten, später erneut starten. Eine feste Wartezeit lässt sich nicht zusagen.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `untertitel.srt` | Untertitel mit Zeitangaben für Videoplayer |
| `untertitel.vtt` | Untertitel für Webplayer |
| `transkript.txt` | Vollständiger Text in Absätzen, ohne Zeitstempel |
| `transkript_zeitstempel.txt` | Vollständiger Text mit Zeitstempeln |
| `info.json` | Titel, Herkunft, erkannte Sprache und Abschlussstatus |
| `original.json3` / `original.vtt` | Unveränderte YouTube-Untertitel, wenn abgerufen |
| `original.transcript-api.json` | Vom direkten Transkriptclient gelieferte Segmente, vor der Bereinigung |
| `untertitel.zip` | Die fertigen Ausgabedateien zusammen |

Rollende Wiederholungen werden beim Umwandeln nur für zeitlich überlappende Untertitelzeilen reduziert. Die unveränderten Originaldaten bleiben erhalten. Bei ungewöhnlichen YouTube-Spuren kann eine manuelle Nachbearbeitung sinnvoll sein.

## Lange Videos, Drive und Wiederaufnahme

**In_Google_Drive_sichern** speichert in `Meine Ablage/YouTube_Untertitel`. Google fragt dafür nach dem Zugriff auf Drive. Ohne diese Option liegt alles in `/content/YouTube_Untertitel` und verschwindet beim Zurücksetzen/Löschen der Colab-Laufzeit.

Whisper liest jeweils etwa zehn Minuten Audio statt die ganze mehrstündige Datei in den Arbeitsspeicher zu laden. Drei Sekunden Kontext um Abschnittsgrenzen helfen bei angeschnittenen Wörtern. Nach jedem abgeschlossenen Abschnitt werden `fortschritt.json` und ausdrücklich als `.partial` bezeichnete Dateien gesichert. Die Originaltonspur wird für YouTube-Transkriptionen unter `_audio` zwischengespeichert, bei aktivierter Drive-Option ebenfalls dauerhaft. Sie ist nicht im ZIP enthalten.

Nach einem Abbruch dieselben Einstellungen, denselben Link bzw. dieselbe Datei und denselben Ausgabeort nutzen. Fertige Abschnitte werden anhand des Inhalts der Audiodatei und des Modells wiederverwendet. Bei einer anders kodierten Tonspur wird sicherheitshalber neu begonnen. Bei `auto` wechselt das Modell zwischen CPU und GPU; für die Wiederaufnahme über verschiedene Hardwaretypen hinweg dasselbe explizite Modell wählen. Ein abgebrochener Download kann gegebenenfalls erneut nötig sein. Ein noch nicht abgeschlossener Abschnitt muss neu gerechnet werden. Eine CPU kann für zehn Minuten Audio erheblich länger als zehn Minuten brauchen.

**Colab hat Laufzeit- und Ressourcenlimits.** Diese Lösung hebt sie nicht auf. Sie hält auch das Handy nicht künstlich wach und verhindert keinen Sitzungsabbruch. Nach Gebrauch eine nicht mehr benötigte GPU-Laufzeit manuell trennen.

## Wenn YouTube blockiert

YouTube kann Zugriffe aus Rechenzentren mit 403, 429, Bot-/Anmeldeprüfungen oder PO-Token-Anforderungen blockieren. Auch mit korrektem Code ist daher kein Erfolg für jeden Link garantiert. Unter **Technische Details** zeigt das Notebook die Fehler beider Abrufwege. Ein Videoplayerfehler allein sagt nicht, ob Untertitel abrufbar sind. Der direkte Transkriptclient dokumentiert selbst mögliche Cloud-IP-Blockaden ([Projekt-Dokumentation](https://github.com/jdepoix/youtube-transcript-api)). Es werden keine externen Bezahldienste oder Proxy-Abos eingerichtet.

Alternativ **Datei_hochladen** anhaken und eine eigene Audio-/Videodatei wählen. Dann arbeitet Whisper unabhängig von YouTube. Für sehr große Dateien ist ein manueller Upload in Colabs Dateibereich bzw. eine bereits in Drive liegende Datei praktischer als der Formularupload, der die Datei zunächst im Speicher hält. Das portable Python-Skript unterstützt dafür `--file`.

Auf iPhone/iPad Colab möglichst in Safari öffnen. Falls der automatische Download nicht startet, einen Downloadknopf benutzen oder die fertige Datei im linken Colab-Dateibereich herunterladen. Die Darstellung der Downloadknöpfe wurde nicht in einer echten iOS-/Colab-Sitzung getestet.

## Außerhalb von Colab

Voraussetzungen: Python 3.11+, FFmpeg; für GPU-Whisper die passenden CUDA-12-/cuDNN-9-Bibliotheken. Für reine vorhandene Untertitel ist FFmpeg nicht erforderlich.

```bash
python -m pip install 'yt-dlp[default,deno] @ git+https://github.com/Erikiss/yt-dlp.git@897341241f2bfb2439fe0367f4c7c9ccd29a3828'
python -m pip install 'youtube-transcript-api==1.2.4'
python colab/subtitle_tool.py 'https://www.youtube.com/watch?v=VIDEO_ID' --mode subtitles

# Optional: Sprache erkennen
python -m pip install 'faster-whisper==1.2.1' 'av==18.1.0'
python colab/subtitle_tool.py --file lecture.mp3 --model small
# Optional: schnelle Verarbeitung auf einer vorhandenen CUDA-GPU
python colab/subtitle_tool.py --file lecture.mp3 --model turbo --fast-gpu
```

## Wartung und Prüfung

yt-dlp wird aus **diesem Fork**, Quellstand `897341241f2bfb2439fe0367f4c7c9ccd29a3828`, mit den dazugehörigen EJS- und Deno-Abhängigkeiten installiert. Der feste Stand macht die Quelle nachvollziehbar, benötigt nach YouTube-Änderungen aber gegebenenfalls ein Update. Den Commit in `notebook_ui.py` und in der Notebook-Einleitung von `build_notebook.py` aktualisieren und neu bauen. Das Notebook braucht keine Laufzeit-Downloads des Anwendungscodes; nur Pakete und gegebenenfalls das Whisper-Modell werden geladen.

```bash
python -m unittest discover -s colab -p 'test_subtitle_tool.py' -v
python colab/build_notebook.py
```

Die 36 Offlineprüfungen decken URL-Validierung, Sprachwahl, rollende Wiederholungen, lange Transkripte, ZIP/SRT/TXT-Ausgaben, Zugriffsfehler und unterbrochene/fertiggestellte Whisper-Sicherungen ab. Für beendete Streams prüfen sie außerdem widersprüchliche Live-Angaben, vergangene/zukünftige Endzeiten im echten Extractor, die ausdrückliche Bestätigung, unvollständige Audioformate und zu kurze Downloads. Der echte Transkriptclient wird mit HTTP-Testantworten geprüft; dabei darf kein Medienabruf gestartet werden. Weitere Fälle prüfen abrufbare Untertitel trotz Playerfehler und die Diagnose beider fehlgeschlagener Wege. Für den GPU-Schnellmodus werden außerdem die Ablehnung einer CPU-Laufzeit, Wiederholung nach Speichermangel ohne doppelte Ausgaben, Weitergabe anderer Fehler, Wiederaufnahme mit korrekten Zeitmarken sowie die Kompatibilität alter Sicherungen geprüft. Die Whisper-Prüfung simuliert das Modell; sie misst keine Erkennungsqualität und prüft keinen echten GPU-Lauf. Ein vollständiger Durchlauf in Google Colab muss mit einem tatsächlich zugänglichen Video erfolgen.

Für Version 1.4 wurde der gemeldete Fehler zusätzlich mit den echten Paketen `faster-whisper==1.2.1` und `av==19.0.1` reproduziert. Nach Installation von `av==18.1.0` bestanden sowohl der Decodertest als auch das Einlesen einer von FFmpeg erzeugten WAV-Datei (6.400 Float32-Samples bei 16 kHz). Für Python 3.13 wurde die Verfügbarkeit des passenden Linux-Wheels geprüft; der Decoderlauf selbst fand unter Python 3.12 statt.

Primärdokumentation: [yt-dlp](https://github.com/yt-dlp/yt-dlp#readme), [YouTube-JavaScript-Runtime/EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Colab-FAQ](https://research.google.com/colaboratory/faq.html).

Diese persönliche Bedienoberfläche wurde auf Anforderung für den Fork erstellt. Sie ist kein Beitrag an das Upstream-Projekt.
