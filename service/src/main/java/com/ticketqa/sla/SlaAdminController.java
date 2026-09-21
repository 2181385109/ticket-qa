package com.ticketqa.sla;

import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.Result;
import com.ticketqa.domain.enums.Role;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 管理接口:手动触发一轮 SLA 扫描(ADMIN)。
 * 联调和接口测试用它代替"等 30 秒定时器",测试用例的执行时间和定时器周期解耦。
 */
@RestController
@RequestMapping("/api/admin/sla")
public class SlaAdminController {

    private final SlaScanner scanner;
    private final AccessChecker access;

    public SlaAdminController(SlaScanner scanner, AccessChecker access) {
        this.scanner = scanner;
        this.access = access;
    }

    @PostMapping("/scan")
    public Result<Map<String, Integer>> scan() {
        access.requireRole(UserContext.require(), Role.ADMIN);
        int escalated = scanner.scanOnce();
        return Result.ok(Map.of("escalated", escalated));
    }
}
