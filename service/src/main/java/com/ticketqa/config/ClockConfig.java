package com.ticketqa.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;
import java.time.ZoneId;

/**
 * 时间来源统一注入 Clock,而不是到处写 LocalDateTime.now()。
 * 好处:时区在配置里显式声明;单测里可以用 Clock.fixed(...) 把"现在"钉死,
 * SLA 闭区间边界(恰好等于时限)才能被精确测到。
 */
@Configuration
public class ClockConfig {

    @Bean
    public Clock clock(AppProperties props) {
        return Clock.system(ZoneId.of(props.timeZone()));
    }
}
