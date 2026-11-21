"""El CLI de simulación (``python -m app.cli``): errores del usuario sin traceback (JAJ-110)."""

from __future__ import annotations

import json

import pytest

from app.cli import main
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


@pytest.fixture
def model_file(tmp_path):
    path = tmp_path / "modelo.json"
    path.write_text(json.dumps(load_sample(SAMPLE)), encoding="utf-8")
    return path


def test_runs_a_sample(model_file, capsys):
    assert main([str(model_file), "--scenario", "pico_normal", "--duration", "5"]) == 0
    assert "cuello de botella" in capsys.readouterr().out


def test_unknown_scenario_names_the_ones_that_exist(model_file, capsys):
    """BE-21: antes terminaba en un traceback de KeyError."""
    assert main([str(model_file), "--scenario", "nope"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "nope" in err and "pico_normal" in err and "cyberday" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "content, expected",
    [
        ("{no es json", "error: "),
        ("[1, 2]", "no es un modelo"),
        (json.dumps({"schema": "otra/v1"}), "Esquema no soportado"),
        (json.dumps({"schema": "branchpoint.model/v1"}), "le falta el campo 'deployment'"),
    ],
)
def test_file_that_is_not_a_model(tmp_path, capsys, content, expected):
    path = tmp_path / "malo.json"
    path.write_text(content, encoding="utf-8")
    assert main([str(path)]) == 2
    assert expected in capsys.readouterr().err


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "no_existe.json")]) == 2
    assert "no se pudo leer" in capsys.readouterr().err


def test_parameter_out_of_range(model_file, capsys):
    assert main([str(model_file), "--cache-hit", "2", "--duration", "5"]) == 2
    assert capsys.readouterr().err.startswith("error: ")
