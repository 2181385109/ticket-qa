"""
附件上传(合法路径)——等价类划分:四种白名单类型各一个有效类;大小 5MB 闭区间上界。
绕过尝试在 tests/security/test_attachment_bypass.py。
"""
import re

import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("附件"), pytest.mark.db]

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\x00" * 100
JPG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 100
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
TXT = "这是一段中文文本\nsecond line\n".encode("utf-8")
UUID_NAME = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|pdf|txt)"


@allure.story("合法上传")
class TestUpload:

    @pytest.mark.parametrize("filename, ctype, content, ext", [
        ("photo.png", "image/png", PNG, "png"),
        ("photo.jpg", "image/jpeg", JPG, "jpg"),
        ("doc.pdf", "application/pdf", PDF, "pdf"),
        ("note.txt", "text/plain; charset=utf-8", TXT, "txt"),
        ("PHOTO.PNG", "image/png", PNG, "png"),
    ], ids=["png", "jpg", "pdf", "txt", "upper-ext"])
    @allure.title("{filename} ({ctype}) → 201,落盘名 UUID.{ext},库表记录一致")
    def test_valid_types(self, tickets, api, db, config, filename, ctype, content, ext):
        t = tickets.assigned(Users.AGENT_A)
        resp = api.as_user(Users.AGENT_A).upload(t["id"], filename, content, ctype)
        (resp.expect.created()
         .data("ticketId").eq(t["id"])
         .data("originalName").eq(filename)
         .data("ext").eq(ext)
         .data("storedName").matches(UUID_NAME)
         .data("sizeBytes").eq(len(content))
         .data("uploadedBy").eq(Users.AGENT_A.id)
         .data("mimeType").eq(ctype.split(";")[0]))
        row = db.attachments(t["id"])[0]
        assert row["stored_name"] == resp.data["storedName"] and row["size_bytes"] == len(content)
        if config.attachment_dir and config.attachment_dir.exists():
            stored = config.attachment_dir / resp.data["storedName"]
            assert stored.exists() and stored.read_bytes() == content

    @allure.title("边界:恰好 5MB → 201;5MB + 1 字节 → 413 / 41301")
    def test_size_boundary(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        limit = 5 * 1024 * 1024
        api.as_user(Users.AGENT_A).upload(t["id"], "max.png", PNG + b"\x00" * (limit - len(PNG)), "image/png") \
            .expect.created().data("sizeBytes").eq(limit)
        api.as_user(Users.AGENT_A).upload(t["id"], "over.png", PNG + b"\x00" * (limit - len(PNG) + 1), "image/png") \
            .expect.error(413, 41301)

    @allure.title("空文件 → 415 / 41501")
    def test_empty_file(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_A).upload(t["id"], "empty.txt", b"", "text/plain").expect.error(415, 41501)

    @allure.title("缺少 file 字段 → 400 / 40001")
    def test_missing_part(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_A).request("POST", f"/api/tickets/{t['id']}/attachments",
                                          files={"other": ("a.png", PNG, "image/png")}).expect.error(400, 40001)

    @allure.title("列表按上传顺序返回,两次上传两条")
    def test_list(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        agent = api.as_user(Users.AGENT_A)
        agent.upload(t["id"], "a.png", PNG, "image/png").expect.created()
        agent.upload(t["id"], "b.txt", TXT, "text/plain").expect.created()
        resp = agent.list_attachments(t["id"])
        resp.expect.ok().data().length(2)
        assert [a["originalName"] for a in resp.data] == ["a.png", "b.txt"]

    @allure.title("权限:写权限才能传(别的坐席 403),读权限才能看列表(组长可看)")
    def test_permissions(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_B).upload(t["id"], "a.png", PNG, "image/png").expect.error(403, 40301)
        api.as_user(Users.AGENT_B).list_attachments(t["id"]).expect.error(403, 40301)
        api.as_user(Users.LEADER_1).upload(t["id"], "a.png", PNG, "image/png").expect.created()
        api.as_user(Users.LEADER_1).list_attachments(t["id"]).expect.ok().data().length(1)
        api.as_user(Users.AGENT_C).list_attachments(t["id"]).expect.error(403, 40301)

    @allure.title("上传到不存在的工单 → 404 / 40401")
    def test_missing_ticket(self, api):
        api.upload(99999999, "a.png", PNG, "image/png").expect.error(404, 40401)
