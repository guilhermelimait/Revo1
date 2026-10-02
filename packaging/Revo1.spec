# PyInstaller spec for Revo1.exe (a windowed, one-folder build).
# Build with packaging\build.ps1, or: pyinstaller packaging\Revo1.spec
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
    VSVersionInfo)

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "revo1"
VERSION = re.search(r'__version__ = "([^"]+)"', (PACKAGE / "__init__.py").read_text()).group(1)
numbers = tuple(int(part) for part in VERSION.split(".")[:3]) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "guilhermelimait"),
            StringStruct("FileDescription", "Revo1"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Revo1"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "Revo1.exe"),
            StringStruct("ProductName", "Revo1"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(PACKAGE / "fonts"), "revo1/fonts"),
           (str(PACKAGE / "assets"), "revo1/assets")],
    # The WinRT projections are imported lazily, so name the ones used.
    hiddenimports=collect_submodules("winrt.windows.media.control")
    + collect_submodules("winrt.windows.foundation")
    # Bluetooth for the wireless link (bleak and the WinRT parts it uses).
    + collect_submodules("bleak") + collect_submodules("winrt.windows.devices")
    + collect_submodules("winrt.windows.storage.streams")
    + ["winrt.system", "comtypes.stream"],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Revo1",
    icon=str(PACKAGE / "assets" / "revo1.ico"),
    version=version_info,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Revo1", upx=False)
