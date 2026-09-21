package com.ticketqa.attachment;

import com.ticketqa.common.Result;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/tickets/{ticketId}/attachments")
public class AttachmentController {

    private final AttachmentService attachmentService;

    public AttachmentController(AttachmentService attachmentService) {
        this.attachmentService = attachmentService;
    }

    /** multipart/form-data,表单字段名 file */
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @ResponseStatus(HttpStatus.CREATED)
    public Result<AttachmentVO> upload(@PathVariable Long ticketId, @RequestPart("file") MultipartFile file) {
        return Result.ok(attachmentService.upload(ticketId, file));
    }

    @GetMapping
    public Result<List<AttachmentVO>> list(@PathVariable Long ticketId) {
        return Result.ok(attachmentService.list(ticketId));
    }
}
