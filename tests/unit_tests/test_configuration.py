"""Unit tests for ConfigurationManager and configuration logic."""

import os
import sys

# Add the project root to the path to import modules
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

import pytest

from reference_api_buddy.core.config import DEFAULT_CONFIG, ConfigurationManager, ConfigurationValidator


def test_default_config_valid():
    valid, errors = ConfigurationValidator.validate_config(DEFAULT_CONFIG)
    assert valid
    assert errors == []


def test_merge_with_defaults():
    user = {"server": {"host": "0.0.0.0"}}
    merged = ConfigurationValidator.merge_with_defaults(user)
    assert merged["server"]["host"] == "0.0.0.0"
    assert merged["server"]["request_timeout"] == 30


def test_invalid_config_raises():
    bad = {"server": {"host": 123, "request_timeout": "bad"}}
    with pytest.raises(ValueError):
        ConfigurationManager(bad)


def test_update_and_reload():
    cm = ConfigurationManager({"server": {"host": "127.0.0.1"}})
    cm.update("server.host", "0.0.0.0")
    assert cm.config["server"]["host"] == "0.0.0.0"
    new_cfg = {"server": {"host": "localhost", "request_timeout": 10}}
    cm.reload(new_cfg)
    assert cm.config["server"]["host"] == "localhost"
    assert cm.config["server"]["request_timeout"] == 10


def test_update_invalid_key_raises():
    cm = ConfigurationManager()
    with pytest.raises(ValueError):
        cm.update("server.request_timeout", "not_an_int")
