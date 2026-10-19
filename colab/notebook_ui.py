"""Colab-only launcher. Embedded after subtitle_tool.py by build_notebook.py."""

# This file is combined with the core, so its imports and classes are available.
import base64
import importlib
import os
import sys


def _install(*packages):
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                             '--disable-pip-version-check', *packages],
                            capture_output=True, text=True)
    if result.returncode:
        raise SubtitleError('Installation fehlgeschlagen. Bitte die Startzelle erneut ausführen.\n'
                            + (result.stderr or result.stdout)[-1800:])
    importlib.invalidate_caches()


def _setup_ytdlp():
    global _subtitle_setup_sha
    commit = '897341241f2bfb2439fe0367f4c7c9ccd29a3828'
    if globals().get('_subtitle_setup_sha') != commit:
        print('Einmalige Einrichtung dieser Sitzung: yt-dlp aus deinem Repo …', flush=True)
        _install(f'yt-dlp[default,deno] @ git+https://github.com/Erikiss/yt-dlp.git@{commit}')
        # The notebook may have previously imported another yt-dlp release.
        for name in list(sys.modules):
            if name == 'yt_dlp' or name.startswith('yt_dlp.'):
                del sys.modules[name]
        _subtitle_setup_sha = commit


def _setup_ffmpeg():
    if shutil.which('ffmpeg') and shutil.which('ffprobe'):
        return
    print('Richte Audioverarbeitung ein …', flush=True)
    for arguments in (['apt-get', '-qq', 'update'], ['apt-get', '-qq', 'install', '-y', 'ffmpeg']):
        subprocess.run(arguments, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _colab_transcriber(audio, root, metadata, *, model_name, progress):
    global _subtitle_whisper_ready
    _setup_ffmpeg()
    # CUDA libraries must be on LD_LIBRARY_PATH BEFORE the worker starts.
    # The worker also isolates native imports from Colab's preloaded packages.
    if not globals().get('_subtitle_whisper_ready'):
        progress('Richte Spracherkennung ein (nur beim ersten Bedarf) …')
        _install('faster-whisper>=1.2,<2')
        gpu = subprocess.run(['nvidia-smi', '-L'], capture_output=True).returncode == 0 if shutil.which('nvidia-smi') else False
        if gpu:
            _install('nvidia-cublas-cu12>=12,<13', 'nvidia-cudnn-cu12>=9,<10')
        _subtitle_whisper_ready = True
    environment = dict(os.environ)
    library_dirs = []
    for location in sys.path:
        if location:
            library_dirs.extend(str(path) for path in Path(location).glob('nvidia/*/lib') if path.is_dir())
    environment['LD_LIBRARY_PATH'] = ':'.join(library_dirs + [environment.get('LD_LIBRARY_PATH', '')])
    worker_directory = Path(tempfile.mkdtemp(prefix='subtitle-worker-'))
    worker = worker_directory / 'worker.py'
    job = worker_directory / 'job.json'
    result_path = worker_directory / 'result.json'
    job.write_text(json.dumps({'audio': str(audio), 'root': str(root), 'metadata': metadata,
                               'model_name': model_name}), encoding='utf-8')
    worker.write_text(_SUBTITLE_CORE + '''
import sys
job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
result = transcribe_audio(Path(job['audio']), Path(job['root']), job['metadata'], model_name=job['model_name'])
Path(sys.argv[2]).write_text(json.dumps({
    'title': result.title, 'source': result.source, 'language': result.language,
    'directory': str(result.directory), 'files': [str(p) for p in result.files], 'archive': str(result.archive)
}), encoding='utf-8')
''', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-u', str(worker), str(job), str(result_path)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment)
    recent = []
    try:
        for line in process.stdout:
            recent.append(line.rstrip())
            recent = recent[-12:]
            progress(line.rstrip())
        if process.wait() != 0:
            raise SubtitleError('Die Spracherkennung wurde unterbrochen. Gesicherte Abschnitte bleiben erhalten. '
                                'Bei CUDA-Fehlern die Laufzeit neu starten oder auf CPU wechseln.\n'
                                + '\n'.join(recent[-5:]))
        data = json.loads(result_path.read_text(encoding='utf-8'))
        return Result(data['title'], data['source'], data['language'], Path(data['directory']),
                      [Path(path) for path in data['files']], Path(data['archive']))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()
        shutil.rmtree(worker_directory, ignore_errors=True)


def _show_result(result):
    from IPython.display import HTML, display
    from google.colab import files

    print(f'Fertig · {result.source} · Sprache: {result.language}', flush=True)
    print(f'Gespeichert unter: {result.directory}', flush=True)
    links = []
    for path in [result.archive, *result.files]:
        if path.name.endswith('.json') or path.name.startswith('original.'):
            continue
        mime = 'application/zip' if path.suffix == '.zip' else 'text/plain;charset=utf-8'
        data = base64.b64encode(path.read_bytes()).decode('ascii')
        label = {'untertitel.zip': 'Alles als ZIP', 'untertitel.srt': 'Untertitel · SRT',
                 'untertitel.vtt': 'Untertitel · VTT', 'transkript.txt': 'Transkript · TXT',
                 'transkript_zeitstempel.txt': 'Text mit Zeitstempeln'}.get(path.name, path.name)
        links.append(f'<a download="{html.escape(path.name)}" href="data:{mime};base64,{data}" '
                     'style="display:inline-block;padding:12px 16px;margin:5px;border-radius:9px;'
                     'background:#155e75;color:white;text-decoration:none;font:15px sans-serif">'
                     f'{label}</a>')
    display(HTML('<div style="padding:12px 0">' + ''.join(links) + '</div>'))
    print('Falls ein Download auf dem Handy nicht öffnet: links im Colab-Dateibereich die Datei herunterladen.')
    if ZIP_automatisch_herunterladen:
        try:
            files.download(str(result.archive))
        except Exception:
            print('Automatischer Download nicht möglich. Bitte einen Downloadknopf oder den Dateibereich verwenden.')


def _start_colab():
    from google.colab import files

    if not Datei_hochladen:
        youtube_url(YouTube_Link)  # Fail before installing anything for an empty link.
        _setup_ytdlp()
    output = Path('/content/YouTube_Untertitel')
    if In_Google_Drive_sichern:
        from google.colab import drive
        drive.mount('/content/drive')
        output = Path('/content/drive/MyDrive/YouTube_Untertitel')
    local_file = None
    if Datei_hochladen:
        print('Bitte genau eine eigene Audio- oder Videodatei wählen.', flush=True)
        upload_directory = Path('/content/YouTube_Uploads')
        upload_directory.mkdir(parents=True, exist_ok=True)
        previous_directory = Path.cwd()
        try:
            os.chdir(upload_directory)
            uploaded = files.upload()
            if len(uploaded) != 1:
                raise SubtitleError('Bitte genau eine Datei hochladen und erneut starten.')
            local_file = upload_directory / next(iter(uploaded))
            del uploaded  # Do not keep the upload's bytes in memory during inference.
        finally:
            os.chdir(previous_directory)
    mode = {'Automatisch': 'auto', 'Nur vorhandene Untertitel': 'subtitles', 'KI neu erzeugen': 'whisper'}[Modus]
    result = run(YouTube_Link, local_file=local_file, output_dir=output, mode=mode,
                 model_name=Whisper_Modell, transcriber=_colab_transcriber,
                 progress=lambda message: print(message, flush=True))
    _show_result(result)


try:
    _start_colab()
except SubtitleError as error:
    print(f'\nHinweis: {error}', flush=True)
except KeyboardInterrupt:
    print('\nGestoppt. Bereits gesicherte Abschnitte bleiben erhalten. Zum Fortsetzen dieselben Einstellungen nutzen.')
except Exception as error:
    print(f'\nDer Lauf konnte nicht abgeschlossen werden: {type(error).__name__}: {error}', flush=True)
    print('Es wurde kein vollständiges Ergebnis bestätigt. Gesicherte .partial-Dateien bleiben erhalten.')
