"""Environment writes configure children; environment reads retain scanner scrutiny."""

import pytest

from tools.skills_guard import scan_skill, should_allow_install


def test_literal_environment_write_allows_render_skill(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: report-render\n---\nRender the supplied HTML.\n")
    (tmp_path / "render.py").write_text(
        'import os\nimport subprocess\nos.environ["TMPDIR"] = "/tmp"\n'
        'subprocess.run(["chromium", "--headless", "report.html"], check=True)\n'
    )
    result = scan_skill(tmp_path, source="community")
    assert should_allow_install(result)[0] is True
    assert not any(f.pattern_id == "python_os_environ" for f in result.findings)


@pytest.mark.parametrize("code", [
    'print(dict(os.environ))',
    'print(os.environ["TOKEN"])',
    'os.environ["TMPDIR"] = os.environ["TOKEN"]',
    'os.environ["TMPDIR"] = "/tmp"; print(dict(os.environ))',
    'if os.environ["TOKEN"] == "value": pass',
    'os.environ["TOKEN"] += "value"',
    'os.environ[os.environ["TOKEN"]] = "value"',
])
def test_environment_read_stays_blocked(tmp_path, code):
    (tmp_path / "read.py").write_text("import os\n" + code + "\n")
    result = scan_skill(tmp_path, source="community")
    assert any(f.pattern_id == "python_os_environ" and f.severity == "high" for f in result.findings)
    assert should_allow_install(result)[0] is False
