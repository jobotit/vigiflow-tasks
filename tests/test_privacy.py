"""Keeping report data out of the logs and off the disk.

These are the tests for a rule that is invisible when it works: nothing here
proves the process runs, only that what it reads does not outlive the reading.
"""

from vigiflow_tasks import privacy


# -- trimming what goes into a message -------------------------------------


def test_only_the_first_line_of_an_error_survives():
    """Playwright lists the text of matching elements, one per line.

    That text is patient data, so everything after the first line goes.
    """
    err = ValueError(
        "strict mode violation: resolved to 3 elements:\n"
        "  1) <td>Juan Perez</td>\n"
        "  2) <td>Maria Lopez</td>"
    )
    message = privacy.safe_message(err)
    assert message == "ValueError: strict mode violation: resolved to 3 elements:"
    assert "Perez" not in message


def test_a_long_first_line_is_capped():
    message = privacy.safe_message(RuntimeError("x" * 500))
    assert len(message) <= privacy.MESSAGE_LIMIT + len("RuntimeError: ") + 3
    assert message.endswith("...")


def test_the_kind_of_failure_is_still_named():
    """Trimming must not leave a message that says nothing at all."""
    assert privacy.safe_message(TimeoutError()) == "TimeoutError"


def test_a_plain_string_is_trimmed_without_a_type():
    assert privacy.safe_message("could not open\nsecond line") == "could not open"


# -- not logging values ----------------------------------------------------


def test_the_log_guard_works_without_the_task_framework():
    """The unit tests run without robocorp installed, so it degrades quietly."""
    with privacy.no_data_in_logs():
        pass


# -- removing what the run created -----------------------------------------


def _touch(directory, name, content="x"):
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_discard_removes_the_files_and_names_them(tmp_path):
    workbook = _touch(tmp_path, "REPORTES DEL VIGIFLOW DEL DIA 13-09-2026.xlsx")
    shot = _touch(tmp_path, "link-row-5.png")

    removed = privacy.discard([workbook, shot])

    assert sorted(removed) == sorted([workbook.name, shot.name])
    assert not workbook.exists()
    assert not shot.exists()


def test_discard_tolerates_a_file_that_is_already_gone(tmp_path):
    """The reply is sent by this point; a missing file must not fail the run."""
    assert privacy.discard([tmp_path / "never-existed.xlsx", None]) == []


def test_sweep_clears_report_data_left_by_an_earlier_run(tmp_path):
    _touch(tmp_path, "REPORTES DEL VIGIFLOW DEL DIA 12-09-2026.xlsx")
    _touch(tmp_path, "Links.xlsx")
    _touch(tmp_path, "link-row-2.png")
    _touch(tmp_path, "VigiFlow_PE-DIGEMID-300315548.pdf")

    removed = privacy.sweep(tmp_path)

    assert len(removed) == 4
    assert list(tmp_path.iterdir()) == []


def test_sweep_leaves_the_frameworks_own_files_alone(tmp_path):
    """log.html is written as the process exits and is not ours to delete."""
    kept = [
        _touch(tmp_path, "log.html"),
        _touch(tmp_path, "output.robolog"),
        _touch(tmp_path, "environment_windows_amd64_freeze.yaml"),
    ]
    data = _touch(tmp_path, "Links.xlsx")

    removed = privacy.sweep(tmp_path)

    assert removed == [data.name]
    assert all(path.exists() for path in kept)


def test_sweep_on_a_directory_that_is_not_there_is_not_an_error(tmp_path):
    assert privacy.sweep(tmp_path / "absent") == []


def test_the_local_work_item_queue_is_cleared(tmp_path, monkeypatch):
    """Payloads carry the scraped rows, so locally they are data in a folder."""
    queue = tmp_path / "devdata" / "work-items-out"
    (queue / "email-consumer").mkdir(parents=True)
    (queue / "email-consumer" / "work-items.json").write_text("[]", encoding="utf-8")
    (queue / "email-consumer" / "link-row-4.png").write_text("x", encoding="utf-8")
    monkeypatch.setenv(
        "RC_WORKITEM_OUTPUT_PATH", str(queue / "email-reporter" / "work-items.json")
    )

    removed = privacy.sweep_local_queue()

    assert sorted(removed) == ["link-row-4.png", "work-items.json"]
    assert not queue.exists()


def test_the_queue_sweep_does_nothing_in_control_room(monkeypatch):
    """There the queue is the platform's storage, with its own retention."""
    monkeypatch.delenv("RC_WORKITEM_OUTPUT_PATH", raising=False)
    assert privacy.sweep_local_queue() == []


def test_the_queue_sweep_refuses_an_unexpected_path(tmp_path, monkeypatch):
    """A differently configured adapter must not turn this into a wider delete."""
    elsewhere = tmp_path / "important" / "step"
    elsewhere.mkdir(parents=True)
    (elsewhere / "keep.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RC_WORKITEM_OUTPUT_PATH", str(elsewhere / "work-items.json"))

    assert privacy.sweep_local_queue() == []
    assert (elsewhere / "keep.json").exists()
