package com.ticketqa.attachment;

import com.ticketqa.domain.entity.TicketAttachment;

import java.time.LocalDateTime;

public record AttachmentVO(
        Long id,
        Long ticketId,
        String originalName,
        String storedName,
        String ext,
        String mimeType,
        Long sizeBytes,
        Long uploadedBy,
        LocalDateTime createdAt) {

    public static AttachmentVO from(TicketAttachment a) {
        return new AttachmentVO(a.getId(), a.getTicketId(), a.getOriginalName(), a.getStoredName(), a.getExt(),
                a.getMimeType(), a.getSizeBytes(), a.getUploadedBy(), a.getCreatedAt());
    }
}
