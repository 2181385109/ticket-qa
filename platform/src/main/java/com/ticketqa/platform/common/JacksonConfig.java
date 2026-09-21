package com.ticketqa.platform.common;

import com.fasterxml.jackson.datatype.jsr310.deser.LocalDateTimeDeserializer;
import com.fasterxml.jackson.datatype.jsr310.ser.LocalDateTimeSerializer;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * LocalDateTime 统一用 "yyyy-MM-dd HH:mm:ss" 收发:spring.jackson.date-format 只管 java.util.Date,
 * 对 java.time 不生效——导入脚本发 "2026-09-21 01:55:18" 会被默认的 ISO 解析器拒掉,和被测服务的 JacksonConfig 同一个理由。
 */
@Configuration
public class JacksonConfig {

    private static final DateTimeFormatter FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer localDateTimeFormat() {
        return builder -> builder
                .serializerByType(LocalDateTime.class, new LocalDateTimeSerializer(FORMAT))
                .deserializerByType(LocalDateTime.class, new LocalDateTimeDeserializer(FORMAT));
    }
}
