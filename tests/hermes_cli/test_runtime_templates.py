from hermes_cli.runtime_templates import (
    REQUIRED_TEMPLATE_NAMES,
    load_required_templates,
    load_template,
    missing_required_templates,
)


def test_required_runtime_templates_exist_and_load():
    assert missing_required_templates() == []

    templates = load_required_templates()

    assert set(templates) == set(REQUIRED_TEMPLATE_NAMES)
    assert "supervisor" in templates["supervisor_intake"].lower()
    assert "advisory memory" in templates["memory_packet"].lower()


def test_template_loader_rejects_path_like_names():
    try:
        load_template("../secret")
    except ValueError as exc:
        assert "bare name" in str(exc)
    else:
        raise AssertionError("expected ValueError")

