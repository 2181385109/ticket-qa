package com.ticketqa.platform;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * 质量数据平台入口。范围严格限定为三件事(ADR-022):执行记录入库、趋势、性能基线对比。
 * 没有用户 / 权限 / 用例管理 / 任务调度。
 */
@SpringBootApplication
@MapperScan("com.ticketqa.platform")
@ConfigurationPropertiesScan
public class PlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(PlatformApplication.class, args);
    }
}
