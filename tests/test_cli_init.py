from pathlib import Path

from lc_auto.cli import _cmd_init


def test_init_uses_config_template_from_env(tmp_path: Path, monkeypatch):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "config.docker.example.yaml").write_text("site: leetcode.cn\n", encoding="utf-8")
    (template_dir / ".env.example").write_text("LC_AUTO_MODEL_API_KEY=replace-me\n", encoding="utf-8")
    (template_dir / "problems.txt").write_text("two-sum\n", encoding="utf-8")

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    monkeypatch.setenv("LC_AUTO_TEMPLATE_DIR", str(template_dir))
    monkeypatch.setenv("LC_AUTO_INIT_CONFIG_TEMPLATE", "config.docker.example.yaml")

    assert _cmd_init() == 0

    assert (work_dir / "config.yaml").read_text(encoding="utf-8") == "site: leetcode.cn\n"
    assert (work_dir / ".env").exists()
    assert (work_dir / "problems.txt").exists()
