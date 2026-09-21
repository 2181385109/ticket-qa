package com.ticketqa.attachment;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 按文件头(魔数)识别真实类型,不信任扩展名和客户端声明的 Content-Type(ADR-008)。
 *
 *   jpg  FF D8 FF
 *   png  89 50 4E 47 0D 0A 1A 0A
 *   pdf  25 50 44 46  ("%PDF")
 *   txt  没有魔数:要求不含 NUL 字节、能按 UTF-8 解码、且不命中任何已知魔数
 */
public final class FileTypeSniffer {

    /** 扩展名 → 允许的声明 MIME(客户端 Content-Type 头) */
    public static final Map<String, String> EXT_TO_MIME = Map.of(
            "jpg", "image/jpeg",
            "png", "image/png",
            "pdf", "application/pdf",
            "txt", "text/plain");

    private record Magic(String ext, byte[] bytes) {
    }

    private static final List<Magic> MAGICS = List.of(
            new Magic("jpg", new byte[]{(byte) 0xFF, (byte) 0xD8, (byte) 0xFF}),
            new Magic("png", new byte[]{(byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A}),
            new Magic("pdf", new byte[]{0x25, 0x50, 0x44, 0x46}));

    private FileTypeSniffer() {
    }

    /**
     * @param head 文件前若干字节(至少 8 字节,越多对 txt 判断越准)
     * @return 识别出的扩展名(jpg/png/pdf/txt),识别不出返回 empty
     */
    public static Optional<String> sniff(byte[] head) {
        if (head == null || head.length == 0) {
            return Optional.empty();
        }
        for (Magic m : MAGICS) {
            if (startsWith(head, m.bytes())) {
                return Optional.of(m.ext());
            }
        }
        return looksLikeText(head) ? Optional.of("txt") : Optional.empty();
    }

    private static boolean startsWith(byte[] data, byte[] prefix) {
        if (data.length < prefix.length) {
            return false;
        }
        return Arrays.equals(data, 0, prefix.length, prefix, 0, prefix.length);
    }

    private static boolean looksLikeText(byte[] head) {
        for (byte b : head) {
            if (b == 0) {
                return false;
            }
        }
        try {
            // 严格解码:遇到非法 UTF-8 序列直接抛异常,而不是替换成 U+FFFD
            StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(trimIncompleteTail(head)));
            return true;
        } catch (CharacterCodingException e) {
            return false;
        }
    }

    /** 采样截断可能切在多字节字符中间,去掉末尾不完整的 UTF-8 序列再解码 */
    private static byte[] trimIncompleteTail(byte[] head) {
        int end = head.length;
        int back = 0;
        while (back < 3 && end - 1 - back >= 0 && (head[end - 1 - back] & 0xC0) == 0x80) {
            back++;
        }
        if (end - 1 - back >= 0 && (head[end - 1 - back] & 0xC0) == 0xC0) {
            end = end - 1 - back;
        }
        return Arrays.copyOf(head, end);
    }
}
