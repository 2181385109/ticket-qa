package com.ticketqa.support;

import com.baomidou.mybatisplus.test.autoconfigure.MybatisPlusTest;
import com.ticketqa.config.MybatisPlusConfig;
import org.springframework.boot.jdbc.EmbeddedDatabaseConnection;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.time.Clock;

/**
 * 持久层切片测试的组合注解(ADR-013)。
 *
 * @MybatisPlusTest 只装配 DataSource + SqlSessionFactory + Mapper,不起 Web、Redis、RabbitMQ,
 * 启动约 1 秒。数据库换成内存 H2 的 MySQL 兼容模式,建表脚本 test/resources/h2/schema.sql。
 *
 * 为什么要 @Import(MybatisPlusConfig):项目的 Mapper 接口没有加 @Mapper 注解,靠 @MapperScan 注册;
 * 切片默认不扫 @Configuration,所以要手动把带 @MapperScan 的配置类带进来。
 * 它又依赖一个 Clock Bean(自动填 created_at / updated_at),这里给一个钉死的 Clock。
 *
 * Java 语法:这是一个"元注解"——把四个注解打包成一个,用法和 Python 里把多个装饰器叠成一个是一回事。
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@MybatisPlusTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE, connection = EmbeddedDatabaseConnection.H2)
@Import({MybatisPlusConfig.class, H2SliceTest.FixedClockConfig.class})
@TestPropertySource(properties = {
        "spring.datasource.url=jdbc:h2:mem:ticketqa;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.sql.init.mode=always",
        "spring.sql.init.schema-locations=classpath:h2/schema.sql",
        "logging.file.name=./target/test-slice.log"
})
public @interface H2SliceTest {

    @TestConfiguration
    class FixedClockConfig {
        @Bean
        public Clock clock() {
            return TestFixtures.fixedClock();
        }
    }
}
