"""Windows OCR 대체 경로: PowerShell(5.1)로 같은 Windows 내장 OCR(Windows.Media.Ocr)을 부른다.

왜 필요한가: 기본 경로는 `winrt` 파이썬 패키지(_winrt.pyd)를 쓰는데, Smart App Control·WDAC·AppLocker 같은
'애플리케이션 제어 정책'이 켜진 PC는 서명 없는 .pyd를 막아 `DLL load failed while importing _winrt`가 난다.
PowerShell은 Microsoft 서명 프로그램이라 같은 정책에서도 실행되므로, 그쪽으로 OCR만 대신 시킨다 (추가 DLL 없음).
OCR 엔진은 같은 Windows 내장 엔진이라 결과가 같다. PowerShell 프로세스를 하나 띄워 두고 요청마다 재사용한다(매번 띄우면 느리다).
core.py가 winrt를 못 불러올 때(또는 환경변수 GTFO_OCR_BACKEND=ps)에만 쓴다.

한계: 정책이 PowerShell을 '제한된 언어 모드(Constrained Language Mode)'로 강제하는 PC에서는 이 방법도 막힐 수 있다 → IT 담당자에게
_winrt.pyd 허용(또는 Python 폴더 허용)을 요청해야 한다."""
import atexit
import os
import subprocess
import tempfile
import threading

_PS = r'''
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), $utf8)
$writer = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), $utf8)
$writer.NewLine = "`n"; $writer.AutoFlush = $true
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.FileAccessMode, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    function Await($op, $type) {
        $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
        [void]$task.Wait(-1)
        return $task.Result
    }
    $inv = [System.Globalization.CultureInfo]::InvariantCulture
    $writer.WriteLine("READY")
} catch {
    $writer.WriteLine("ERR`t" + ($_.Exception.Message -replace "[\r\n\t]+", " "))
    exit 1
}
while ($true) {
    $line = $reader.ReadLine()
    if ($null -eq $line) { break }
    $p = $line.Split("`t")
    try {
        if ($p[0] -eq 'LANGS') {
            foreach ($l in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
                $writer.WriteLine("L`t" + $l.LanguageTag + "`t" + $l.DisplayName)
            }
        } elseif ($p[0] -eq 'OCR') {
            $lang = $p[1]; $path = $p[2]
            $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
            $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            if ($lang -eq '' -or $lang -eq 'auto') {
                $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
            } else {
                $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language($lang)))
            }
            if ($null -eq $engine) {
                $writer.WriteLine("ERR`tLANG`t" + $lang)
            } else {
                $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
                foreach ($ln in $res.Lines) {
                    foreach ($w in $ln.Words) {
                        $r = $w.BoundingRect
                        $writer.WriteLine("W`t" + $w.Text + "`t" + $r.X.ToString($inv) + "`t" + $r.Y.ToString($inv) + "`t" +
                                          $r.Width.ToString($inv) + "`t" + $r.Height.ToString($inv))
                    }
                }
            }
            $stream.Dispose()
        }
    } catch {
        $writer.WriteLine("ERR`t" + ($_.Exception.Message -replace "[\r\n\t]+", " "))
    }
    $writer.WriteLine("END")
}
'''


class _Server:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.tmp = None
        self.seq = 0
        self.failed = ""

    def _start(self):
        if self.failed:
            raise RuntimeError(self.failed)
        if not self.tmp or not os.path.isdir(self.tmp):
            self.tmp = tempfile.mkdtemp(prefix="gtfo_ocr_")
        ps1 = os.path.join(self.tmp, "ocr.ps1")
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(_PS)
        self.proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        first = self._readline()
        if first != "READY":
            self._stop()
            self.failed = ("PowerShell로 Windows OCR을 시작하지 못했습니다 (" + first.replace("ERR\t", "") + "). "
                           "보안 정책이 PowerShell을 제한하고 있을 수 있습니다. IT 담당자에게 `_winrt.pyd` 허용을 요청하거나, "
                           "Windows 보안 > 앱 및 브라우저 컨트롤 > 스마트 앱 컨트롤 설정을 확인하세요.")
            raise RuntimeError(self.failed)

    def _readline(self) -> str:
        raw = self.proc.stdout.readline()
        return raw.decode("utf-8", "replace").rstrip("\r\n") if raw else ""

    def _stop(self):
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None
        if self.tmp:
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)

    def ensure(self):
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()

    def request(self, line: str) -> list:
        """한 줄 요청을 보내고 END까지의 응답 줄을 돌려준다."""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            self.proc.stdin.write((line + "\n").encode("utf-8"))
            self.proc.stdin.flush()
            out = []
            while True:
                s = self._readline()
                if s == "END":
                    return out
                if s == "" and self.proc.poll() is not None:
                    self._stop()
                    raise RuntimeError("PowerShell OCR 프로세스가 중간에 종료되었습니다.")
                out.append(s)

    def next_image_path(self) -> str:
        with self.lock:
            self.seq += 1
            return os.path.join(self.tmp, f"req_{self.seq}.png")


_srv = _Server()
atexit.register(_srv._stop)


def languages() -> list:
    """[(언어 태그, 표시 이름)] — winrt 경로의 ocr_languages와 같은 형식."""
    try:
        rows = [r.split("\t") for r in _srv.request("LANGS") if r.startswith("L\t")]
        return [(r[1], r[2]) for r in rows if len(r) >= 3] or [("ko", "한국어")]
    except Exception:
        return [("ko", "한국어")]


def recognize(png_bytes: bytes, lang: str = "ko") -> list:
    """[(text, x, y중심, 높이, 너비)] — 입력 PNG 기준 픽셀 좌표 (core._recognize가 배율을 되돌린다)."""
    _srv.ensure()
    path = _srv.next_image_path()         # 호출마다 다른 파일 (Windows OCR이 직전 파일을 잠시 잡고 있어 같은 이름을 덮어쓸 수 없다)
    with open(path, "wb") as f:
        f.write(png_bytes)
    try:
        lines = _srv.request(f"OCR\t{lang or ''}\t{path}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass                          # 아직 잠겨 있으면 종료 때 임시 폴더째 지운다
    words = []
    for s in lines:
        p = s.split("\t")
        if p[0] == "ERR":
            if len(p) > 1 and p[1] == "LANG":
                raise RuntimeError(f"OCR 언어 '{lang}'를 사용할 수 없습니다. Windows 설정 > 시간 및 언어 > 언어에서 "
                                   "해당 언어(OCR 포함)를 설치하세요.")
            raise RuntimeError("Windows OCR(PowerShell) 실패: " + " ".join(p[1:]))
        if p[0] == "W" and len(p) >= 6:
            x, y, w, h = (float(v) for v in p[2:6])
            words.append((p[1], x, y + h / 2, h, w))
    return words


_call_lock = threading.Lock()
