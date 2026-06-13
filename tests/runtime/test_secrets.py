"""Tests for runtime.secrets"""


import pytest

from runtime.secrets import load_secrets


def test_load_secrets_basic(tmp_path):
    """Test basic secrets loading."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\nKEY2=value2\n")
    
    secrets = load_secrets(secrets_file)
    assert secrets == {"KEY1": "value1", "KEY2": "value2"}


def test_load_secrets_with_quotes(tmp_path):
    """Test loading secrets with quoted values."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text('KEY1="quoted value"\nKEY2=\'single quoted\'\nKEY3=unquoted\n')
    
    secrets = load_secrets(secrets_file)
    assert secrets["KEY1"] == "quoted value"
    assert secrets["KEY2"] == "single quoted"
    assert secrets["KEY3"] == "unquoted"


def test_load_secrets_skip_comments(tmp_path):
    """Test that comments and empty lines are skipped."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("""
# This is a comment
KEY1=value1

# Another comment
KEY2=value2
    """.strip())
    
    secrets = load_secrets(secrets_file)
    assert secrets == {"KEY1": "value1", "KEY2": "value2"}


def test_load_secrets_required_keys(tmp_path):
    """Test required keys validation."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\nKEY2=value2\n")
    
    # All required keys present
    secrets = load_secrets(secrets_file, required_keys={"KEY1", "KEY2"})
    assert secrets == {"KEY1": "value1", "KEY2": "value2"}
    
    # Missing required key
    with pytest.raises(ValueError, match="Missing required secrets"):
        load_secrets(secrets_file, required_keys={"KEY1", "KEY2", "KEY3"})


def test_load_secrets_optional_keys(tmp_path):
    """Test optional keys."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\n")
    
    secrets = load_secrets(
        secrets_file,
        required_keys={"KEY1"},
        optional_keys={"KEY2", "KEY3"},
    )
    assert secrets == {"KEY1": "value1"}


def test_load_secrets_strict_allowlist(tmp_path):
    """Test that keys not in allowlist raise ValueError."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\nUNEXPECTED=value2\n")
    
    with pytest.raises(ValueError, match="not in the allowlist"):
        load_secrets(
            secrets_file,
            required_keys={"KEY1"},
            optional_keys=set(),
        )


def test_load_secrets_file_not_found():
    """Test that missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_secrets("/nonexistent/path.env")


def test_load_secrets_invalid_format(tmp_path):
    """Test that invalid line format raises ValueError."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\nINVALID_LINE_NO_EQUALS\n")
    
    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        load_secrets(secrets_file)


def test_load_secrets_from_env_var(tmp_path, monkeypatch):
    """Test loading from MCPTOOLING_SECRETS_PATH env var."""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("KEY1=value1\n")
    
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(secrets_file))
    
    secrets = load_secrets()  # No path argument
    assert secrets == {"KEY1": "value1"}
