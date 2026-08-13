from pathlib import Path


def test_windows_launcher_detaches_gui_process_from_cmd() -> None:
    script = (Path(__file__).parents[1] / "run.bat").read_text(encoding="utf-8")

    assert "pythonw.exe" in script.lower()
    assert 'start "" /b' in script.lower()
    assert "python -m petnest" not in script.lower()
