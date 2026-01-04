"""Tests for config commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from mirustech.devenv_generator.cli import main


class TestConfigShow:
    """Tests for the config show command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_config_show_displays_settings(self, runner: CliRunner) -> None:
        """Should display registry configuration."""
        result = runner.invoke(main, ["config", "show"])
        assert result.exit_code == 0
        assert "Registry Configuration" in result.output
        assert "Enabled:" in result.output
        assert "URL:" in result.output
        assert "Auth Method:" in result.output
        assert "Auto-push:" in result.output
        assert "Timeout:" in result.output

    def test_config_show_with_env_vars(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should reflect environment variable settings."""
        result = runner.invoke(
            main,
            ["config", "show"],
            env={
                "HOME": str(tmp_path),
                "DEVENV_REGISTRY__ENABLED": "true",
                "DEVENV_REGISTRY__URL": "my-registry.example.com",
                "DEVENV_REGISTRY__AUTO_PUSH": "true",
            },
        )
        assert result.exit_code == 0
        assert "True" in result.output  # Enabled
        assert "my-registry.example.com" in result.output

    def test_config_show_shows_config_path(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should show config file path."""
        result = runner.invoke(
            main, ["config", "show"], env={"HOME": str(tmp_path)}
        )
        assert result.exit_code == 0
        assert "Config file:" in result.output


class TestConfigSetRegistry:
    """Tests for the config set-registry command."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_set_registry_creates_config_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should create config file with user inputs."""
        # Simulate user inputs
        # 1. Registry URL (use default)
        # 2. Auth choice (1 = existing)
        # 3. Auto-push (n = no)
        result = runner.invoke(
            main,
            ["config", "set-registry"],
            input="\n1\nn\n",  # Default URL, existing auth, no auto-push
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert "Configuration saved" in result.output

        # Verify config file was created
        config_path = tmp_path / ".config" / "devenv-generator" / "config.env"
        assert config_path.exists()

        content = config_path.read_text()
        assert "DEVENV_REGISTRY__ENABLED=true" in content
        assert "DEVENV_REGISTRY__AUTH_METHOD=existing" in content
        assert "DEVENV_REGISTRY__AUTO_PUSH=false" in content

    def test_set_registry_with_custom_url(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should save custom registry URL."""
        result = runner.invoke(
            main,
            ["config", "set-registry"],
            input="custom.registry.io\n1\nn\n",
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0

        config_path = tmp_path / ".config" / "devenv-generator" / "config.env"
        content = config_path.read_text()
        assert "DEVENV_REGISTRY__URL=custom.registry.io" in content

    def test_set_registry_with_stored_credentials(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should save username and password for stored auth."""
        result = runner.invoke(
            main,
            ["config", "set-registry"],
            input="\nstored\nmyuser\nmypassword\nn\n",
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0
        assert "Password stored in plaintext" in result.output

        config_path = tmp_path / ".config" / "devenv-generator" / "config.env"
        content = config_path.read_text()
        assert "DEVENV_REGISTRY__AUTH_METHOD=stored" in content
        assert "DEVENV_REGISTRY__USERNAME=myuser" in content
        assert "DEVENV_REGISTRY__PASSWORD=mypassword" in content

    def test_set_registry_with_auto_push(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Should save auto-push setting."""
        result = runner.invoke(
            main,
            ["config", "set-registry"],
            input="\n1\ny\n",  # Default URL, existing auth, yes auto-push
            env={"HOME": str(tmp_path)},
        )
        assert result.exit_code == 0

        config_path = tmp_path / ".config" / "devenv-generator" / "config.env"
        content = config_path.read_text()
        assert "DEVENV_REGISTRY__AUTO_PUSH=true" in content


class TestConfigGroup:
    """Tests for the config command group."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_config_help(self, runner: CliRunner) -> None:
        """Should show config help."""
        result = runner.invoke(main, ["config", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output
        assert "set-registry" in result.output
        assert "edit" in result.output
