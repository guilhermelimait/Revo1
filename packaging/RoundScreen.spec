# PyInstaller spec for RoundScreen.exe (a windowed, one-folder build).
# Build with packaging\build.ps1, or: pyinstaller packaging\RoundScreen.spec
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
    VSVersionInfo)

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "roundscreen"
VERSION = re.search(r'__version__ = "([^"]+)"', (PACKAGE / "__init__.py").read_text()).group(1)
numbers = tuple(int(part) for part in VERSION.split(".")[:3]) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "guilhermelimait"),
            StringStruct("FileDescription", "RoundScreen"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "RoundScreen"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "RoundScreen.exe"),
            StringStruct("ProductName", "RoundScreen"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(PACKAGE / "fonts"), "roundscreen/fonts"),
           (str(PACKAGE / "assets"), "roundscreen/assets")],
    # The WinRT projections are imported lazily, so name the ones used.
    hiddenimports=collect_submodules("winrt.windows.media.control")
    + collect_submodules("winrt.windows.foundation")
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
    name="RoundScreen",
    icon=str(PACKAGE / "assets" / "roundscreen.ico"),
    version=version_info,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="RoundScreen", upx=False)
