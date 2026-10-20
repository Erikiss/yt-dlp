"""Rebuild the self-contained, single-form Colab notebook (standard library only)."""

import json
import copy
from pathlib import Path


HERE = Path(__file__).resolve().parent
core = (HERE / 'subtitle_tool.py').read_text(encoding='utf-8')
core = core.rsplit("if __name__ == '__main__':", 1)[0].rstrip() + '\n'
ui = (HERE / 'notebook_ui.py').read_text(encoding='utf-8')
form = '''#@title YouTube-Link einfügen → ▶ starten { display-mode: "form" }
#@markdown **Nur den Link einfügen.** Installation, Untertitelwahl und Download laufen automatisch.
YouTube_Link = "" #@param {type:"string"}
#@markdown Optionale Einstellungen – können unverändert bleiben.
Modus = "Automatisch" #@param ["Automatisch", "Nur vorhandene Untertitel", "KI neu erzeugen"]
Stream_bereits_beendet = False #@param {type:"boolean"}
In_Google_Drive_sichern = False #@param {type:"boolean"}
Datei_hochladen = False #@param {type:"boolean"}
Whisper_Modell = "auto" #@param ["auto", "small", "medium", "turbo", "large-v3"]
GPU_Schnellmodus = False #@param {type:"boolean"}
ZIP_automatisch_herunterladen = True #@param {type:"boolean"}
#@markdown **Drive:** Ergebnisse und KI-Zwischenstände dauerhaft sichern (Google fragt nach Freigabe).
#@markdown **Stream bereits beendet:** anhaken, falls YouTube eine beendete Aufzeichnung noch als live meldet. Auch `/live/`-Links sind gültig.
#@markdown **Datei hochladen:** eigene Audio-/Videodatei statt Link, z. B. wenn YouTube den Abruf blockiert.
#@markdown **KI:** Sprache bleibt im Original. `auto` nutzt Turbo auf GPU, Small auf CPU. Keine Übersetzung.
#@markdown **GPU-Schnellmodus:** mehrere Audioteile gleichzeitig, schnellere Textsuche. Benötigt eine GPU; Erkennungsfehler können sich verändern.

'''
source = form + f'_SUBTITLE_CORE = {core!r}\nexec(compile(_SUBTITLE_CORE, "subtitle_tool.py", "exec"))\n\n' + ui
intro = '''# YouTube → Untertitel & Transkript

**Version 1.5** · Zusätzlicher GPU-Schnellmodus und Zeitmessung pro Abschnitt. [A100-Voreinstellung öffnen](https://colab.research.google.com/github/Erikiss/yt-dlp/blob/subtitle-colab/colab/YouTube_Untertitel_GPU.ipynb). Die bisherigen CPU-Einstellungen bleiben Standard; Sicherungen aus Version 1.3/1.4 lassen sich damit fortsetzen.

**Link einfügen. ▶ drücken. Dateien herunterladen.** Funktioniert im Browser auf Handy, Tablet und PC.

1. Im Feld **YouTube_Link** den Videolink einfügen.
2. Links neben der Zelle **▶** drücken. Beim ersten Start gegebenenfalls mit Google anmelden und „Trotzdem ausführen“ bestätigen.
3. Anschließend **ZIP, SRT, VTT oder TXT** herunterladen. Für das nächste Video Link austauschen und erneut ▶ drücken.

**Standard:** vorhandene Untertitel zuerst mit `youtube-transcript-api`, danach bei Bedarf mit yt-dlp abrufen. Die Originalsprache wird bevorzugt; falls sie nicht ermittelbar ist, wird das gekennzeichnet. Falls kein Untertitelabruf gelingt und die Tonspur zugänglich ist, Sprache mit Whisper erkennen. Kein API-Key. Für vorhandene Untertitel reicht die normale CPU-Laufzeit.

**Gerade beendeter Stream:** Der `/live/`-Link bleibt gültig. Wenn YouTube weiterhin „live“ meldet, **Stream_bereits_beendet** aktivieren. Das Tool versucht vorhandene Untertitel und eine fertige Audiodatei abzurufen. YouTube kann die Aufzeichnung und die neuen automatischen Untertitel noch verarbeiten; dann meldet das Tool das gesondert. Es startet keine dauerhafte Liveaufnahme und gibt keinen erkennbar unvollständigen Audioausschnitt als ganzes Video aus.

**Sehr lange Videos ohne Untertitel:** vor dem Start bei Bedarf **Laufzeit → Laufzeittyp ändern → T4 GPU** wählen; eine A100 ist nicht erforderlich. Für dauerhafte Zwischenstände **In_Google_Drive_sichern** anhaken. Whisper verarbeitet 10-Minuten-Abschnitte und sichert nach jedem fertigen Abschnitt. Dieselbe Datei/Link und dieselbe Modellwahl setzen den Lauf fort. Ohne Drive bleiben Sicherungen nur bis zum Löschen der Laufzeit erhalten. Colab kann Sitzungen beenden; eine unbegrenzte Laufzeit wird nicht zugesichert.

**Falls der Abruf scheitert:** Unter „Technische Details“ stehen die Ergebnisse beider Abrufwege, etwa eine Anfragegrenze, eine Anmeldeanforderung oder ein Verbindungsfehler. Eine solche Meldung bedeutet nicht, dass das Video keine Untertitel hat. Für eine gezielte Fehleranalyse bitte diese Details mitkopieren. Alternativ **Datei_hochladen** wählen und eine eigene Audio-/Videodatei verwenden.

Die Ausgabe ist vollständig und wird nicht zusammengefasst. `transkript.txt` ist zum Lesen und für ChatGPT; `untertitel.srt`/`.vtt` enthalten Zeitangaben. KI-Ergebnisse können Erkennungsfehler enthalten. Kein künstliches Limit für die Videolänge; Laufzeit, Speicher und YouTube-Zugriff bleiben praktische Grenzen.

Nutzt [Erikiss/yt-dlp](https://github.com/Erikiss/yt-dlp), festgelegten Quellstand `897341241f2bfb2439fe0367f4c7c9ccd29a3828`. [Anleitung & technische Details](https://github.com/Erikiss/yt-dlp/blob/subtitle-colab/colab/README.md).
'''
notebook = {
    'nbformat': 4, 'nbformat_minor': 5,
    'metadata': {
        'colab': {'name': 'YouTube_Untertitel.ipynb', 'provenance': []},
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python'},
    },
    'cells': [
        {'id': 'instructions', 'cell_type': 'markdown', 'metadata': {}, 'source': intro.splitlines(keepends=True)},
        {'id': 'one-click', 'cell_type': 'code',
         'metadata': {'cellView': 'form', 'id': 'one-click'},
         'source': source.splitlines(keepends=True), 'outputs': [], 'execution_count': None},
    ],
}
destination = HERE / 'YouTube_Untertitel.ipynb'
destination.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(destination)

# A different notebook path creates a separate Colab session from the CPU run.
gpu_notebook = copy.deepcopy(notebook)
gpu_notebook['metadata']['accelerator'] = 'GPU'
gpu_notebook['metadata']['colab'].update(name='YouTube_Untertitel_GPU.ipynb', gpuType='A100')
gpu_form = form.replace('YouTube_Link = ""', 'YouTube_Link = "https://www.youtube.com/watch?v=nWCutquolHk"')
gpu_form = gpu_form.replace('Stream_bereits_beendet = False', 'Stream_bereits_beendet = True')
gpu_form = gpu_form.replace('Whisper_Modell = "auto"', 'Whisper_Modell = "turbo"')
gpu_form = gpu_form.replace('GPU_Schnellmodus = False', 'GPU_Schnellmodus = True')
gpu_form = gpu_form.replace('YouTube-Link einfügen → ▶ starten', 'Dein Video ist eingetragen → ▶ starten')
gpu_form = gpu_form.replace('**Nur den Link einfügen.**', '**Dein Video ist eingetragen. Einfach ▶ drücken.**')
gpu_source = gpu_form + source[len(form):]
gpu_intro = '''# YouTube → Untertitel · schnelle GPU-Voreinstellung

**Version 1.5 · Dein Video ist bereits eingetragen. Einfach ▶ drücken.**

A100 als gewünschte GPU, Whisper **turbo**, parallele Verarbeitung und schnelle Textsuche sind voreingestellt. Installation, Abruf und ZIP-Download laufen automatisch. Vorhandene Untertitel werden weiterhin zuerst versucht; falls sie nicht abrufbar sind, wird die Tonspur transkribiert. Die Sprache bleibt im Original.

Colab kann vor dem Start eine Anmeldung oder „Trotzdem ausführen“ verlangen. Die tatsächlich zugeteilte GPU wird ausgegeben. Falls noch keine GPU verbunden ist, **Laufzeit → Laufzeittyp ändern → A100 GPU** wählen. Die Zuteilung hängt von deinem Colab-Konto und der Verfügbarkeit ab. Eine andere NVIDIA-GPU funktioniert ebenfalls.

**Zum parallelen Start dieses separate Notebook benutzen.** Deinen laufenden CPU-Job im anderen Notebook weiterlaufen lassen. Hier wird ein eigener Durchlauf gestartet.

Nach jedem Zehn-Minuten-Abschnitt siehst du Bearbeitungszeit, Geschwindigkeit und geschätzte Restzeit. Download, Modellvorbereitung und eigentliche Spracherkennung werden getrennt ausgewiesen. Turbo mit Schnellmodus kann andere Erkennungsfehler liefern als Small im bisherigen CPU-Lauf. Eine konkrete Beschleunigung ist erst nach dem Lauf gemessen.

**Speichern:** Am Ende wird der ZIP-Download angestoßen; zusätzlich erscheinen Downloadknöpfe für TXT/SRT/VTT. Für dauerhafte Zwischenstände vor dem Start optional **In_Google_Drive_sichern** aktivieren und Googles Freigabe bestätigen. Ohne Drive bleiben die Zwischenstände nur in der Colab-Laufzeit. Die GPU-Laufzeit bei Bedarf nach dem Download manuell trennen.

Für ein anderes Video einfach **YouTube_Link** austauschen. **Stream_bereits_beendet** ist für die hier eingetragene Aufzeichnung aktiviert; bei anderen Videos nur aktivieren, wenn ein gemeldeter Livestream tatsächlich beendet ist.

[Anleitung](https://github.com/Erikiss/yt-dlp/blob/subtitle-colab/colab/README.md) · [Normale Voreinstellung](https://colab.research.google.com/github/Erikiss/yt-dlp/blob/subtitle-colab/colab/YouTube_Untertitel.ipynb)
'''
gpu_notebook['cells'][0]['source'] = gpu_intro.splitlines(keepends=True)
gpu_notebook['cells'][1]['source'] = gpu_source.splitlines(keepends=True)
gpu_destination = HERE / 'YouTube_Untertitel_GPU.ipynb'
gpu_destination.write_text(json.dumps(gpu_notebook, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(gpu_destination)
