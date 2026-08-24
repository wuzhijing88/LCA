from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_build_does_not_bundle_full_vc_redistributable():
    batch = (
        ROOT / "build_assets" / "packaging" / "build_release.bat"
    ).read_text(encoding="utf-8-sig")

    assert "vc_redist.x64.exe" not in batch
    assert 'set "VCRUNTIME=C:\\Windows\\System32"' in batch


def test_release_build_supports_noninteractive_offline_edition():
    batch = (
        ROOT / "build_assets" / "packaging" / "build_release.bat"
    ).read_text(encoding="utf-8-sig")
    setup = (
        ROOT / "build_assets" / "packaging" / "setup.iss"
    ).read_text(encoding="utf-8-sig")

    assert "LCA_NONINTERACTIVE" in batch
    assert "version_info.py" not in batch
    assert "LCA_离线版_Setup.exe" in batch
    assert "OutputBaseFilename=LCA_离线版_Setup" in setup
    assert "MyAppVersion" not in setup


def test_installer_disclaimer_does_not_conflict_with_agpl():
    disclaimer = (ROOT / "resources" / "disclaimer.txt").read_text(encoding="utf-8")

    assert "GNU Affero General Public License v3.0" in disclaimer
    assert "不得对本软件进行反向工程" not in disclaimer
