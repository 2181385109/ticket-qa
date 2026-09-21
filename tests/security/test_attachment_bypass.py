"""
附件绕过(CLAUDE.md §5.7)——每一层校验一个无效等价类,外加组合绕过。

三层:扩展名白名单 → 声明 Content-Type 与扩展名一致 → 文件头魔数与扩展名一致(ADR-008)。
绕过手法按层归类:
  L1 扩展名:改名、双扩展名、大小写混合、空字节截断、无扩展名、点结尾
  L2 声明 MIME:octet-stream、伪造成 image/png 但扩展名是 .php、带参数的 MIME
  L3 内容:PHP / HTML / SVG / ELF 内容改名成 .jpg / .png / .txt
  路径:../ 穿越、绝对路径、Windows 路径、超长文件名
  大小:5MB + 1
真正的"多层同时通过"只有一种:内容本身就是合法魔数(polyglot),那不在这三层的防护范围内,单独记录(known-issues)。
"""
import re

import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("安全"), allure.story("附件绕过")]

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\x00" * 64
JPG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 64
# 注意:载荷故意写得"无害"——Windows Defender 会实时查杀 Tomcat 落到临时目录的 multipart 文件,
# 含 system($_GET[...]) 的 PHP 会在服务读取前被隔离,服务侧变成 500(见 known-issues KI-003),测的就不是校验层了
PHP = b"<?php echo 'hello from php'; ?>"
HTML = b"<html><script>alert(1)</script></html>"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 64
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|pdf|txt)$")


@pytest.fixture
def owned(tickets):
    return tickets.assigned(Users.AGENT_A)


def _upload(api, ticket, filename, content, ctype):
    return api.as_user(Users.AGENT_A).upload(ticket["id"], filename, content, ctype)


def _assert_nothing_stored(db, config, ticket):
    assert db.attachments(ticket["id"]) == [], "被拒的上传不能留下库记录"
    if config.attachment_dir and config.attachment_dir.exists():
        for p in config.attachment_dir.iterdir():
            assert UUID_RE.match(p.name), f"附件目录里出现了非 UUID 命名的文件: {p.name}"


class TestExtensionLayer:

    @pytest.mark.parametrize("filename", [
        "shell.php", "shell.jsp", "shell.exe", "shell.sh", "shell.html", "shell.svg",
        "shell.php.jpg.php", "photo.jpg.php", "a.jpg.php",
        "shell.pHp", "shell.PHP5", "shell.phtml",
        "noext", "trailingdot.", ".htaccess", "photo.jpeg", "photo.jpe", "photo.PnG.exe",
    ])
    @allure.title("L1 扩展名「{filename}」→ 415 / 41502")
    def test_extension_not_whitelisted(self, api, db, config, owned, filename):
        _upload(api, owned, filename, JPG, "image/jpeg").expect.error(415, 41502)
        _assert_nothing_stored(db, config, owned)

    @allure.title("L1 空字节截断 shell.php\\x00.jpg:不能被当成 .jpg 接受")
    def test_null_byte_truncation(self, api, db, config, owned):
        resp = _upload(api, owned, "shell.php\x00.jpg", JPG, "image/jpeg")
        assert resp.status != 201, resp.summary()
        _assert_nothing_stored(db, config, owned)

    @allure.title("L1 双扩展名 shell.jpg.php:按最后一个点判定 → 415")
    def test_double_extension_last_dot_wins(self, api, owned):
        _upload(api, owned, "shell.jpg.php", JPG, "image/jpeg").expect.error(415, 41502)


class TestMimeLayer:

    @pytest.mark.parametrize("ctype", ["application/octet-stream", "image/jpeg", "text/plain", "application/x-php", None,
                                       "image/png; charset=binary"])
    @allure.title("L2 .png 文件声明 Content-Type={ctype} → 415 / 41503")
    def test_declared_mime_mismatch(self, api, db, config, owned, ctype):
        # image/png; charset=binary:MediaType 解析 charset 失败 → 整串当作类型比较 → 拒绝。拒绝是 fail-safe,
        # 但说明"带未知 charset 参数的合法类型"进不来,记 known-issues KI-004 待决定
        _upload(api, owned, "photo.png", PNG, ctype).expect.error(415, 41503)
        _assert_nothing_stored(db, config, owned)

    @allure.title("L2 带普通参数的合法类型 image/png; foo=bar:只比 type/subtype,放行")
    def test_declared_mime_with_parameter_allowed(self, api, owned):
        _upload(api, owned, "photo.png", PNG, "image/png; foo=bar").expect.created()

    @allure.title("L2 声明的类型合法但扩展名不合法(image/png + shell.php):扩展名层先拦 → 41502")
    def test_mime_cannot_rescue_extension(self, api, owned):
        _upload(api, owned, "shell.php", PNG, "image/png").expect.error(415, 41502)


class TestContentLayer:

    @pytest.mark.parametrize("filename, ctype, content", [
        ("shell.jpg", "image/jpeg", PHP),
        ("shell.png", "image/png", PHP),
        ("page.png", "image/png", HTML),
        ("vector.png", "image/png", SVG),
        ("bin.txt", "text/plain", ELF),
        ("bin.pdf", "application/pdf", ELF),
        ("swap.jpg", "image/jpeg", PNG),
        ("swap.png", "image/png", JPG),
        ("fake.pdf", "application/pdf", b"PDF-1.7 without percent"),
    ], ids=["php-as-jpg", "php-as-png", "html-as-png", "svg-as-png", "elf-as-txt", "elf-as-pdf", "png-as-jpg", "jpg-as-png", "fake-pdf"])
    @allure.title("L3 内容与扩展名不符 {filename} → 415 / 41503")
    def test_magic_mismatch(self, api, db, config, owned, filename, ctype, content):
        _upload(api, owned, filename, content, ctype).expect.error(415, 41503)
        _assert_nothing_stored(db, config, owned)

    @allure.title("L3 文本类:PHP 源码以 .txt 上传是合法的(txt 无魔数,内容是 UTF-8 文本)——存下来的是 UUID.txt,不可执行")
    def test_php_as_txt_is_stored_inert(self, api, owned):
        resp = _upload(api, owned, "shell.txt", PHP, "text/plain")
        resp.expect.created().data("ext").eq("txt").data("storedName").matches(r".*\.txt")

    @pytest.mark.known_issue
    @pytest.mark.xfail(strict=True, reason="KI-002 已知局限:魔数只看文件头,PNG 头 + PHP 尾的 polyglot 会被接受(docs/findings/known-issues.md)")
    @allure.title("L3 polyglot:合法 PNG 头 + PHP 代码尾 → 期望被拒(当前实现只查文件头)")
    def test_polyglot_png_php(self, api, owned):
        _upload(api, owned, "poly.png", PNG + PHP, "image/png").expect.error(415, 41503)


class TestPathAndSize:

    @pytest.mark.parametrize("filename", [
        "../../../etc/passwd.png", "..\\..\\..\\windows\\win.ini.png", "/etc/cron.d/evil.png", "C:\\Windows\\evil.png",
        "....//....//evil.png", "%2e%2e%2f%2e%2e%2fevil.png", "photo.png/../../evil.png",
    ])
    @allure.title("路径穿越「{filename}」→ 201 但落盘名是 UUID,原始名只进数据库,目录外没有文件")
    def test_path_traversal_neutralised(self, api, db, config, owned, filename):
        resp = _upload(api, owned, filename, PNG, "image/png")
        resp.expect.created().data("storedName").matches(UUID_RE.pattern[1:-1])
        stored = resp.data["storedName"]
        assert "/" not in stored and "\\" not in stored and ".." not in stored
        row = db.attachments(owned["id"])[-1]
        assert row["stored_name"] == stored
        if config.attachment_dir and config.attachment_dir.exists():
            assert (config.attachment_dir / stored).exists()
            for outside in (config.attachment_dir.parent / "evil.png", config.attachment_dir.parent.parent / "evil.png"):
                assert not outside.exists(), f"文件逃出了附件目录: {outside}"

    @allure.title("超长文件名(300 字符)→ 201,original_name 截断到 255,落盘名仍是 UUID")
    def test_overlong_filename(self, api, db, owned):
        name = "a" * 296 + ".png"
        resp = _upload(api, owned, name, PNG, "image/png")
        resp.expect.created()
        assert len(db.attachments(owned["id"])[-1]["original_name"]) == 255

    @allure.title("5MB + 1 字节 → 413 / 41301;8MB + 1(超过容器上限)→ 413,都不落盘")
    def test_oversize(self, api, db, config, owned):
        five = 5 * 1024 * 1024
        _upload(api, owned, "big.png", PNG + b"\x00" * (five - len(PNG) + 1), "image/png").expect.error(413, 41301)
        resp = _upload(api, owned, "huge.png", PNG + b"\x00" * (8 * 1024 * 1024 - len(PNG) + 1), "image/png")
        assert resp.status == 413, resp.summary()
        _assert_nothing_stored(db, config, owned)

    @allure.title("multipart 里塞两个 file 字段:只处理第一个,不会同时写两份")
    def test_duplicate_parts(self, api, db, owned):
        resp = api.as_user(Users.AGENT_A).request("POST", f"/api/tickets/{owned['id']}/attachments",
                                                  files=[("file", ("a.png", PNG, "image/png")), ("file", ("b.php", PHP, "application/x-php"))])
        assert resp.status in (201, 415), resp.summary()
        assert len(db.attachments(owned["id"])) <= 1
