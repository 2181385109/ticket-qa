package com.ticketqa;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 入口。@SpringBootApplication = @Configuration + @EnableAutoConfiguration + @ComponentScan,
 * 扫描范围是本类所在包 com.ticketqa 及其子包。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
@EnableCaching
@EnableScheduling
public class TicketQaApplication {

    public static void main(String[] args) {
        SpringApplication.run(TicketQaApplication.class, args);
    }
}
