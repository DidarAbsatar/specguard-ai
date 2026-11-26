from pathlib import Path
import runpy

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithRevision(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        source = runpy.run_path(str(root / "provenance.py"))
        fingerprint = source["build_id"]()
        commit = source["revision"](root, fingerprint)
        stamp = Path(self.build_lib) / "_specguard_release.py"
        if commit:
            stamp.write_text(f"# {commit} {fingerprint}\n", encoding="ascii")
        else:
            stamp.unlink(missing_ok=True)


setup(cmdclass={"build_py": BuildWithRevision})
