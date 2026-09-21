package com.ticketqa.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.OptimisticLockerInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.apache.ibatis.reflection.MetaObject;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;
import java.time.LocalDateTime;

/**
 * MyBatis-Plus 装配:
 * 1. @MapperScan 让 mapper 包下的接口被生成代理对象并注册为 Bean(接口没有实现类,实现是运行时生成的);
 * 2. 分页插件:把 selectPage 改写成 LIMIT + COUNT 两条 SQL;
 * 3. 乐观锁插件:实体带 @Version 时,updateById 自动加 "AND version = ?" 并 SET version = ? + 1(ADR-016);
 *    插件顺序按 MP 官方建议:分页在前、乐观锁在后;
 * 4. MetaObjectHandler:插入 / 更新时自动填 created_at / updated_at,时间来自注入的 Clock。
 */
@Configuration
@MapperScan("com.ticketqa.mapper")
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
        return interceptor;
    }

    @Bean
    public MetaObjectHandler auditTimeFillHandler(Clock clock) {
        return new MetaObjectHandler() {
            @Override
            public void insertFill(MetaObject metaObject) {
                LocalDateTime now = LocalDateTime.now(clock);
                this.strictInsertFill(metaObject, "createdAt", LocalDateTime.class, now);
                this.strictInsertFill(metaObject, "updatedAt", LocalDateTime.class, now);
            }

            /**
             * 更新时无条件覆盖 updatedAt。strictUpdateFill 只在字段为 null 时才填,
             * 而 updateById 传进来的实体是从库里查出来的、updatedAt 已有值——联调时发现
             * 流转了五次 updated_at 还是创建时间,就是这个原因。
             */
            @Override
            public void updateFill(MetaObject metaObject) {
                this.setFieldValByName("updatedAt", LocalDateTime.now(clock), metaObject);
            }
        };
    }
}
