from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def main() -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 1

    if not REQUIREMENTS.is_file():
        print(f"Could not find requirements.txt at: {REQUIREMENTS}")
        return 1

    if not VENV_DIR.exists():
        print("Creating virtual environment...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    if sys.platform == "win32":
        python = VENV_DIR / "Scripts" / "python.exe"
    else:
        python = VENV_DIR / "bin" / "python"

    print("Installing requirements...")
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=ROOT,
    )
    if result.returncode:
        return result.returncode

    print("Starting API at http://127.0.0.1:8000 (press Ctrl+C to stop)")
    try:
        return subprocess.run(
            [
                str(python), "-m", "uvicorn", "app.main:app",
                "--host", "127.0.0.1", "--port", "8000",
            ],
            cwd=ROOT,
        ).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())