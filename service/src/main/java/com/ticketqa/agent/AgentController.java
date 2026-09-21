package com.ticketqa.agent;

import com.ticketqa.auth.CurrentUser;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/agents")
public class AgentController {

    /** 用于确认 X-User-Id 被正确解析:返回当前登录者。 */
    @GetMapping("/me")
    public Result<CurrentUser> me() {
        return Result.ok(UserContext.require());
    }
}
