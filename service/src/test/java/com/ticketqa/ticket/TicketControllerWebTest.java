package com.ticketqa.ticket;

import com.ticketqa.agent.AgentService;
import com.ticketqa.common.AccessDeniedException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.common.NotFoundException;
import com.ticketqa.config.JacksonConfig;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.support.TestFixtures;
import com.ticketqa.ticket.dto.TicketVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.notNullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Web 层切片(ADR-013):只起 DispatcherServlet + Controller + ControllerAdvice + 拦截器 + 过滤器,
 * Service 用 @MockBean 替掉,不连数据库。测的是"HTTP 边界上的翻译是否正确":
 *   - 认证拦截器:没有 / 无效 X-User-Id → 401 + 40101
 *   - Bean Validation:@Valid 请求体、@Min 查询参数 → 400 + 40001,message 指出字段
 *   - 异常 → 状态码 / 错误码 的映射(409 / 403 / 404 / 500)
 *   - 统一返回体 Result{code,message,data,traceId} 与 X-Trace-Id 响应头
 *
 * 等价类:每一类异常各取一个代表;错误码前三位 == HTTP 状态是断言的依据(ErrorCode 的约定)。
 */
@WebMvcTest(TicketController.class)
@Import(JacksonConfig.class)
@TestPropertySource(properties = "logging.file.name=./target/test-web.log")
class TicketControllerWebTest {

    @Autowired
    private MockMvc mvc;

    @MockBean
    private TicketService ticketService;
    @MockBean
    private AgentService agentService;

    @BeforeEach
    void setUp() {
        when(agentService.findCurrentUser(3L)).thenReturn(Optional.of(TestFixtures.agentA()));
        when(agentService.findCurrentUser(999L)).thenReturn(Optional.empty());
    }

    private static TicketVO sampleVO() {
        return new TicketVO(1L, "T20260920-ABCD1234", "申请退款", "内容", TicketCategory.REFUND, TicketPriority.P1,
                TicketStatus.PENDING, 1001L, 1L, null, TestFixtures.NOW.plusMinutes(60), null, null, 0,
                TestFixtures.NOW, TestFixtures.NOW);
    }

    @Nested
    @DisplayName("认证拦截器")
    class Auth {

        @Test
        @DisplayName("没有 X-User-Id → 401 / 40101,响应仍是统一格式且带 traceId")
        void missingHeader() throws Exception {
            mvc.perform(get("/api/tickets/1"))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.code").value(40101))
                    .andExpect(jsonPath("$.traceId", notNullValue()))
                    .andExpect(header().exists("X-Trace-Id"));
        }

        @Test
        @DisplayName("X-User-Id 不是数字 → 401")
        void nonNumericHeader() throws Exception {
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "abc"))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.code").value(40101));
        }

        @Test
        @DisplayName("X-User-Id 指向不存在 / 停用的坐席 → 401")
        void unknownUser() throws Exception {
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "999"))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.code").value(40101));
        }

        @Test
        @DisplayName("Actuator 不在拦截范围:/actuator/** 不需要 X-User-Id(这里只验证拦截器路径,端点由 CI 里的服务验证)")
        void actuatorNotIntercepted() throws Exception {
            // 切片里没有 actuator 端点,404 即可说明拦截器没有先给 401
            mvc.perform(get("/actuator/health")).andExpect(status().isNotFound());
        }
    }

    @Nested
    @DisplayName("参数校验")
    class Validation {

        @Test
        @DisplayName("标题为空 → 400 / 40001,message 指出 title")
        void blankTitle() throws Exception {
            mvc.perform(post("/api/tickets").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"title\":\"\",\"content\":\"x\",\"customerId\":1}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001))
                    .andExpect(jsonPath("$.message", containsString("title")));
        }

        @Test
        @DisplayName("customerId 为负数 → 400,message 指出 customerId")
        void negativeCustomerId() throws Exception {
            mvc.perform(post("/api/tickets").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"title\":\"t\",\"content\":\"x\",\"customerId\":-1}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.message", containsString("customerId")));
        }

        @Test
        @DisplayName("标题 201 字 → 400(@Size 上界 200)")
        void titleTooLong() throws Exception {
            String title = "标".repeat(201);
            mvc.perform(post("/api/tickets").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"title\":\"" + title + "\",\"content\":\"x\",\"customerId\":1}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }

        @Test
        @DisplayName("请求体不是 JSON → 400 / 40001")
        void malformedJson() throws Exception {
            mvc.perform(post("/api/tickets").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{not json"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }

        @Test
        @DisplayName("target 不是合法枚举 → 400(反序列化失败也归 40001)")
        void invalidEnumInBody() throws Exception {
            mvc.perform(post("/api/tickets/1/transitions").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"target\":\"DONE\"}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }

        @Test
        @DisplayName("page=0 → 400(@Min(1) 查询参数,类上 @Validated 生效)")
        void pageZero() throws Exception {
            mvc.perform(get("/api/tickets").param("page", "0").header("X-User-Id", "3"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }

        @Test
        @DisplayName("size=201 → 400(@Max(200))")
        void sizeTooLarge() throws Exception {
            mvc.perform(get("/api/tickets").param("size", "201").header("X-User-Id", "3"))
                    .andExpect(status().isBadRequest());
        }

        @Test
        @DisplayName("status=FOO → 400(枚举转换失败)")
        void invalidStatusParam() throws Exception {
            mvc.perform(get("/api/tickets").param("status", "FOO").header("X-User-Id", "3"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }

        @Test
        @DisplayName("路径参数不是数字 → 400")
        void nonNumericPathVariable() throws Exception {
            mvc.perform(get("/api/tickets/abc").header("X-User-Id", "3"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value(40001));
        }
    }

    @Nested
    @DisplayName("异常 → HTTP 状态 / 错误码")
    class ExceptionMapping {

        @Test
        @DisplayName("IllegalTransitionException → 409 / 40901")
        void illegalTransition() throws Exception {
            when(ticketService.transit(eq(1L), any()))
                    .thenThrow(new IllegalTransitionException(TicketStatus.ASSIGNED, TicketStatus.CLOSED));
            mvc.perform(post("/api/tickets/1/transitions").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON).content("{\"target\":\"CLOSED\"}"))
                    .andExpect(status().isConflict())
                    .andExpect(jsonPath("$.code").value(40901))
                    .andExpect(jsonPath("$.message", containsString("ASSIGNED")));
        }

        @Test
        @DisplayName("水平越权 → 403 / 40301;垂直越权 → 403 / 40302")
        void accessDenied() throws Exception {
            when(ticketService.get(1L)).thenThrow(new AccessDeniedException(ErrorCode.FORBIDDEN, "无权查看"));
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "3"))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.code").value(40301));

            when(ticketService.assign(eq(1L), any())).thenThrow(new AccessDeniedException(ErrorCode.ROLE_FORBIDDEN, "角色不够"));
            mvc.perform(post("/api/tickets/1/assign").header("X-User-Id", "3")
                            .contentType(MediaType.APPLICATION_JSON).content("{\"assigneeId\":4}"))
                    .andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.code").value(40302));
        }

        @Test
        @DisplayName("NotFoundException → 404 / 40401")
        void notFound() throws Exception {
            when(ticketService.get(404L)).thenThrow(new NotFoundException(ErrorCode.TICKET_NOT_FOUND, 404L));
            mvc.perform(get("/api/tickets/404").header("X-User-Id", "3"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.code").value(40401));
        }

        @Test
        @DisplayName("未知路径 → 404,仍是统一格式")
        void unknownPath() throws Exception {
            mvc.perform(get("/api/nothing-here").header("X-User-Id", "3"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.code").value(40401));
        }

        @Test
        @DisplayName("未预期的 RuntimeException → 500 / 50000,message 不泄漏异常细节")
        void unexpectedException() throws Exception {
            when(ticketService.get(anyLong())).thenThrow(new IllegalStateException("数据库连接池耗尽 jdbc://secret"));
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "3"))
                    .andExpect(status().isInternalServerError())
                    .andExpect(jsonPath("$.code").value(50000))
                    .andExpect(jsonPath("$.message", not(containsString("jdbc"))));
        }
    }

    @Nested
    @DisplayName("统一返回体与 traceId")
    class Envelope {

        @Test
        @DisplayName("创建成功 → 201,code=0,data 是工单,traceId 与响应头 X-Trace-Id 一致")
        void createdEnvelope() throws Exception {
            when(ticketService.create(any())).thenReturn(sampleVO());
            mvc.perform(post("/api/tickets").header("X-User-Id", "3").header("X-Trace-Id", "my-trace-001")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"title\":\"申请退款\",\"content\":\"内容\",\"customerId\":1001}"))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.code").value(0))
                    .andExpect(jsonPath("$.data.id").value(1))
                    .andExpect(jsonPath("$.data.category").value("REFUND"))
                    .andExpect(jsonPath("$.data.slaDeadline").value("2026-09-20 11:00:00"))
                    .andExpect(jsonPath("$.traceId").value("my-trace-001"))
                    .andExpect(header().string("X-Trace-Id", "my-trace-001"));
        }

        @Test
        @DisplayName("没带 X-Trace-Id 时服务端生成一个 16 位十六进制串")
        void generatedTraceId() throws Exception {
            when(ticketService.get(1L)).thenReturn(sampleVO());
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "3"))
                    .andExpect(status().isOk())
                    .andExpect(header().string("X-Trace-Id", org.hamcrest.Matchers.matchesPattern("[0-9a-f]{16}")));
        }

        @Test
        @DisplayName("data 为空的字段不输出(non_null):PENDING 单没有 assigneeId 键")
        void nullFieldsOmitted() throws Exception {
            when(ticketService.get(1L)).thenReturn(sampleVO());
            mvc.perform(get("/api/tickets/1").header("X-User-Id", "3"))
                    .andExpect(jsonPath("$.data.assigneeId").doesNotExist())
                    .andExpect(jsonPath("$.data.status").value("PENDING"));
        }
    }
}
