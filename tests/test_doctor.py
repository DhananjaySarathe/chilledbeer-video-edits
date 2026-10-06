from shorts import doctor


def test_doctor_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    result = doctor.doctor()
    assert result["passed"] is False
    assert any(c["name"] == "whisper-cli" and not c["ok"] for c in result["checks"])
