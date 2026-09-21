package com.ticketqa.attachment;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 魔数识别——等价类划分(docs/test-design/05-附件等价类划分.md)。
 *
 * 有效类:jpg 头 / png 头 / pdf 头 / 纯文本(UTF-8、无 NUL)
 * 无效类:空 / 含 NUL 的二进制 / 非法 UTF-8 / 已知魔数但扩展名对不上(在 AttachmentServiceTest 里测)
 * 边界:只有 2 字节的 jpg 头(不够长)、多字节字符被采样截断在中间
 */
class FileTypeSnifferTest {

    private static byte[] bytes(int... values) {
        byte[] b = new byte[values.length];
        for (int i = 0; i < values.length; i++) {
            b[i] = (byte) values[i];
        }
        return b;
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }

    @Test
    @DisplayName("jpg:FF D8 FF")
    void jpg() {
        assertThat(FileTypeSniffer.sniff(concat(bytes(0xFF, 0xD8, 0xFF, 0xE0), new byte[16]))).contains("jpg");
    }

    @Test
    @DisplayName("png:89 50 4E 47 0D 0A 1A 0A")
    void png() {
        assertThat(FileTypeSniffer.sniff(concat(bytes(0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A), new byte[16]))).contains("png");
    }

    @Test
    @DisplayName("pdf:%PDF")
    void pdf() {
        assertThat(FileTypeSniffer.sniff("%PDF-1.7\n%âãÏÓ".getBytes(StandardCharsets.ISO_8859_1))).contains("pdf");
    }

    @Test
    @DisplayName("txt:UTF-8 中文文本,没有魔数、没有 NUL")
    void utf8Text() {
        assertThat(FileTypeSniffer.sniff("这是一段中文文本\nline 2".getBytes(StandardCharsets.UTF_8))).contains("txt");
    }

    @Test
    @DisplayName("PHP 源码在魔数层面就是文本:识别为 txt(挡它的是扩展名白名单,不是魔数)")
    void phpSourceLooksLikeText() {
        assertThat(FileTypeSniffer.sniff("<?php echo 1; ?>".getBytes(StandardCharsets.UTF_8))).contains("txt");
    }

    @Test
    @DisplayName("含 NUL 字节的内容不是文本:识别不出")
    void nulByteIsNotText() {
        assertThat(FileTypeSniffer.sniff(bytes(0x41, 0x00, 0x42))).isEmpty();
    }

    @Test
    @DisplayName("非法 UTF-8 序列不是文本(GBK 编码的中文会落到这里)")
    void invalidUtf8IsNotText() {
        byte[] gbk = "中文".getBytes(java.nio.charset.Charset.forName("GBK"));
        assertThat(FileTypeSniffer.sniff(gbk)).isEmpty();
    }

    @Test
    @DisplayName("空 / null:识别不出")
    void emptyAndNull() {
        assertThat(FileTypeSniffer.sniff(new byte[0])).isEmpty();
        assertThat(FileTypeSniffer.sniff(null)).isEmpty();
    }

    @Test
    @DisplayName("边界:jpg 头只有 2 字节(FF D8)不算 jpg,按文本规则也不算(FF 不是合法 UTF-8 起始字节)")
    void truncatedMagicIsNotRecognised() {
        assertThat(FileTypeSniffer.sniff(bytes(0xFF, 0xD8))).isEmpty();
    }

    @Test
    @DisplayName("边界:8KB 采样恰好切在多字节字符中间,尾部不完整序列被去掉,仍识别为 txt")
    void sampleCutInsideMultibyteChar() {
        byte[] full = "字".getBytes(StandardCharsets.UTF_8);          // 3 字节 E5 AD 97
        byte[] cut = concat("abc".getBytes(StandardCharsets.UTF_8), Arrays.copyOf(full, 2));   // 只剩前 2 字节
        assertThat(FileTypeSniffer.sniff(cut)).contains("txt");
    }

    @Test
    @DisplayName("扩展名到声明 MIME 的映射覆盖且仅覆盖白名单四种")
    void extToMimeCoversWhitelist() {
        assertThat(FileTypeSniffer.EXT_TO_MIME).containsOnlyKeys("jpg", "png", "pdf", "txt");
        assertThat(FileTypeSniffer.EXT_TO_MIME).containsEntry("jpg", "image/jpeg");
    }
}
