package com.ticketqa.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.jsontype.BasicPolymorphicTypeValidator;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.cache.RedisCacheManagerBuilderCustomizer;
import org.springframework.cache.Cache;
import org.springframework.cache.annotation.CachingConfigurer;
import org.springframework.cache.interceptor.CacheErrorHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;

import java.time.Duration;

/**
 * Spring Cache 落 Redis 时的两项定制:
 *
 * 1. 序列化:默认是 JDK 序列化(二进制不可读,改类就反序列化失败),换成 JSON 并带类型信息(@class 字段),
 *    redis-cli 里能直接看懂缓存内容。
 * 2. 错误处理:默认 Redis 异常会从 @Cacheable 冒出来变成 500——那意味着 Redis 一挂鉴权就挂。
 *    这里把缓存异常降级为"未命中":打 WARN、直接查库。缓存是加速器,不是依赖(故障注入 docker stop redis 时可观察)。
 */
@Configuration
public class CacheConfig implements CachingConfigurer {

    private static final Logger log = LoggerFactory.getLogger(CacheConfig.class);
    public static final String CACHE_AGENTS = "agents";

    @Bean
    public RedisCacheManagerBuilderCustomizer cacheManagerCustomizer() {
        ObjectMapper mapper = new ObjectMapper()
                .registerModule(new JavaTimeModule())
                .activateDefaultTyping(
                        BasicPolymorphicTypeValidator.builder().allowIfSubType("com.ticketqa.").build(),
                        ObjectMapper.DefaultTyping.NON_FINAL);
        GenericJackson2JsonRedisSerializer serializer = new GenericJackson2JsonRedisSerializer(mapper);
        RedisCacheConfiguration base = RedisCacheConfiguration.defaultCacheConfig()
                .serializeValuesWith(RedisSerializationContext.SerializationPair.fromSerializer(serializer))
                .prefixCacheNameWith("ticketqa:cache:")
                .disableCachingNullValues();
        return builder -> builder
                .cacheDefaults(base.entryTtl(Duration.ofMinutes(10)))
                .withCacheConfiguration(CACHE_AGENTS, base.entryTtl(Duration.ofMinutes(10)));
    }

    /** 缓存读写失败 → 记日志、当作未命中,不让 Redis 故障传染到业务。 */
    @Override
    public CacheErrorHandler errorHandler() {
        return new CacheErrorHandler() {
            @Override
            public void handleCacheGetError(RuntimeException e, Cache cache, Object key) {
                log.warn("缓存读取失败,回源查库 cache={} key={} err={}", cache.getName(), key, e.getMessage());
            }

            @Override
            public void handleCachePutError(RuntimeException e, Cache cache, Object key, Object value) {
                log.warn("缓存写入失败,忽略 cache={} key={} err={}", cache.getName(), key, e.getMessage());
            }

            @Override
            public void handleCacheEvictError(RuntimeException e, Cache cache, Object key) {
                log.warn("缓存删除失败,忽略 cache={} key={} err={}", cache.getName(), key, e.getMessage());
            }

            @Override
            public void handleCacheClearError(RuntimeException e, Cache cache) {
                log.warn("缓存清空失败,忽略 cache={} err={}", cache.getName(), e.getMessage());
            }
        };
    }
}
