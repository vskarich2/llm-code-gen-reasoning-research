"""Shared test fixtures."""

import sys
import os
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# FORCE mock mode for ALL tests — never use real API in test suite
os.environ["OPENAI_API_KEY"] = "sk-dummy"

import pytest

BASE = Path(__file__).resolve().parents[1]
