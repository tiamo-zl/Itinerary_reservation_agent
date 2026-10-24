from itinerary_agent.api.pii import scrub, scrub_obj


def test_scrub_phone_and_id():
    # 网关在入参/出参两个方向都做格式级脱敏。
    text = "联系人 13812345678，身份证 110101199001011234"
    masked = scrub(text)
    assert "13812345678" not in masked
    assert "110101199001011234" not in masked
    assert "[PHONE]" in masked
    assert "[ID]" in masked
    assert scrub_obj({"phone": "13812345678"})["phone"] == "[PHONE]"
    # 系统 ID 里的数字片段不能被误伤。
    assert scrub_obj({"task_id": "6a568faa40734ae193132843160efd1f"})[
        "task_id"
    ] == "6a568faa40734ae193132843160efd1f"
