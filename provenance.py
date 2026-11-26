"""Identify the checked-out or packaged source that actually ran."""
from hashlib import sha256
from pathlib import Path
import re
import subprocess


ENGINE = ("specguard.py", "quality.py", "assessment.py", "reporting.py", "comparison.py", "provenance.py",
          "chatgpt_provider.py", "review_tables.py")


def build_id(files=None):
    if files is None:
        files = {n: Path(__file__).with_name(n).read_bytes() for n in ENGINE}
    return sha256(b"".join(files[n].replace(b"\r\n", b"\n") for n in ENGINE)).hexdigest()[:16]


def revision(root, fingerprint):
    if (root / ".git").exists():
        try:
            git = ["git", "-C", str(root)]
            commit = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True,
                                             stderr=subprocess.DEVNULL, timeout=10).strip()
            clean = subprocess.run([*git, "diff", "--quiet", "HEAD", "--", "."], capture_output=True, timeout=10)
            tracked = subprocess.run([*git, "ls-files", "--error-unmatch", "--", *ENGINE],
                                     capture_output=True, timeout=10)
            if clean.returncode == tracked.returncode == 0 and re.fullmatch("[0-9a-f]{40}", commit):
                return commit
        except (OSError, subprocess.SubprocessError):
            pass
        return None
    stamp = root / "_specguard_release.py"
    if stamp.is_file():
        match = re.fullmatch(r'# ([0-9a-f]{40}) ([0-9a-f]{16})\s*', stamp.read_text(encoding="ascii"))
        if match and match[2] == fingerprint:
            return match[1]
    return None
