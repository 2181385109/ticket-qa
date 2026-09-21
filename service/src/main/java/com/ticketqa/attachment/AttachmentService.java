package com.ticketqa.attachment;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.CurrentUser;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.BizException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.config.AppProperties;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.entity.TicketAttachment;
import com.ticketqa.mapper.TicketAttachmentMapper;
import com.ticketqa.ticket.TicketService;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;

/**
 * 附件上传(CLAUDE.md §5.7)。三层校验,顺序从便宜到贵:
 *   1. 大小 ≤ 5MB(闭区间,恰好 5MB 允许)、非空
 *   2. 扩展名在白名单 jpg/png/pdf/txt(取最后一个点之后、小写)
 *   3. 客户端声明的 Content-Type 与扩展名一致
 *   4. 文件头魔数与扩展名一致(FileTypeSniffer)——这一层才是真正防绕过的
 * 通过后重命名为 UUID + 扩展名落盘;原始文件名只进数据库,永远不参与路径拼接。
 */
@Service
public class AttachmentService {

    private static final Logger log = LoggerFactory.getLogger(AttachmentService.class);
    private static final int SNIFF_BYTES = 8192;

    private final TicketAttachmentMapper attachmentMapper;
    private final TicketService ticketService;
    private final AccessChecker access;
    private final AppProperties props;
    private Path baseDir;

    public AttachmentService(TicketAttachmentMapper attachmentMapper, TicketService ticketService,
                            AccessChecker access, AppProperties props) {
        this.attachmentMapper = attachmentMapper;
        this.ticketService = ticketService;
        this.access = access;
        this.props = props;
    }

    /** @PostConstruct:依赖注入完成后、Bean 投入使用前执行一次。这里确保上传目录存在。 */
    @PostConstruct
    void ensureDir() throws IOException {
        baseDir = Paths.get(props.attachment().dir()).toAbsolutePath().normalize();
        Files.createDirectories(baseDir);
        log.info("附件目录 {}", baseDir);
    }

    @Transactional(rollbackFor = Exception.class)
    public AttachmentVO upload(Long ticketId, MultipartFile file) {
        CurrentUser user = UserContext.require();
        Ticket ticket = ticketService.getOrThrow(ticketId);
        access.checkWrite(user, ticket);

        if (file == null || file.isEmpty()) {
            throw new BizException(ErrorCode.ATTACHMENT_EMPTY);
        }
        if (file.getSize() > props.attachment().maxSizeBytes()) {
            throw new BizException(ErrorCode.ATTACHMENT_TOO_LARGE,
                    "附件 " + file.getSize() + " 字节,上限 " + props.attachment().maxSizeBytes());
        }
        String originalName = Optional.ofNullable(file.getOriginalFilename()).orElse("");
        String ext = extensionOf(originalName);
        if (!props.attachment().allowedExt().contains(ext)) {
            throw new BizException(ErrorCode.ATTACHMENT_EXT_NOT_ALLOWED,
                    "扩展名 '" + ext + "' 不在白名单 " + props.attachment().allowedExt());
        }
        String expectedMime = FileTypeSniffer.EXT_TO_MIME.get(ext);
        String declared = normalizeMime(file.getContentType());
        if (!expectedMime.equals(declared)) {
            throw new BizException(ErrorCode.ATTACHMENT_MIME_MISMATCH,
                    "声明的 Content-Type '" + file.getContentType() + "' 与扩展名 ." + ext + " 不符,应为 " + expectedMime);
        }
        String sniffed = FileTypeSniffer.sniff(readHead(file)).orElse("unknown");
        if (!ext.equals(sniffed)) {
            throw new BizException(ErrorCode.ATTACHMENT_MIME_MISMATCH,
                    "文件内容识别为 " + sniffed + ",与扩展名 ." + ext + " 不符");
        }

        String storedName = UUID.randomUUID() + "." + ext;
        Path target = baseDir.resolve(storedName);
        // try-with-resources:无论 copy 成功还是抛异常,InputStream 都会被关闭
        try (InputStream in = file.getInputStream()) {
            Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            throw new UncheckedIOException("附件写入失败", e);
        }

        TicketAttachment row = new TicketAttachment();
        row.setTicketId(ticketId);
        row.setOriginalName(originalName.length() > 255 ? originalName.substring(0, 255) : originalName);
        row.setStoredName(storedName);
        row.setExt(ext);
        row.setMimeType(expectedMime);
        row.setSizeBytes(file.getSize());
        row.setUploadedBy(user.id());
        attachmentMapper.insert(row);
        log.info("附件上传 ticketId={} stored={} size={} by={}", ticketId, storedName, file.getSize(), user.id());
        return AttachmentVO.from(row);
    }

    public List<AttachmentVO> list(Long ticketId) {
        CurrentUser user = UserContext.require();
        Ticket ticket = ticketService.getOrThrow(ticketId);
        access.checkRead(user, ticket);
        return attachmentMapper.selectList(new LambdaQueryWrapper<TicketAttachment>()
                        .eq(TicketAttachment::getTicketId, ticketId)
                        .orderByAsc(TicketAttachment::getId))
                .stream().map(AttachmentVO::from).toList();
    }

    // ------------------------------------------------------------------ 内部

    /** "photo.JPG" → "jpg";"archive.tar.gz" → "gz";"noext" → "" */
    static String extensionOf(String filename) {
        int dot = filename.lastIndexOf('.');
        if (dot < 0 || dot == filename.length() - 1) {
            return "";
        }
        return filename.substring(dot + 1).toLowerCase(Locale.ROOT).trim();
    }

    /** "text/plain; charset=UTF-8" → "text/plain";空 → "" */
    static String normalizeMime(String contentType) {
        if (contentType == null || contentType.isBlank()) {
            return "";
        }
        try {
            MediaType mt = MediaType.parseMediaType(contentType);
            return (mt.getType() + "/" + mt.getSubtype()).toLowerCase(Locale.ROOT);
        } catch (RuntimeException e) {
            return contentType.toLowerCase(Locale.ROOT).trim();
        }
    }

    private static byte[] readHead(MultipartFile file) {
        try (InputStream in = file.getInputStream()) {
            return in.readNBytes(SNIFF_BYTES);
        } catch (IOException e) {
            throw new UncheckedIOException("读取附件头失败", e);
        }
    }
}
