package com.ticketqa.ticket;

import com.ticketqa.common.Result;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.ticket.dto.AssignRequest;
import com.ticketqa.ticket.dto.AuditLogVO;
import com.ticketqa.ticket.dto.CreateTicketRequest;
import com.ticketqa.ticket.dto.PageVO;
import com.ticketqa.ticket.dto.ReplyDraftVO;
import com.ticketqa.ticket.dto.TicketVO;
import com.ticketqa.ticket.dto.TransitionRequest;
import com.ticketqa.ticket.dto.UpdateTicketRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.http.HttpStatus;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 工单接口。Controller 只做三件事:绑定参数、触发校验(@Valid)、调用 Service。
 * 权限、状态机、事务都不在这一层——所以这里没有任何 if。
 *
 * @Validated 放在类上是为了让 @RequestParam 上的 @Min/@Max 生效(方法级校验走的是另一套 AOP)。
 */
@RestController
@RequestMapping("/api/tickets")
@Validated
public class TicketController {

    private final TicketService ticketService;

    public TicketController(TicketService ticketService) {
        this.ticketService = ticketService;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Result<TicketVO> create(@Valid @RequestBody CreateTicketRequest req) {
        return Result.ok(ticketService.create(req));
    }

    @GetMapping("/{id}")
    public Result<TicketVO> get(@PathVariable Long id) {
        return Result.ok(ticketService.get(id));
    }

    @GetMapping
    public Result<PageVO<TicketVO>> list(
            @RequestParam(required = false) TicketStatus status,
            @RequestParam(defaultValue = "1") @Min(1) long page,
            @RequestParam(defaultValue = "20") @Min(1) @Max(200) long size) {
        return Result.ok(ticketService.list(status, page, size));
    }

    @PutMapping("/{id}")
    public Result<TicketVO> update(@PathVariable Long id, @Valid @RequestBody UpdateTicketRequest req) {
        return Result.ok(ticketService.update(id, req));
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        ticketService.delete(id);
        return Result.ok();
    }

    @PostMapping("/{id}/transitions")
    public Result<TicketVO> transit(@PathVariable Long id, @Valid @RequestBody TransitionRequest req) {
        return Result.ok(ticketService.transit(id, req));
    }

    @PostMapping("/{id}/grab")
    public Result<TicketVO> grab(@PathVariable Long id) {
        return Result.ok(ticketService.grab(id));
    }

    @PostMapping("/{id}/assign")
    public Result<TicketVO> assign(@PathVariable Long id, @Valid @RequestBody AssignRequest req) {
        return Result.ok(ticketService.assign(id, req));
    }

    @GetMapping("/{id}/audit-logs")
    public Result<List<AuditLogVO>> auditLogs(@PathVariable Long id) {
        return Result.ok(ticketService.auditLogs(id));
    }

    @PostMapping("/{id}/reply-draft")
    public Result<ReplyDraftVO> replyDraft(@PathVariable Long id) {
        return Result.ok(ticketService.draftReply(id));
    }
}
