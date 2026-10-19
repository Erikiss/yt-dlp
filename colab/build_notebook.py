"""Rebuild the self-contained, single-form Colab notebook (standard library only)."""

import json
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
In_Google_Drive_sichern = False #@param {type:"boolean"}
Datei_hochladen = False #@param {type:"boolean"}
Whisper_Modell = "auto" #@param ["auto", "small", "medium", "turbo", "large-v3"]
ZIP_automatisch_herunterladen = True #@param {type:"boolean"}
#@markdown **Drive:** Ergebnisse und KI-Zwischenstände dauerhaft sichern (Google fragt nach Freigabe).
#@markdown **Datei hochladen:** eigene Audio-/Videodatei statt Link, z. B. wenn YouTube den Abruf blockiert.
#@markdown **KI:** Sprache bleibt im Original. `auto` nutzt Turbo auf GPU, Small auf CPU. Keine Übersetzung.

'''
source = form + f'_SUBTITLE_CORE = {core!r}\nexec(compile(_SUBTITLE_CORE, "subtitle_tool.py", "exec"))\n\n' + ui
intro = '''# YouTube → Untertitel & Transkript

**Version 1.1** · Korrektur für fehlende Videolänge und bessere Fehlermeldungen auf dem Handy.

**Link einfügen. ▶ drücken. Dateien herunterladen.** Funktioniert im Browser auf Handy, Tablet und PC.

1. Im Feld **YouTube_Link** den Videolink einfügen.
2. Links neben der Zelle **▶** drücken. Beim ersten Start gegebenenfalls mit Google anmelden und „Trotzdem ausführen“ bestätigen.
3. Anschließend **ZIP, SRT, VTT oder TXT** herunterladen. Für das nächste Video Link austauschen und erneut ▶ drücken.

**Standard:** vorhandene Untertitel in der Originalsprache bevorzugen; falls keine vorhanden sind, Sprache mit Whisper erkennen. Kein API-Key. Für vorhandene Untertitel reicht die normale CPU-Laufzeit.

**Sehr lange Videos ohne Untertitel:** vor dem Start bei Bedarf **Laufzeit → Laufzeittyp ändern → T4 GPU** wählen; eine A100 ist nicht erforderlich. Für dauerhafte Zwischenstände **In_Google_Drive_sichern** anhaken. Whisper verarbeitet 10-Minuten-Abschnitte und sichert nach jedem fertigen Abschnitt. Dieselbe Datei/Link und dieselbe Modellwahl setzen den Lauf fort. Ohne Drive bleiben Sicherungen nur bis zum Löschen der Laufzeit erhalten. Colab kann Sitzungen beenden; eine unbegrenzte Laufzeit wird nicht zugesichert.

**YouTube kann Cloud-Zugriffe blockieren.** Dann erklärt das Notebook den Fehler. Alternativ **Datei_hochladen** wählen und eine eigene Audio-/Videodatei verwenden. Das benötigt keinen YouTube-Zugriff.

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
