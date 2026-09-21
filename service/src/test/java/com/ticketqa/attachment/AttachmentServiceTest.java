package com.ticketqa.attachment;

import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.BizException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.config.AppProperties;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.entity.TicketAttachment;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.TicketAttachmentMapper;
import com.ticketqa.support.TestFixtures;
import com.ticketqa.ticket.TicketService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 附件三层校验(ADR-008)——等价类划分 + 边界值(docs/test-design/05)。
 *
 * 校验顺序:非空 → 大小 → 扩展名白名单 → 声明 MIME 与扩展名一致 → 魔数与扩展名一致 → UUID 重命名落盘。
 * 每一层一个无效等价类;大小取 5MB 整(允许)和 5MB + 1 字节(拒绝)两个边界点。
 * 路径穿越:原始文件名带 ../ 时,落盘文件名仍是 UUID,原始名只进数据库。
 *
 * 文件系统用 JUnit 的 @TempDir:每个测试一个临时目录,测试结束自动删掉。
 */
@ExtendWith(MockitoExtension.class)
class AttachmentServiceTest {

    private static final byte[] PNG_HEAD = {(byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    private static final byte[] JPG_HEAD = {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0};
    private static final long MAX = 5L * 1024 * 1024;

    @Mock
    private TicketAttachmentMapper attachmentMapper;
    @Mock
    private TicketService ticketService;
    @Mock
    private AccessChecker access;

    @TempDir
    Path tempDir;

    private AttachmentService service;

    @BeforeEach
    void setUp() throws IOException {
        UserContext.set(TestFixtures.agentA());
        AppProperties base = TestFixtures.appProperties();
        AppProperties props = new AppProperties(base.timeZone(), base.sla(), base.ticket(),
                new AppProperties.Attachment(tempDir.toString(), MAX, List.of("jpg", "png", "pdf", "txt")));
        service = new AttachmentService(attachmentMapper, ticketService, access, props);
        service.ensureDir();
        Ticket ticket = TestFixtures.ticket(1L, TicketStatus.ASSIGNED, 1L, 3L);
        lenient().when(ticketService.getOrThrow(1L)).thenReturn(ticket);
    }

    @AfterEach
    void tearDown() {
        UserContext.clear();
    }

    private static byte[] padded(byte[] head, int totalLength) {
        return Arrays.copyOf(head, totalLength);
    }

    private static MockMultipartFile file(String name, String contentType, byte[] content) {
        return new MockMultipartFile("file", name, contentType, content);
    }

    private ErrorCode codeOf(Runnable r) {
        try {
            r.run();
            return null;
        } catch (BizException e) {
            return e.getErrorCode();
        }
    }

    // ------------------------------------------------------------------ 合法

    @Test
    @DisplayName("合法 png:落盘为 UUID.png,数据库记录原始名 / 大小 / 上传者,返回 VO")
    void validPngStoredUnderUuid() throws IOException {
        byte[] content = padded(PNG_HEAD, 200);

        AttachmentVO vo = service.upload(1L, file("photo.PNG", "image/png", content));

        assertThat(vo.ext()).isEqualTo("png");
        assertThat(vo.originalName()).isEqualTo("photo.PNG");
        assertThat(vo.storedName()).matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.png");
        assertThat(vo.sizeBytes()).isEqualTo(200L);
        assertThat(vo.uploadedBy()).isEqualTo(3L);
        assertThat(vo.mimeType()).isEqualTo("image/png");
        assertThat(Files.readAllBytes(tempDir.resolve(vo.storedName()))).isEqualTo(content);

        ArgumentCaptor<TicketAttachment> captor = ArgumentCaptor.forClass(TicketAttachment.class);
        verify(attachmentMapper).insert(captor.capture());
        assertThat(captor.getValue().getTicketId()).isEqualTo(1L);
    }

    @Test
    @DisplayName("合法 txt:声明 text/plain; charset=UTF-8 也算一致(只比 type/subtype)")
    void validTxtWithCharsetParameter() {
        AttachmentVO vo = service.upload(1L, file("note.txt", "text/plain; charset=UTF-8", "中文文本".getBytes()));
        assertThat(vo.ext()).isEqualTo("txt");
    }

    // ------------------------------------------------------------------ 大小边界

    @Test
    @DisplayName("边界:恰好 5MB 允许(闭区间上界)")
    void exactlyMaxSizeAllowed() {
        AttachmentVO vo = service.upload(1L, file("big.png", "image/png", padded(PNG_HEAD, (int) MAX)));
        assertThat(vo.sizeBytes()).isEqualTo(MAX);
    }

    @Test
    @DisplayName("边界:5MB + 1 字节拒绝,41301,且不落盘")
    void oneByteOverMaxRejected() throws IOException {
        assertThat(codeOf(() -> service.upload(1L, file("big.png", "image/png", padded(PNG_HEAD, (int) MAX + 1)))))
                .isEqualTo(ErrorCode.ATTACHMENT_TOO_LARGE);
        try (Stream<Path> files = Files.list(tempDir)) {
            assertThat(files).isEmpty();
        }
        verify(attachmentMapper, never()).insert(any(TicketAttachment.class));
    }

    @Test
    @DisplayName("空文件:41501")
    void emptyFileRejected() {
        assertThat(codeOf(() -> service.upload(1L, file("empty.txt", "text/plain", new byte[0]))))
                .isEqualTo(ErrorCode.ATTACHMENT_EMPTY);
    }

    // ------------------------------------------------------------------ 三层绕过

    @Nested
    @DisplayName("绕过尝试:每一层各一个无效等价类")
    class Bypass {

        @ParameterizedTest(name = "[{index}] 文件名 {0} → 扩展名不在白名单")
        @CsvSource({"shell.php", "shell.jsp", "archive.tar.gz", "noext", "trailingdot.", "a.jpg.php", "photo.jpeg"})
        void extensionNotInWhitelist(String name) {
            assertThat(codeOf(() -> service.upload(1L, file(name, "image/jpeg", padded(JPG_HEAD, 64)))))
                    .isEqualTo(ErrorCode.ATTACHMENT_EXT_NOT_ALLOWED);
        }

        @Test
        @DisplayName("扩展名合法但声明 MIME 不匹配(application/octet-stream)→ 41503")
        void declaredMimeMismatch() {
            assertThat(codeOf(() -> service.upload(1L, file("photo.jpg", "application/octet-stream", padded(JPG_HEAD, 64)))))
                    .isEqualTo(ErrorCode.ATTACHMENT_MIME_MISMATCH);
        }

        @Test
        @DisplayName("扩展名 + 声明 MIME 都对,但内容是 PHP(魔数不符)→ 41503")
        void magicMismatchPhpAsJpg() {
            assertThat(codeOf(() -> service.upload(1L, file("shell.jpg", "image/jpeg", "<?php echo 1; ?>".getBytes()))))
                    .isEqualTo(ErrorCode.ATTACHMENT_MIME_MISMATCH);
        }

        @Test
        @DisplayName("png 内容改名成 .jpg(魔数是 png)→ 41503")
        void pngContentNamedJpg() {
            assertThat(codeOf(() -> service.upload(1L, file("x.jpg", "image/jpeg", padded(PNG_HEAD, 64)))))
                    .isEqualTo(ErrorCode.ATTACHMENT_MIME_MISMATCH);
        }

        @Test
        @DisplayName("二进制内容伪装成 .txt(含 NUL)→ 41503")
        void binaryAsTxt() {
            assertThat(codeOf(() -> service.upload(1L, file("x.txt", "text/plain", new byte[]{0x41, 0x00, 0x42}))))
                    .isEqualTo(ErrorCode.ATTACHMENT_MIME_MISMATCH);
        }

        @Test
        @DisplayName("没有声明 Content-Type → 与扩展名不符,41503(客户端必须显式声明,ADR-008)")
        void missingContentType() {
            assertThat(codeOf(() -> service.upload(1L, file("photo.png", null, padded(PNG_HEAD, 64)))))
                    .isEqualTo(ErrorCode.ATTACHMENT_MIME_MISMATCH);
        }

        @Test
        @DisplayName("路径穿越:原始名 ../../evil.png,落盘名仍是 UUID,文件只出现在附件目录内")
        void pathTraversalNeutralised() throws IOException {
            AttachmentVO vo = service.upload(1L, file("../../evil.png", "image/png", padded(PNG_HEAD, 64)));

            assertThat(vo.storedName()).doesNotContain("..").doesNotContain("/").doesNotContain("\\");
            assertThat(vo.originalName()).isEqualTo("../../evil.png");
            assertThat(Files.exists(tempDir.resolve(vo.storedName()))).isTrue();
            assertThat(Files.exists(tempDir.getParent().getParent().resolve("evil.png"))).isFalse();
        }

        @Test
        @DisplayName("Windows 风格路径穿越:..\\..\\evil.png 同样只按最后一个点取扩展名")
        void windowsPathTraversalNeutralised() {
            AttachmentVO vo = service.upload(1L, file("..\\..\\evil.png", "image/png", padded(PNG_HEAD, 64)));
            assertThat(vo.ext()).isEqualTo("png");
            assertThat(vo.storedName()).doesNotContain("..");
        }
    }

    // ------------------------------------------------------------------ 校验顺序

    @Test
    @DisplayName("校验顺序:大小先于扩展名(超大的 .php 报 41301 而不是 41502)")
    void sizeCheckedBeforeExtension() {
        assertThat(codeOf(() -> service.upload(1L, file("big.php", "application/x-php", new byte[(int) MAX + 1]))))
                .isEqualTo(ErrorCode.ATTACHMENT_TOO_LARGE);
    }

    @Test
    @DisplayName("权限先于一切:无权写工单时不做任何文件校验")
    void accessCheckedFirst() {
        org.mockito.Mockito.doThrow(new com.ticketqa.common.AccessDeniedException(ErrorCode.FORBIDDEN, "无权"))
                .when(access).checkWrite(any(), any());
        assertThat(codeOf(() -> service.upload(1L, file("shell.php", "x", new byte[0]))))
                .isEqualTo(ErrorCode.FORBIDDEN);
    }

    // ------------------------------------------------------------------ 纯函数

    @ParameterizedTest(name = "[{index}] extensionOf({0}) = {1}")
    @CsvSource({"photo.JPG, jpg", "archive.tar.gz, gz", "noext, ''", "trailing., ''", "'a.b.c.PDF ', pdf", ".hidden, hidden"})
    void extensionOf(String filename, String expected) {
        assertThat(AttachmentService.extensionOf(filename)).isEqualTo(expected);
    }

    @ParameterizedTest(name = "[{index}] normalizeMime({0}) = {1}")
    @CsvSource({"'text/plain; charset=UTF-8', text/plain", "IMAGE/PNG, image/png", "'', ''", "garbage, garbage"})
    void normalizeMime(String contentType, String expected) {
        assertThat(AttachmentService.normalizeMime(contentType)).isEqualTo(expected);
    }
}
