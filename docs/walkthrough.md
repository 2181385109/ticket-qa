# walkthrough — 逐模块讲解

> 读者画像:Python 熟练、Java 是弱项、正在补 Spring Boot。
> 每一节:解决什么问题 → 代码怎么组织 → Java 语言层面 → Spring 层面 → 5 道自检题(不给答案)。
> 决策的"为什么"在 `docs/adr/`,这里讲"是什么、怎么运转"。
> 代码路径相对 `service/src/main/java/com/ticketqa/`。

---

## 0. 阅读指南

### 0.1 先把它跑起来

```
ops/        docker compose up -d        → MySQL / Redis / RabbitMQ / WireMock / Prometheus
service/    mvn spring-boot:run         → http://localhost:8080
```

详细步骤在根目录 `README.md`。跑起来之后,对着 README 的 curl 清单点一遍,再回来读代码——
先有行为再看实现,比先看代码顺得多。

### 0.2 一次请求的完整旅程(先建立地图)

以 `POST /api/tickets` 创建工单为例,一次请求依次经过:

```
Tomcat 线程池取一个线程
 └─ TraceIdFilter            (Servlet Filter)      生成/透传 traceId,放进 MDC
     └─ DispatcherServlet
         └─ AuthInterceptor  (HandlerInterceptor)  X-User-Id → 查坐席(Redis 缓存)→ ThreadLocal
             └─ TicketController.create           @Valid 触发 Bean Validation
                 └─ TicketService.create
                     ├─ LlmService.classify       (事务外) 熔断器 → LlmClient → 契约校验 → 落盘
                     └─ txTemplate.execute        (事务内) insert ticket → bind llm log → 审计 → publishEvent
                         └─ 提交
                             └─ TicketEventPublisher (AFTER_COMMIT) → RabbitTemplate → RabbitMQ
                                 └─ StatusChangedConsumer (另一个线程) → 去重表 → 打日志
             └─ AuthInterceptor.afterCompletion    清 ThreadLocal
     └─ TraceIdFilter finally                      清 MDC
```

后面每一节讲其中一段。

### 0.3 Python → Java 的心智映射(先对齐概念)

| Python 里的 | Java / Spring 里对应的 | 差异要点 |
|---|---|---|
| `def f(x: int) -> str` 类型提示,运行时不检查 | `String f(int x)` 编译期强制 | 类型不对编译不过,不是运行时才报 |
| `dataclass(frozen=True)` | `record` | record 组件不可变,自动 equals/hashCode/toString |
| `dataclass` 可变 | 普通类 + getter/setter | Java 没有属性语法糖,框架靠 getter/setter 反射 |
| `Optional[T]` 只是类型提示 | `java.util.Optional<T>` 是一个真实容器对象 | 用 `.map/.orElse/.ifPresent` 链式处理,避免 null 检查 |
| `list[T]` 运行时不知道 T | `List<T>` 泛型,编译后擦除 | 编译期检查,运行时都是 `List<Object>` |
| lambda / 一等函数 | lambda + 函数式接口 | Java 的 lambda 必须有一个目标接口类型 |
| `with open() as f:` | `try (InputStream in = ...) {}` | try-with-resources,离开块自动 close |
| `@decorator` 运行时包装函数 | 注解本身不做事,由框架在特定时机读取 | 注解是元数据,谁在什么时候读它决定了它的效果 |
| `pytest` fixture 注入 | Spring 构造器注入 | 容器按类型找 Bean 填进构造器参数 |
| Django ORM / SQLAlchemy | MyBatis-Plus | MP 是"半 ORM":通用 CRUD 自动,复杂 SQL 手写 |
| `asyncio` 事件循环 | Tomcat 线程池,每请求一线程 | 阻塞 IO,所以"占着线程等 LLM"是真实成本 |
| `threading.local()` | `ThreadLocal<T>` | 同一个坑:线程复用时必须清理 |
| Flask `@app.errorhandler` | `@RestControllerAdvice` + `@ExceptionHandler` | 集中翻译异常为 HTTP 响应 |

---

## 1. 项目骨架与 Spring Boot 启动

### 解决什么问题

把几十个类组装成一个能跑的服务:谁创建对象、谁把依赖塞进去、配置从哪来、启动顺序是什么。
Python 里你自己 `main()` 里 new 一遍;Spring 里这些由**容器**做。

### 代码怎么组织

```
TicketQaApplication          入口,@SpringBootApplication
config/
  AppProperties              app.* 配置绑定(record + @ConfigurationProperties)
  LlmProperties              llm.* 配置绑定
  ClockConfig                Clock Bean,时区来自配置
  MybatisPlusConfig          @MapperScan、分页插件、自动填充时间
  JacksonConfig              LocalDateTime 的 JSON 格式
  CacheConfig                Redis 缓存序列化
  RabbitConfig               交换机 / 队列 / 绑定 / 消息转换器
  WebMvcConfig               注册拦截器
resources/application.yml    所有配置,${ENV:default} 形式
```

### Java 语言层面

**包(package)与可见性**。`package com.ticketqa.config;` 对应目录结构,是强制的。
没写修饰符的类 / 方法是"包私有",同包可见;`public` 全局可见;`private` 类内可见。
`AttachmentService` 第一次编译失败就是因为 `TicketService.getOrThrow` 是包私有、跨包调不了。

**静态 vs 实例**。`public static void main` 是静态方法,不需要对象就能调,JVM 从这里进。
`private static final Logger log = ...` 每个类一个静态常量,不随对象复制。

**record**(`AppProperties`):

```java
public record AppProperties(String timeZone, Sla sla, Ticket ticket, Attachment attachment) {
    public record Sla(Map<TicketPriority, Integer> responseMinutes, long scanIntervalMs, ...) {}
}
```

一行声明 = 私有 final 字段 + 规范构造器 + 访问器(`props.sla()`,注意不是 `getSla()`)+
equals / hashCode / toString。嵌套 record 表达配置树。record 不能有可变实例字段,
所以配置一旦绑定就是不可变的——这是有意的。

**泛型的 `Map<TicketPriority, Integer>`**。键是枚举,Spring 会把 yml 里的 `P0: 15` 转成
`TicketPriority.P0 → 15`。Python 里 dict 的 key 可以是任何东西;Java 里编译器知道 key 的类型,
`responseMinutes.get(outcome.priority())` 传错类型编译不过。

### Spring 层面

**容器(ApplicationContext)是什么**。一个大 Map,key 是 Bean 名字,value 是对象。
`SpringApplication.run()` 做的事:扫描 `com.ticketqa` 下所有带 `@Component` / `@Service` /
`@Configuration` / `@RestController` 的类,按依赖顺序创建对象,填进 Map。这些对象叫 Bean。

**依赖注入怎么发生**。本项目全部用**构造器注入**:

```java
public TicketService(TicketMapper ticketMapper, TicketStateMachine stateMachine, ...) {
    this.ticketMapper = ticketMapper;
    ...
}
```

容器创建 `TicketService` 时,看它唯一的构造器需要哪些参数,按**类型**在容器里找到对应 Bean
传进去。找不到 → 启动失败;找到两个 → 启动失败(除非 `@Primary` 或 `@Qualifier`)。
不需要 `@Autowired`——单构造器时 Spring 4.3+ 自动识别。字段注入(`@Autowired private X x;`)
在本项目里一处都没有,因为它让依赖不可见、测试时没法 new。

**Bean 生命周期**(你需要知道的最少版本):

1. 实例化:调构造器(此时依赖已经注入,因为它们是构造器参数)
2. 属性填充:字段注入在这一步(本项目不用)
3. 初始化回调:`@PostConstruct` 方法(`AttachmentService.ensureDir()` 建上传目录)
4. **代理**:如果类上有 `@Transactional` / `@Cacheable` 等,容器把原对象包进一个代理对象,
   放进 Map 的是代理不是原对象(第 5 节展开)
5. 使用
6. 销毁:`@PreDestroy`(本项目没用)

**Bean 作用域**。默认 `singleton`——整个容器只有一个实例,所有请求共用。所以 Bean 里
**不能有请求级的可变状态**:`TicketService` 没有任何非 final 字段,当前用户放在 ThreadLocal
而不是字段里。`CircuitBreaker` 有可变状态但它是有意的进程级共享,用了原子类保证线程安全。
其他作用域(`prototype`、`request`、`session`)本项目没用。

**自动配置**。`@SpringBootApplication` 包含 `@EnableAutoConfiguration`:Spring Boot 看
classpath 上有什么 jar,就自动配什么。有 `mysql-connector-j` + HikariCP → 自动配 `DataSource`;
有 `spring-rabbit` → 自动配 `ConnectionFactory`、`RabbitTemplate`(本项目自己定义了一个
`RabbitTemplate` Bean,自动配置的就让位——`@ConditionalOnMissingBean` 机制)。
`application.yml` 的 `spring.datasource.*`、`spring.rabbitmq.*` 就是喂给自动配置的。

**配置绑定**。`@ConfigurationPropertiesScan` 让容器找到 `AppProperties` 和 `LlmProperties`,
按前缀把 yml 树反射填进 record。`@Validated` + `@NotBlank` / `@Min` 让非法配置在启动时失败——
这比运行到一半 NPE 好得多。`${MYSQL_HOST:localhost}` 是"环境变量优先,没有就用默认值",
所以 compose 的 `.env` 和 yml 的默认值保持一致就能零改动跑起来。

**Clock 为什么是 Bean**。`LocalDateTime.now()` 是隐藏的全局依赖,测试没法控制。
把 `Clock` 做成 Bean 注入,生产用 `Clock.system(zone)`,测试换 `Clock.fixed(...)`。
所有 `now` 都从它来,时区只在一个地方声明。

**启动顺序里有个陷阱**:`@Scheduled` 任务在容器就绪后立即开始计时,`SlaScanner` 配了
`initialDelayString` 等一个周期再跑,避免启动瞬间数据库连接还没热就扫描。

### 自检问题

1. `TicketService` 的构造器有 11 个参数,容器是怎么知道每个参数该传哪个对象的?如果容器里
   有两个 `Clock` Bean 会发生什么?
2. `AppProperties` 是 record,不可变。如果想在运行时动态改 SLA 时限(不重启),这个设计要
   怎么改?改动会波及哪些类?
3. `@PostConstruct` 里抛异常,容器会怎样?这和在构造器里抛异常有区别吗?
4. singleton 作用域的 `TicketService` 被 200 个并发请求同时调用,为什么不会互相干扰?
   它的哪个依赖是有状态的?
5. 把 `application.yml` 里 `llm.timeout-ms` 改成 `50`(小于 `@Min(100)`),启动时会发生什么?
   报错信息会指向哪个类?

---

## 2. 统一返回、异常处理、参数校验、traceId

### 解决什么问题

所有接口返回同一种壳 `{"code","message","data","traceId"}`;所有异常在一个地方翻译成
HTTP 状态 + 业务错误码;参数校验用注解不用 if;每条日志和响应都带 traceId 方便对账。

### 代码怎么组织

```
common/
  Result<T>                  响应壳(record + 泛型)
  ErrorCode                  枚举:业务码 + HTTP 状态 + 默认文案
  BizException               业务异常基类(RuntimeException)
  ├─ IllegalTransitionException   非法流转(带 from/to)
  ├─ AccessDeniedException        越权
  └─ NotFoundException            找不到
  GlobalExceptionHandler     @RestControllerAdvice,异常 → ResponseEntity<Result>
  TraceIdFilter              Servlet Filter,traceId → MDC → 响应头
```

### Java 语言层面

**泛型 `Result<T>`**:

```java
public record Result<T>(int code, String message, T data, String traceId) {
    public static <T> Result<T> ok(T data) { ... }
}
```

`T` 是类型参数。`Result<TicketVO>` 和 `Result<List<AuditLogVO>>` 是不同的类型,编译器检查
你往 `data` 里放的东西对不对。静态方法上的 `<T>` 是方法级泛型声明——因为静态方法拿不到
类的 `T`。运行时泛型被**擦除**,`Result<TicketVO>` 和 `Result<String>` 是同一个 class,
Jackson 序列化靠 `data` 对象的实际类型,不靠 `T`。

**枚举可以有字段和方法**(`ErrorCode`):

```java
public enum ErrorCode {
    TICKET_NOT_FOUND(40401, HttpStatus.NOT_FOUND, "工单不存在"),
    ...;
    private final int code;
    ErrorCode(int code, HttpStatus httpStatus, String defaultMessage) { ... }
    public int code() { return code; }
}
```

Python 的 `Enum` 也能带值,但 Java 枚举是完整的类:私有构造器、字段、方法、甚至可以实现接口。
每个枚举常量是一个单例对象,`==` 比较安全。

**异常层次**。`RuntimeException` 的子类是**非受检异常**:方法签名不用声明、调用方不用
catch。`Exception` 的直接子类(如 `IOException`)是**受检异常**:必须 catch 或在签名里
`throws`。Python 没有这个区分。本项目所有业务异常继承 `RuntimeException`,让 Service 代码
不被 `throws` 污染。`AttachmentService` 里把 `IOException` 包成 `UncheckedIOException` 就是
在做"受检 → 非受检"的转换。

**`instanceof` 模式匹配**(Java 16+,`GlobalExceptionHandler` / `LlmHttpSupport`):

```java
if (e instanceof RestClientResponseException re) {
    return ... re.getStatusCode() ...;   // re 已经是转型后的变量
}
```

省掉了 `((RestClientResponseException) e).getStatusCode()` 的强转。

**Stream**(`handleBodyValidation`):

```java
e.getBindingResult().getFieldErrors().stream()
        .map(GlobalExceptionHandler::describe)
        .collect(Collectors.joining("; "));
```

相当于 `"; ".join(describe(fe) for fe in errors)`。`::` 是方法引用,`describe` 是
`FieldError → String` 的静态方法。Stream 是惰性的,`collect` 才真正执行。

### Spring 层面

**`@RestControllerAdvice` 的匹配规则**。所有 `@RestController` 抛出的异常都会经过它,
按异常类型**就近匹配**:抛 `IllegalTransitionException` 时,有 `BizException` 的处理器
就用它,不会掉到 `Exception` 的兜底处理器。所以处理器的顺序不重要,类型层次才重要。

**为什么是 `ResponseEntity<Result<Void>>` 而不是直接返回 `Result`**。`ResponseEntity`
能设 HTTP 状态码;直接返回对象状态码永远是 200(或类上的 `@ResponseStatus`)。
业务错误码的前三位就是 HTTP 状态(40901 → 409),`ErrorCode.httpStatus()` 直接给出。

**Bean Validation 什么时候触发**。`@Valid @RequestBody CreateTicketRequest req`——
`@Valid` 让 Spring 在参数绑定后、进方法前跑 Hibernate Validator,失败抛
`MethodArgumentNotValidException`,由 advice 翻译成 400 + 40001。
`@RequestParam` 上的 `@Min` 是另一套机制:需要类上 `@Validated`,由 AOP 在方法调用时校验,
失败抛 `ConstraintViolationException`。两种异常都处理了。

**Filter vs Interceptor**。`TraceIdFilter` 是 Servlet 规范的 Filter,在 `DispatcherServlet`
**之前**执行,拿不到 Spring MVC 的信息(不知道要进哪个 Controller),但能包住整个请求
——所以 traceId 放这里,连 404 都带 traceId。`AuthInterceptor` 是 Spring 的
HandlerInterceptor,在 DispatcherServlet **之内**,知道 handler 是谁,能按路径匹配
(只拦 `/api/**`)。`OncePerRequestFilter` 保证转发 / 错误页重定向时不重复执行。

**MDC**。`MDC.put("traceId", ...)` 把值挂在当前线程,logback 的 pattern `%X{traceId}` 取出来
打进每条日志。它是 ThreadLocal,所以 `finally { MDC.remove() }` 不能省。MQ 消费者在另一个
线程,`IdempotentConsumerSupport` 从消息体里取 traceId 重新 put——这是跨线程传递 traceId
的手工方式(不引链路追踪框架)。

### 自检问题

1. `Result<T>` 里的 `T` 在运行时是什么?Jackson 怎么知道 `data` 该序列化成 `TicketVO` 的形状?
2. 如果把 `BizException` 改成继承 `Exception`(受检),哪些代码会编译不过?`@Transactional`
   的默认回滚行为会怎么变?
3. 一个请求 `X-User-Id` 缺失被 `AuthInterceptor` 拦下返回 401,这个响应会经过
   `GlobalExceptionHandler` 吗?为什么?
4. `TraceIdFilter` 标了 `@Order(HIGHEST_PRECEDENCE)`,如果去掉会怎样?什么情况下会观察到差别?
5. 把 `@Validated` 从 `TicketController` 类上去掉,`GET /api/tickets?page=0` 会返回什么?
   为什么 `@Valid @RequestBody` 不受影响?

---

## 3. 持久层:MyBatis-Plus + MySQL

### 解决什么问题

把 Java 对象和数据库行互相转换,通用 CRUD 不写 SQL,特殊 SQL 手写且可见。

### 代码怎么组织

```
domain/entity/               6 个实体,一表一类,@TableName / @TableId / @TableField
domain/enums/                状态、分类、优先级、角色等枚举
mapper/                      6 个接口,继承 BaseMapper<实体>;TicketMapper 多两条注解 SQL
config/MybatisPlusConfig     @MapperScan、分页插件、时间自动填充
ops/mysql/init/01-schema.sql 建表 DDL(索引理由见 ADR-005)
```

### Java 语言层面

**接口没有实现类也能用**(`TicketMapper`):

```java
public interface TicketMapper extends BaseMapper<Ticket> {
    @Select("SELECT id FROM ticket WHERE ...")
    List<Long> selectSlaOverdueIds(@Param("now") LocalDateTime now, @Param("limit") int limit);
}
```

Python 里接口只是约定;Java 里接口是类型,但这个接口从头到尾没有 `class XxxImpl implements
TicketMapper`。它的实现是 MyBatis 在运行时用 **JDK 动态代理** 生成的:`@MapperScan` 扫到接口,
为它造一个代理对象,调用任何方法都被转发到 MyBatis 的 SQL 执行器——`selectById` 之类的通用
方法由 `BaseMapper<Ticket>` 的泛型参数决定表和列,注解方法直接执行注解里的 SQL。

**泛型继承 `BaseMapper<Ticket>`**:`BaseMapper<T>` 定义了 `T selectById(Serializable id)`、
`int insert(T entity)` 等,继承时把 `T` 绑定成 `Ticket`,于是 `ticketMapper.selectById(1L)`
返回 `Ticket` 而不是 `Object`。

**文本块**(Java 15+,`"""` 三引号)让多行 SQL 不用拼字符串。和 Python 的三引号一样,
但会自动去掉公共缩进。

**实体为什么是可变类而不是 record**。MyBatis 查出一行后:`new Ticket()`(无参构造)→
逐列 `setXxx(value)`。record 没有无参构造和 setter,MP 3.5.7 不支持。这是本项目实体类
150 行 getter/setter 的根本原因(ADR-010)。

**`Integer` vs `int`,`Boolean` vs `boolean`**。实体字段全用包装类型(`Integer deleted`、
`Boolean degraded`),因为数据库的 NULL 要能表达;`int` 没有 null,查到 NULL 会报错。
`Long id` 同理,插入前 id 是 null,由数据库生成后回填。

### Spring / MyBatis-Plus 层面

**`@TableName / @TableId / @TableField`**。类 ↔ 表,`@TableId(type = AUTO)` 表示主键由
数据库自增、insert 后回填到对象;字段 ↔ 列默认驼峰转下划线(`slaDeadline → sla_deadline`),
由 `map-underscore-to-camel-case: true` 开启。

**`@TableField(fill = INSERT)` + `MetaObjectHandler`**:插入时自动填 `createdAt / updatedAt`,
更新时自动填 `updatedAt`。`strictInsertFill` 只在字段为 null 时填——所以 `TicketService.create`
显式 `setCreatedAt(now)` 后不会被覆盖,保证 `sla_deadline == created_at + 时限`。

**`@TableField(updateStrategy = ALWAYS)`**。`updateById(entity)` 默认**跳过 null 字段**
(生成的 SQL 只 SET 非 null 的列)。这对"部分更新"友好,但对"要把 assignee 清成 NULL"
(退回 PENDING)是坑:不加这个注解,`setAssigneeId(null)` 后 `updateById` 根本不会碰这一列。
`assigneeId` 和 `closedAt` 加了 ALWAYS。

**`@TableLogic`**。`deleted` 标为逻辑删除字段后:所有 `select*` 自动加 `AND deleted = 0`,
`deleteById` 改写成 `UPDATE ... SET deleted = 1`。手写的注解 SQL **不会**自动加,所以
`TicketMapper` 的两条 SQL 里显式写了 `deleted = 0`。

**枚举怎么存**。`status` 字段是 `TicketStatus` 枚举,数据库列是 `VARCHAR(16)`。MP 默认的
`CompositeEnumTypeHandler`:枚举没有 `@EnumValue` 就按 `name()` 存取,`PENDING` 存成
字符串 `'PENDING'`。所以 DDL 里的 `COMMENT` 写的枚举值必须和 Java 枚举名一字不差。

**分页**。`ticketMapper.selectPage(new Page<>(page, size), wrapper)`——`PaginationInnerInterceptor`
把一条查询改写成两条:`SELECT COUNT(*)` 和 `SELECT ... LIMIT offset, size`。没有这个插件,
`Page` 参数会被忽略、返回全表。

**`LambdaQueryWrapper`**:

```java
new LambdaQueryWrapper<Ticket>()
        .eq(status != null, Ticket::getStatus, status)        // 第一个参数是"条件是否生效"
        .eq(user.is(Role.AGENT), Ticket::getAssigneeId, user.id())
        .orderByDesc(Ticket::getId);
```

`Ticket::getStatus` 是方法引用,MP 从它反推列名 `status`——改字段名时编译器帮你查
所有用到的地方,字符串拼列名做不到。第一个 boolean 参数让"可选条件"不用写 if。

**事务里的 Mapper 调用**。Mapper 代理从 Spring 的事务同步管理器里取当前线程绑定的连接
(`SqlSessionTemplate`)。所以同一个 `@Transactional` 方法里的多次 Mapper 调用用的是同一个
连接、同一个事务;方法外调用则每次一个自动提交的连接。

**与 SQLAlchemy 的对照**。SQLAlchemy 的 Session 有身份映射和脏检查(改了对象属性,commit 时
自动 UPDATE);MyBatis 没有——改了对象必须显式 `updateById`,否则数据库不知道。这是
MyBatis"半 ORM"的含义:它只做行 ↔ 对象转换,不追踪对象状态。

### 自检问题

1. `TicketMapper` 是接口,`ticketMapper.selectById(1L)` 真正执行的代码在哪里?用什么机制
   把接口调用变成 SQL?
2. 把 `Ticket.assigneeId` 上的 `@TableField(updateStrategy = ALWAYS)` 去掉,"退回 PENDING"
   接口会出现什么现象?数据库里会留下什么状态?
3. `TicketMapper.selectSlaOverdueIds` 的 SQL 显式写了 `deleted = 0`,而 `selectById` 没写。
   为什么后者也不会查到已删除的工单?如果把 `@TableLogic` 去掉会怎样?
4. `LlmCallLog.degraded` 是 `Boolean` 而 DDL 里是 `TINYINT(1)`,这个转换谁做的?如果字段
   改成基本类型 `boolean`,查到 NULL 会怎样?
5. `Page<Ticket>` 的分页依赖一个拦截器 Bean。如果 `MybatisPlusConfig` 里忘了注册它,
   `GET /api/tickets?page=2&size=1` 会返回什么?

---

## 4. 状态机(数据驱动)

### 解决什么问题

6 个状态 9 条边 1 个时间条件,要求"其余一律非法"可证明、可在白板上画出来(ADR-001)。

### 代码怎么组织

```
statemachine/
  Transition          record(from, to),当 Map 的 key
  TransitionGuard     函数式接口:(ticket, now) → Optional<拒绝原因>
  TransitionTable     三张表:EDGES(边)、guards(守卫)、entryActions(进入动作)
  TicketStateMachine  执行器:assertAllowed / transit
```

`TicketService` 调 `stateMachine.transit(ticket, target, now)`,它只改内存对象,不碰数据库。

### Java 语言层面

**`EnumMap` / `EnumSet`**。专门给枚举 key 优化的 Map / Set:内部是数组,按 `ordinal()` 索引,
比 HashMap 快且遍历有序。`EnumSet.of(ASSIGNED, ESCALATED)` 是一个位图。

**静态初始化块**:

```java
private static final Map<TicketStatus, Set<TicketStatus>> EDGES;
static {
    Map<...> edges = new EnumMap<>(TicketStatus.class);
    edges.put(PENDING, EnumSet.of(ASSIGNED, ESCALATED));
    ...
    EDGES = Collections.unmodifiableMap(edges);
}
```

类加载时执行一次,给静态常量赋值。`unmodifiableMap` 返回只读视图,任何 `put` 抛异常——
表是事实来源,不允许运行时被改。

**静态导入**:`import static com.ticketqa.domain.enums.TicketStatus.PENDING;` 之后可以直接写
`PENDING` 而不是 `TicketStatus.PENDING`,让表读起来像规格文档。

**record 当 Map 的 key**。`new Transition(CLOSED, PROCESSING)` 每次都是新对象,但 record
自动生成的 `equals/hashCode` 按组件比较,所以 `guards.get(new Transition(CLOSED, PROCESSING))`
能命中。普通类不重写 `equals/hashCode` 的话,按引用比较,永远找不到。

**函数式接口与 lambda**:

```java
@FunctionalInterface
public interface TransitionGuard {
    Optional<String> check(Ticket ticket, LocalDateTime now);
}
guards.put(new Transition(CLOSED, PROCESSING), (ticket, now) -> {
    if (closedAt.plusDays(reopenDays).isBefore(now)) return Optional.of("已关闭超过 7 天");
    return Optional.empty();
});
```

Java 的 lambda 没有自己的类型,必须"落"到一个只有一个抽象方法的接口上——那个接口就是
它的类型。`@FunctionalInterface` 让编译器检查确实只有一个抽象方法。`BiConsumer<Ticket,
LocalDateTime>` 是 JDK 自带的双参数无返回值函数式接口,进入动作用它。

**`Optional` 链**(`TicketStateMachine.assertAllowed`):

```java
table.guardOf(from, target)                       // Optional<TransitionGuard>
        .flatMap(guard -> guard.check(ticket, now))  // Optional<String>
        .ifPresent(reason -> { throw new IllegalTransitionException(...); });
```

读法:如果有守卫,跑它;如果守卫返回了原因,抛异常。没有守卫或守卫放行,什么都不做。
三层 if-null 压成一条链。`flatMap` 用于"函数本身返回 Optional"的情况,`map` 会得到
`Optional<Optional<String>>`。

**lambda 里抛异常**。`ifPresent(reason -> { throw ...; })`——lambda 体里可以抛非受检异常,
它会穿透 `ifPresent` 冒到外面。受检异常不行(函数式接口的签名没有 `throws`),这是本项目
所有业务异常用 `RuntimeException` 的又一个理由。

**闭包捕获**。守卫 lambda 用了构造器里的局部变量 `reopenDays`,Java 要求被捕获的局部变量
是"事实上 final"(赋值后不再改)。Python 的闭包可以改外部变量(`nonlocal`),Java 不行。

### Spring 层面

`TransitionTable` 和 `TicketStateMachine` 都是 `@Component`,singleton。表是静态的,守卫和
动作在构造器里注册一次。`TransitionTable` 依赖 `AppProperties` 拿 `reopenWindowDays`——
配置通过构造器注入,守卫在构造时把它捕获进 lambda。

注意 `TicketStateMachine` **不依赖 Mapper**:它只改内存对象,持久化和事件是 Service 的事。
这让它可以在没有 Spring、没有数据库的情况下单测——`new TicketStateMachine(new TransitionTable(props))`
就够了。

### 自检问题

1. 从 `EDGES` 表推导:6×6 = 36 种 (from, to) 组合里合法的有 9 种,非法的 27 种包括哪些?
   哪些非法组合值得写成测试用例,哪些是冗余的?
2. `entryActions` 在 `setStatus` 之前执行。如果调换顺序,`PROCESSING` 的进入动作会出什么问题?
3. 守卫 lambda 捕获了 `reopenDays`。如果把它改成从 `props` 里每次读取(`props.ticket().reopenWindowDays()`),
   行为有区别吗?哪种更适合运行时改配置?
4. `Transition` 如果从 record 改成普通类且不重写 `equals/hashCode`,`guardOf(CLOSED, PROCESSING)`
   会返回什么?为什么?
5. `EDGES` 是 `static final` 且不可变,`guards` 是实例字段的 `HashMap`。为什么不把守卫表
   也做成静态的?

---

## 5. 工单服务、审计日志与事务

### 解决什么问题

一次状态流转 = 改状态 + 写审计 + 发事件,要么全成要么全不成;MQ 发送必须在提交之后;
LLM 调用不能占着数据库连接(ADR-002)。

### 代码怎么组织

```
ticket/
  TicketController     参数绑定 + @Valid + 调 Service,没有任何 if
  TicketService        所有业务:权限、状态机、审计、事件、事务边界
  TicketConverter      实体 → VO
  dto/                 请求 / 响应 record
  event/TicketDomainEvent   进程内事件(record)
audit/AuditLogService  写审计,Propagation.MANDATORY
mq/TicketEventPublisher    @TransactionalEventListener(AFTER_COMMIT) → RabbitMQ
```

典型流转方法的骨架:

```java
@Transactional(rollbackFor = Exception.class)
public TicketVO transit(Long id, TransitionRequest req) {
    CurrentUser user = UserContext.require();          // 谁
    Ticket ticket = getOrThrow(id);                    // SELECT
    access.checkWrite(user, ticket);                   // 能不能(ADR-007)
    TicketStatus from = stateMachine.transit(ticket, req.target(), now);   // 查表改内存
    updateOrConflict(ticket);                          // UPDATE … WHERE id=? AND version=?;0 行 → 40903(ADR-017)
    auditLogService.record(...);                       // INSERT 审计(同事务;from 已被 version 验证过)
    publish(EventType.STATUS_CHANGED, ...);            // 只是发进程内事件,还没到 MQ
    return TicketConverter.toVO(ticket);
}                                                      // ← 提交;提交后 Publisher 才发 MQ
```

### Java 语言层面

**`final` 字段 + 构造器注入 = 不可变依赖**。`private final TicketMapper ticketMapper;`
构造后不能再指向别的对象,这是线程安全的基础之一。

**Stream + 方法引用**(`list`):

```java
result.getRecords().stream().map(TicketConverter::toVO).toList();
```

`toList()` 是 Java 16+ 的快捷方式,返回不可变 List。Python 里 `[toVO(t) for t in records]`。

**三元表达式里的 lambda**(`create`):`txTemplate.execute(status -> { ...; return t; })`——
`execute` 接收 `TransactionCallback<T>`,lambda 的返回值就是 `execute` 的返回值。`status`
参数是 `TransactionStatus`,可以调 `setRollbackOnly()`,本项目没用到但必须声明。

**`Objects.equals(a, b)`**。两个 `Long` 用 `==` 比较的是引用不是值——`Long` 在 -128~127
之外不缓存,`assigneeId == user.id()` 在 id 大于 127 时会错。`Objects.equals` 处理 null
且按值比较。这是 Java 新手最常踩的坑之一,`AccessChecker` 里全用它。

### Spring 层面(本节最重要)

**`@Transactional` 的代理机制**。容器创建 `TicketService` 时发现它有 `@Transactional` 方法,
于是生成一个**子类**(CGLIB 代理),重写那些方法:

```
代理.transit(id, req):
    开事务(从连接池拿连接,setAutoCommit(false),绑定到当前线程)
    try {
        原对象.transit(id, req)     ← 你写的代码
        提交
    } catch (需要回滚的异常) {
        回滚
        rethrow
    } finally {
        解绑连接,还回池
    }
```

`TicketController` 注入的是代理,所以经过了这层包装。**同类内部 `this.transit()` 调用走的
是原对象,不经过代理,`@Transactional` 不生效**——这是 Spring 事务最经典的失效场景,
`TicketService.create()` 用 `TransactionTemplate` 就是为了绕开它(还有 `AgentCache` 拆成
独立 Bean 是同一个原因,那里是 `@Cacheable`)。

**其他失效场景**(自检):
- 方法不是 `public`:CGLIB 只能代理 public 方法(严格说 protected 也能但 Spring 不处理)。
- 异常被 catch 吃掉:代理看不到异常,不会回滚。
- 抛的是受检异常且没写 `rollbackFor`:默认只回滚 `RuntimeException` 和 `Error`。
  本项目所有 `@Transactional` 都写了 `rollbackFor = Exception.class`。
- 多线程:事务绑定在线程上,方法里 `new Thread` 或 `@Async` 里的操作不在事务里。
- 类被 `final` 修饰:CGLIB 无法生成子类。

**传播行为(Propagation)**。本项目用了四种:

| 传播 | 用在 | 含义 |
|---|---|---|
| `REQUIRED`(默认) | `transit / grab / assign / update / delete`、`bindTicket` | 有事务就加入,没有就新开 |
| `MANDATORY` | `AuditLogService.record` | 必须已有事务,否则抛 `IllegalTransactionStateException` |
| `REQUIRES_NEW` | `LlmCallLogService.record` | 挂起当前事务,另拿一个连接新开事务,提交后恢复 |
| 无事务 | `LlmService.classify`、`TicketService.create` 前半段、`draftReply` | HTTP 等待不占连接 |

`REQUIRES_NEW` 的代价:同一个线程同时持有两个连接。连接池 20 个,极端情况下 10 个线程
各持两个就满了。本项目只在 LLM 落盘这一处用它,且那一处本来就在事务外(`create` 前半段),
所以实际上不会叠加。

**`TransactionTemplate`**。编程式事务,和注解做同样的事但边界写在代码里:

```java
Ticket created = txTemplate.execute(status -> { ... return t; });
```

lambda 内抛非受检异常 → 回滚;正常返回 → 提交。Spring Boot 自动配置了这个 Bean。

**`ApplicationEventPublisher` + `@TransactionalEventListener`**。Spring 自带的进程内发布 /
订阅。`events.publishEvent(event)` 在事务里调用时,Spring 不会立刻调监听器,而是把事件
挂到当前事务上;`@TransactionalEventListener(phase = AFTER_COMMIT)` 的监听器在**提交之后**
被调用。回滚了就不调。这就是"消费者收到消息时数据一定已经提交"的实现方式。
`fallbackExecution = true`:没有事务时立即执行而不是丢弃。

AFTER_COMMIT 里的代码**不在事务里**(事务已经结束),所以监听器里再操作数据库是自动提交的、
抛异常也不会回滚任何东西——`TicketEventPublisher` 只发 MQ,catch 了 `AmqpException`。

**`@Transactional` 上的 `readOnly`**。本项目查询方法没加 `@Transactional(readOnly = true)`,
因为单条查询不需要事务;`list` 的两条 SQL(COUNT + LIMIT)在不同的自动提交连接里跑,
理论上有不一致窗口(计数后有人插了一条),可接受。

### 自检问题

1. 把 `TicketService.transit` 上的 `@Transactional` 去掉,调用 `POST /transitions` 时
   `AuditLogService.record` 会发生什么?为什么这是一个"好"的失败?
2. 在 `transit` 方法里加一个 `try { ... } catch (Exception e) { log.error(...); }` 包住
   `auditLogService.record`,事务还会回滚吗?数据库里会留下什么?
3. `create()` 为什么不能写成 `@Transactional` 的 `create()` 调用同类的 `classifyOutsideTx()`?
   把 LLM 调用挪到另一个 Bean 里能解决吗?和 `TransactionTemplate` 比哪个更好?
4. `TicketEventPublisher.onTicketEvent` 里如果 `rabbitTemplate.convertAndSend` 抛异常,
   工单状态会回滚吗?HTTP 响应是什么?
5. `LlmCallLogService.record` 用 `REQUIRES_NEW`,如果它在一个已经持有事务的方法里被调用,
   连接池会发生什么?什么情况下这会导致死锁?

---

## 6. 坐席抢单(2026-09-21 修复后:三层防线)

### 解决什么问题

PENDING 的工单,坐席点一下变成分配给自己(CLAUDE.md §5.2)。第一版是 SELECT → 内存判断 → UPDATE,
2026-09-20 压测证明 2 线程即 100% 重复分配(KI-008,[记录](findings/20260920-压测-抢单并发重复分配.md)),
审计还会记出没发生过的 `PENDING→ASSIGNED`(KI-009)。本节讲修复后的实现;为什么这么修在 ADR-016 / ADR-017。

### 代码怎么组织

```java
public TicketVO grab(Long id) {                                   // 没有 @Transactional!
    CurrentUser user = UserContext.require();
    Optional<String> lock = grabLock.tryAcquire(id);              // ① Redis SET NX,事务之外
    if (lock.isEmpty()) throw new BizException(ErrorCode.GRAB_CONTENDED);   // 40904,连数据库连接都不拿
    try {
        return txTemplate.execute(status -> grabInTransaction(id, user));   // ② 事务在这一行里开始和提交
    } finally {
        grabLock.release(id, lock.get());                         // ③ 提交之后再放锁
    }
}

private TicketVO grabInTransaction(Long id, CurrentUser user) {
    Ticket ticket = getOrThrow(id);                               // 快照读
    access.checkGrab(user, ticket);
    if (ticket.getStatus() != PENDING) throw new IllegalTransitionException(...);   // 顺序场景的准确文案
    int affected = ticketMapper.grabIfPending(id, user.id(), ticket.getVersion(), now);   // ④ 条件 UPDATE
    if (affected == 0) throw new IllegalTransitionException(PENDING, ASSIGNED, "已被其他坐席抢走");   // 40901
    TicketStatus from = PENDING;                                  // ⑤ 不是快照,是 WHERE 断言过的事实
    ... 审计 / 事件 / 返回
}
```

```sql
-- TicketMapper.grabIfPending
UPDATE ticket SET status='ASSIGNED', assignee_id=?, updated_at=?, version=version+1
 WHERE id=? AND status='PENDING' AND version=? AND deleted=0
```

三层各管一件事:

| 层 | 类 | 保证什么 | 失败码 | 拿掉它会怎样 |
|---|---|---|---|---|
| Redis 前置锁 | `GrabLock` | 削峰:同一张单同一时刻只放一个请求进库 | 40904 | 仍然正确,只是所有请求都进库排行锁(回归里 Redis 停机 120 个请求恰好 1 个 200) |
| 条件 UPDATE | `grabIfPending` | **正确性**:只有仍为 PENDING 的行会被改 | 40901 | 重复分配回来 |
| version | `@Version` + 拦截器 | 其它写路径的正确性,审计 from 可信 | 40903 | 改派 / 流转 / 改标题撞车时后写的覆盖先写的 |

### Java 语言层面

- **`Optional<String>` 作为三态返回值**:`tryAcquire` 要表达"拿到了(token)/ 被占(空)/ Redis 挂了(fail-open,空串)"。
  Python 会返回 `str | None` 再加一个 sentinel;Java 里 `Optional` 把"可能没有"写进类型签名,调用方必须 `isEmpty()` / `get()`
  显式处理,编译器不允许直接把它当字符串用。空串代表 fail-open 是一个约定,`release` 看到空串直接返回——
  写在 Javadoc 里,是这个类唯一需要"记住"的东西。
- **`try { … } finally { … }` 保证放锁**:`txTemplate.execute` 里抛任何异常(409、403、数据库错误)都会经过 `finally`,
  锁不会留到 TTL 到期。Python 的 `try/finally` 语义相同;区别是 Java 没有 `with`,资源释放要么 try-with-resources
  (需要 `AutoCloseable`),要么手写 finally。这里锁不是 Closeable,所以手写。
- **lambda 当事务回调**:`txTemplate.execute(status -> grabInTransaction(id, user))`——参数是 `TransactionCallback<T>`
  函数式接口(只有一个方法 `T doInTransaction(TransactionStatus)`),lambda 自动适配。`status` 参数没用到但不能省略
  (接口签名决定形参个数)。它捕获了外层的 `id` 和 `user`:Java 的 lambda 只能捕获"事实上不变"的局部变量,
  所以这两个变量在后面不能被重新赋值——Python 闭包没有这个限制。
- **`ticket.getVersion() == null ? null : ticket.getVersion() + 1`**:`Integer` 是对象,可能为 null;`+ 1` 会自动拆箱,
  null 拆箱抛 NPE。老数据(迁移前插入的行)version 是 DEFAULT 0,不会是 null,但 H2 切片里手工 `new Ticket()` 的对象会,
  所以防御一下。这就是 Python 里 `None + 1` 报 TypeError 的 Java 版本,只是错误发生在"拆箱"这个 Python 没有的概念上。

### Spring / MyBatis-Plus 层面

- **为什么 `grab` 不能用 `@Transactional`**:注解式事务是代理在方法外层开、方法返回后提交。锁要在事务开始**前**拿、
  提交**后**放,注解包不住这个顺序——如果在方法体里拿锁,连接已经先被占了;如果把 `grabInTransaction` 也加 `@Transactional`
  然后 `this.grabInTransaction()`,不经过代理,注解不生效(第 5 节讲过的自调用失效)。所以用 `TransactionTemplate` 把
  "事务从哪一行开始、哪一行结束"写在代码里。`create()` 因为要把 LLM 调用放在事务外,是同一个理由。
- **`OptimisticLockerInnerInterceptor` 改写了什么**:`MybatisPlusConfig` 里注册后,所有 `updateById(entity)` 在执行前
  被拦截:如果实体有 `@Version` 字段且值非空,SQL 的 WHERE 追加 `AND version = ?`(旧值),SET 追加 `version = ?`(旧值 + 1),
  执行后把新值回填进实体。它是 MyBatis 的 `Interceptor` 插件链上的一环,和分页插件同一个 `MybatisPlusInterceptor`;
  顺序按官方建议分页在前、乐观锁在后。看 `target/test-slice.log` 里的 `Preparing:` 行就能看到改写后的 SQL。
  `updateOrConflict` 只做一件事:受影响 0 行 → 抛 40903。
- **快照读 vs 当前读**(这是整个修复的物理基础):REPEATABLE-READ 下普通 SELECT 读的是事务开始时的一致性快照,
  看不到别的事务刚提交的 ASSIGNED;UPDATE 先拿行锁、再在**最新已提交版本**上求值 WHERE。把判断写进 WHERE,
  就是把判断从"快照"挪到了"锁下的最新版本"。这一条不是 Spring 的事,是 InnoDB 的事——但它决定了为什么
  "先 SELECT 再判断再 UPDATE"在任何隔离级别下都救不回来(SERIALIZABLE 除外,那是把所有读都变成锁定读)。
- **`AuditLogService.record` 仍是 `MANDATORY`**:它在 `grabInTransaction` 里被调用,而 `grabInTransaction` 跑在
  `txTemplate.execute` 开的事务里,所以有外层事务;如果有人把 `txTemplate.execute` 去掉直接调 `grabInTransaction`,
  审计会抛 `IllegalTransactionStateException`——这个"故意炸"保护了 ADR-002 的边界。
- **MyBatis 一级缓存**(H2 切片测试踩到的坑):同一个 SqlSession(同一事务)里 `selectById(id)` 两次返回**同一个对象**,
  第二次根本没查库。想在测试里模拟"两个客户端各持一份快照",要么把 version 值先拷出来,要么 `new Ticket()` 手工构造。
  Python 的 ORM(SQLAlchemy 的 identity map)有同样的行为,只是 MyBatis 的缓存边界是 SqlSession,更容易被忽视。

### 自检问题

1. Redis 停机时 `tryAcquire` 返回什么?`release` 收到它时做什么?这一轮抢单的正确性由哪一层保证?回归记录里
   哪一组数据证明了这一点?
2. `grabIfPending` 的 WHERE 里已经有 `status='PENDING'`,为什么还要 `version=?`?去掉它,哪种并发场景会出问题?
   (提示:改标题和抢单同时到达。)
3. 100 个线程抢同一张单,回归里"进库 2 个、锁挡 98 个",那第 2 个进库的请求为什么没有走到条件 UPDATE、
   `grab_conflict_total` 为什么是 0?它是在哪一行返回的、返回什么码?
4. 把 `txTemplate.execute(...)` 换成 `grabInTransaction(id, user)` 直接调用(不开事务),会在哪一行抛什么异常?
   这个异常保护的是哪条 ADR?
5. (开放题)如果业务要求"排队等锁而不是拒绝"(先到先得),`GrabLock` 应该怎么改?改了之后条件 UPDATE 还需要吗?
   Redis 主从切换丢锁的场景下,你的新设计会多分配吗?

---

## 7. SLA 定时扫描与自动升级

### 解决什么问题

超时未响应的工单自动升级到 `ESCALATED` 并发 MQ;同一张工单绝不升级两次;边界按闭区间
(ADR-006)。

### 代码怎么组织

```
sla/
  SlaScanner             @Scheduled 定时器;Redis 扫描锁(fail-open);逐张调 escalate
  SlaEscalationService   单张工单:条件 UPDATE → 受影响 1 行才写审计 + 发两个事件;独立事务
  SlaAdminController     POST /api/admin/sla/scan 手动触发一轮(ADMIN)
mapper/TicketMapper      selectSlaOverdueIds(now, limit) / escalateIfStillUnresponded(id, from, version, now)
```

扫描一轮:

```
SET NX ticketqa:lock:sla-scan (TTL 25s)     ← 拿不到:别的实例在扫,跳过;Redis 挂:照扫
SELECT id FROM ticket WHERE status IN (PENDING, ASSIGNED) AND escalated_at IS NULL
   AND sla_deadline <= now AND deleted = 0 ORDER BY sla_deadline LIMIT 100
for id in ids:
    escalate(id, now):                       ← 每张一个事务
        before = SELECT … WHERE id=?           ← 读到 status / version
        UPDATE ticket SET status='ESCALATED', escalated_at=now, version=version+1
         WHERE id=? AND status=before.status AND status IN (PENDING, ASSIGNED)
           AND version=before.version AND escalated_at IS NULL     ← status/version 是 ADR-017 加的
        affected == 0 → 跳过(别人处理过了,或扫描后被人流转 / 抢走——下一轮重读)
        affected == 1 → 审计(SCHEDULER) + STATUS_CHANGED 事件 + SLA_ESCALATED 事件
释放锁(Lua:只删自己的)
```

### Java 语言层面

**`volatile` / `AtomicInteger` 在这一节没有,但有 `UUID instanceId`**:每个进程一个随机 id,
作为锁的 value,释放时用 Lua 脚本比对,防止删掉别人的锁(自己的锁过期后别人拿到了)。

**`Boolean` 三态**。`tryLock()` 返回 `Boolean`(包装类型),`TRUE` 拿到、`FALSE` 被占、
`null` Redis 不可用。基本类型 `boolean` 表达不了第三种。`Boolean.TRUE.equals(x)` 是
null-safe 的比较写法。

**try / finally 释放锁**。`scanOnce` 的 finally 里 `unlock()`,无论扫描是否抛异常都释放;
但只在 `locked == TRUE` 时释放——没拿到锁就不能去删。

**逐张 try / catch**。循环里每张工单单独 catch,一张失败不中断整轮。这和事务边界一致:
`escalate` 是 `@Transactional`,一张回滚不影响其他。

### Spring 层面

**`@Scheduled(fixedDelayString = "${app.sla.scan-interval-ms}")`**。`@EnableScheduling`
开启后,Spring 用一个**单线程**的 `TaskScheduler` 跑所有 `@Scheduled` 方法。
`fixedDelay` = 上一次**结束**到下一次开始的间隔(不会重叠);`fixedRate` = 上一次**开始**
到下一次开始(慢了会积压)。`initialDelay` 让启动后先等一个周期。`String` 后缀的属性
支持 `${}` 占位符。

**定时任务和 `@Transactional`**。`scheduledScan` 本身不在事务里(它只是编排),事务在
`SlaEscalationService.escalate` 上。这两个方法在不同 Bean 里,所以 `@Transactional` 通过
代理正常生效——如果把 `escalate` 写在 `SlaScanner` 自己类里再 `this.escalate()`,注解失效。

**`StringRedisTemplate`**。Spring Data Redis 提供的模板,key / value 都是 String,
`opsForValue().setIfAbsent(key, value, ttl)` 对应 `SET key value NX PX ttl`。
`execute(RedisScript, keys, args)` 跑 Lua,脚本在 Redis 里原子执行,"比对再删"不会被
插队。

**fail-open 的实现**。`tryLock` 里 catch 所有异常返回 null,打点 `sla_scan_lock_unavailable_total`。
调用方看到 null 就当"没锁但继续"。这是有意的:正确性由数据库条件更新保证,锁只是优化。
做 `docker stop redis` 故障注入时会看到:扫描照常、指标增长、日志 WARN。

**手动触发接口**。`SlaAdminController.scan()` 直接调 `scanner.scanOnce()`,和定时器走同一段
代码。接口测试用它代替"等 30 秒",测试时间和定时器周期解耦。

### 自检问题

1. 一张 P0 工单在 10:00:00.000 创建,`sla_deadline` 是 10:15:00.000。扫描在 10:15:00.000
   整点跑,会升级吗?10:14:59.999 呢?这两个时刻在代码里对应哪个比较运算符?
2. 两个服务实例同时扫到同一张工单、同时执行 `escalateIfStillUnresponded`,InnoDB 行锁会
   让它们怎么排队?第二个拿到的 `affected` 是几?它会写审计吗?
3. 一张工单被升级后组长改派回 ASSIGNED,`sla_deadline` 仍然是过去时间。下一轮扫描会再
   升级它吗?是哪个条件挡住的?
4. Redis 挂了,`tryLock` 返回 null,扫描继续。此时 `unlock()` 会被调用吗?如果 Redis 在
   扫描中途恢复,`unlock` 的 Lua 脚本会删掉什么?
5. `fixedDelay` 换成 `fixedRate`,并且一轮扫描耗时超过 30 秒,会发生什么?单线程调度器
   在这里起了什么作用?

---

## 8. RabbitMQ 异步链路与消费幂等

### 解决什么问题

三类事件(状态变更、SLA 升级、分配)走 MQ 通知;消费端必须幂等(ADR-003)。

### 代码怎么组织

```
config/RabbitConfig            拓扑:1 个 topic 交换机、3 个队列、3 个绑定;JSON 转换器;RabbitTemplate
mq/message/TicketEventMessage  消息体(普通类 + 无参构造,Jackson 需要)
mq/TicketEventPublisher        AFTER_COMMIT 监听器 → convertAndSend
mq/IdempotentConsumerSupport   consumeOnce(consumer, message, business):去重表 + 事务
mq/consumer/*Consumer          三个 @RabbitListener,各调 consumeOnce
```

消息流:

```
TicketService.publish(event)                 进程内事件(事务里)
   ↓ 提交
TicketEventPublisher.onTicketEvent           AFTER_COMMIT
   → TicketEventMessage.from(event)          生成 messageId(UUID)
   → rabbitTemplate.convertAndSend(exchange, routingKey, message)   JSON
   ↓ RabbitMQ 按 routing key 路由到队列
StatusChangedConsumer.onMessage(message)     @RabbitListener,另一个线程
   → idempotent.consumeOnce("status-changed-notifier", message, m -> log.info(...))
        开事务
        INSERT mq_message_dedup (message_id, consumer)   ← 唯一键
        DuplicateKeyException → 重复,跳过
        插入成功 → 执行 business lambda
        提交(business 抛异常 → 回滚,去重行消失 → 消息重投后可再处理)
```

### Java 语言层面

**`Consumer<T>` 作为参数**(`consumeOnce`):

```java
public void consumeOnce(String consumerName, TicketEventMessage message, Consumer<TicketEventMessage> business)
// 调用:
idempotent.consumeOnce(NAME, message, m -> log.info("[通知客户] 工单 {} ...", m.getTicketNo()));
```

`java.util.function.Consumer<T>` 是"接收一个 T 不返回值"的函数式接口。把业务逻辑作为
lambda 传进去,幂等外壳就能复用于三个消费者——这是 Java 版的"高阶函数"。

**为什么消息体不是 record**。Jackson 反序列化 record 需要 2.12+ 且有些边界情况;
`TicketEventMessage` 用普通类 + 无参构造 + setter,最稳。`from(TicketDomainEvent)` 静态工厂
从 record 事件转换过来。

**捕获 `DuplicateKeyException`**。Spring 把各数据库的唯一键冲突异常统一翻译成
`org.springframework.dao.DuplicateKeyException`(非受检),所以不用关心 MySQL 的错误码 1062。
在 `tryMark` 内部 catch,不让它穿过 `@Transactional` 边界——穿过去 Spring 会把事务标记为
rollback-only,后面的 commit 会失败。

### Spring 层面

**拓扑声明为 Bean**。`TopicExchange`、`Queue`、`Binding` 声明成 `@Bean` 后,Spring AMQP 的
`RabbitAdmin` 在第一次建立连接时自动向 Broker 声明它们(`declare` 是幂等的,重复声明同参数
不报错;参数不同会报错——比如把 durable 改了,得先删队列)。

**`Jackson2JsonMessageConverter`**。让 `convertAndSend(obj)` 把对象序列化成 JSON、
`@RabbitListener` 方法参数按 JSON 反序列化。消息头里带 `__TypeId__`(类全名),消费端据此
反序列化;跨语言消费者(Python)忽略这个头直接解析 JSON 即可。复用了 Spring Boot 配好的
`ObjectMapper`,所以 `LocalDateTime` 格式和 HTTP 响应一致。

**`@RabbitListener(queues = ...)`**。`RabbitListenerAnnotationBeanPostProcessor` 扫描到它,
为每个方法创建一个 `SimpleMessageListenerContainer`:开一个线程阻塞消费队列,收到消息 →
转换 → 调方法。**方法在容器的线程里执行,不是请求线程**,所以 ThreadLocal 里没有当前用户、
MDC 里没有 traceId(`consumeOnce` 从消息体取 traceId 重新 put)。

**消费失败策略**(`application.yml`):

```yaml
listener.simple:
  acknowledge-mode: auto                # 方法正常返回 → ack;抛异常 → 按下面的策略
  default-requeue-rejected: false       # 不无限重投
  retry: enabled, max-attempts 3        # 本地重试 3 次(在同一线程里 sleep 后重调)
```

重试用尽 → 拒绝且不重入队 → 消息丢弃(没配死信队列,ADR-003)。因为有去重表,重试时
第一次插入的去重行已经随失败的事务回滚了,重试可以正常处理——这是"去重和业务同事务"
的直接收益。

**`consumeOnce` 上的 `@Transactional` 为什么有效**。`StatusChangedConsumer` 注入的是
`IdempotentConsumerSupport` 的代理,跨 Bean 调用,代理生效。如果把幂等逻辑写在消费者
自己的方法里再 `this.xxx()`,就失效了。

**Publisher 的失败**。`convertAndSend` 是 fire-and-forget:Broker 不可达时抛 `AmqpException`,
Publisher catch 后打点 `mq_event_publish_failed_total`。没开 publisher confirms——
那是"Broker 确认收到"的回调机制,本项目不需要那个级别的保证(ADR-002)。

### 自检问题

1. 同一条消息被投递两次,第二次 `consumeOnce` 走到哪一行就返回了?去重表里有几行?
   `mq_event_duplicate_total` 增加了吗?
2. `business` lambda 里抛了 `RuntimeException`,去重行还在吗?消息会怎样?3 次重试都失败后呢?
3. 把 `IdempotentConsumerSupport.tryMark` 里的 `catch (DuplicateKeyException e)` 去掉,让它
   冒到 `consumeOnce` 外面。事务会怎样?消费者会看到什么异常?
4. `TicketEventMessage` 改成 record,`@RabbitListener` 方法能收到消息吗?Jackson 需要什么条件?
5. `docker stop rabbitmq` 后调用 `POST /transitions`,HTTP 返回什么?数据库里状态和审计
   改了吗?哪个指标会增长?恢复 RabbitMQ 后那条消息还会被发出去吗?

---

## 9. LLM 依赖路径

### 解决什么问题

工单创建时自动分类 + 优先级,坐席回复时生成草稿。LLM 慢、贵、输出不确定、可用性不可控,
所以要:超时 3 秒降级到规则、连续失败 5 次熔断 60 秒、分类越界落 OTHER、每次调用落盘、
打指标(ADR-004、ADR-009)。

### 代码怎么组织

```
llm/
  LlmClient                    接口:requestModel() / classify() / draftReply()
  OpenAiCompatibleLlmClient    真实实现:/chat/completions,response_format=json_object
  WireMockLlmClient            挡板实现:/mock/llm/classify、/mock/llm/draft
  LlmClientConfig              按 llm.mode 装配其中一个;RestClient + JDK HttpClient 超时
  LlmHttpSupport               异常 → DegradeReason 翻译(两个实现共用)
  LlmException                 带 DegradeReason 的失败
  ClassifyResult / DraftResult 实现返回的原始结果(字符串,不做主)
  LlmService                   韧性外壳:熔断器 → 调用 → 契约校验 → 落盘 → 打点 → 降级
  CircuitBreaker               连续失败计数 + 打开截止时间
  KeywordRuleClassifier        降级用的关键词规则(确定性)
  LlmCallLogService            落盘(REQUIRES_NEW)+ bindTicket
  LlmMetrics                   Micrometer 计数器 / 计时器 / gauge
  ClassifyOutcome / DraftOutcome   给调用方的最终结果(枚举、降级标志、模型名、耗时)
config/LlmProperties           llm.* 配置
ops/wiremock/mappings/*.json   挡板桩:关键词分类、[SLOW] [ERROR] [BAD_CATEGORY] [BAD_JSON]
```

`LlmService.classify` 的流程见 ADR-004 的表和类顶部的注释图。

### Java 语言层面

**接口 + 多实现 + 按类型注入**。`LlmService` 的构造器参数是 `LlmClient client`(接口类型),
容器里只有一个实现的 Bean(由 `@ConditionalOnProperty` 保证),注入的就是它。`LlmService`
的代码对两个实现完全无感——这是接口的意义:调用方依赖抽象。

**`RestClient`**(Spring 6.1+ 的同步 HTTP 客户端,替代 `RestTemplate`):

```java
restClient.post().uri("/chat/completions").contentType(APPLICATION_JSON).body(body)
          .retrieve().body(String.class);
```

流式 API,链式调用。非 2xx 默认抛 `RestClientResponseException`(4xx 是
`HttpClientErrorException`,5xx 是 `HttpServerErrorException`),网络层错误抛
`ResourceAccessException`(包着 `IOException` / `HttpTimeoutException`)。

**异常链遍历**(`LlmHttpSupport.isTimeout`):

```java
Throwable cur = t;
while (cur != null) {
    if (cur instanceof HttpTimeoutException || cur instanceof SocketTimeoutException) return true;
    cur = cur.getCause() == cur ? null : cur.getCause();
}
```

Java 异常可以层层包装(`getCause()`),超时异常通常在第二三层。`getCause() == cur` 的检查
防止自引用死循环。

**`Map.of(...)` 与不可变集合**。`Map.of("model", model, "temperature", 0, ...)` 创建不可变 Map,
最多 10 对;值类型混合时推断为 `Object`。Jackson 把它序列化成 JSON 对象。

**`AtomicInteger` 和 `volatile`**(`CircuitBreaker`):

```java
private final AtomicInteger consecutiveFailures = new AtomicInteger();
private volatile long openUntilEpochMs = 0L;
```

`AtomicInteger.incrementAndGet()` 是原子的(CAS),多线程同时失败不会丢计数。`volatile`
保证一个线程写了 `openUntilEpochMs` 其他线程立刻可见(否则可能读到 CPU 缓存里的旧值)。
Python 有 GIL 所以 `x += 1` 在 CPython 里"碰巧"安全;Java 没有 GIL,普通 `int++` 在多线程下
会丢更新。本项目没有用 `synchronized`——两个原语已经够,而且熔断器允许阈值附近的微小误差。

**`Optional.orElseGet(Supplier)`**(`LlmService.classify`):

```java
TicketPriority priority = parsedPriority.orElseGet(() -> {
    metrics.contractViolation(scene, "priority");
    return rules.priorityOf(category, lower(title, content));
});
```

`orElse(x)` 的 `x` 总是会被求值;`orElseGet(supplier)` 只在为空时才调用 supplier。
这里 supplier 有副作用(打点),必须用 `orElseGet`。

**`Locale.ROOT`**。`toLowerCase(Locale.ROOT)` 而不是 `toLowerCase()`:后者用系统默认
Locale,土耳其语环境下 `I` 的小写不是 `i`。关键词匹配要求确定性,所以显式 ROOT。

### Spring 层面

**`@ConditionalOnProperty`**:

```java
@Bean @ConditionalOnProperty(name = "llm.mode", havingValue = "real")
public LlmClient realLlmClient(...)
@Bean @ConditionalOnProperty(name = "llm.mode", havingValue = "mock", matchIfMissing = true)
public LlmClient wireMockLlmClient(...)
```

容器启动时读配置决定注册哪个 `@Bean` 方法。两个方法返回类型相同、条件互斥,所以永远只有
一个 `LlmClient` Bean。`matchIfMissing = true` 让完全不配 `llm.mode` 时默认走挡板——
这是"接口自动化默认走挡板"的实现。

**超时在哪一层**。`JdkClientHttpRequestFactory` 包着 JDK 11+ 的 `HttpClient`,
`setReadTimeout(3000ms)` 映射到每个 `HttpRequest.timeout()`——整体等待响应头的时间。
连接超时另外设 2 秒。不是线程池 + `Future.get`(ADR-004)。

**`LlmService` 为什么不是 `@Transactional`**。它的整个流程是 HTTP 等待 + 内存计算,唯一的
数据库操作是 `callLogService.record`,后者自己 `REQUIRES_NEW`。所以 `LlmService` 不持有
连接,3 秒等待期间连接池不受影响。`TicketService.create` 调它时也在事务外。

**Micrometer 指标**(`LlmMetrics`):

```java
Counter.builder("llm.fallback").tag("scene", ...).tag("reason", ...).register(registry).increment();
```

`register` 是幂等的:同名同 tag 返回已有的 Counter。名字里的 `.` 导出到 Prometheus 时变成
`_`,Counter 自动加 `_total` 后缀,所以 `llm.fallback` → `llm_fallback_total`。tag 变成
Prometheus 的 label。`Timer` 记录耗时分布,`publishPercentiles` 让客户端算 P50/P95/P99。
`Gauge` 是"当前值",传一个 `Supplier<Number>`,抓取时才调用。

**`MeterRegistry` 从哪来**。`micrometer-registry-prometheus` 在 classpath 上,Actuator 自动
配置一个 `PrometheusMeterRegistry` 并暴露 `/actuator/prometheus`。所有 `@Component` 直接
注入 `MeterRegistry` 即可。

### 自检问题

1. `llm.mode=real` 但 `LLM_API_KEY` 为空,创建工单会经历什么路径?最终分类来自哪里?
   `llm_call_log` 里 `degrade_reason` 是什么?
2. 标题带 `[SLOW]` 连续创建 5 张工单,第 6 张创建时 `LlmClient` 会被调用吗?`latency_ms`
   大约是多少?`llm_circuit_open_total` 是几?
3. 熔断打开 60 秒后自动闭合。如果 WireMock 此时仍然返回 500,第 61 秒开始的前几次调用
   会怎样?这和有半开状态的熔断器有什么行为差异?
4. `CircuitBreaker.recordFailure` 里 `incrementAndGet` 和 `set(0)` 之间没有加锁,两个线程
   同时到达阈值会发生什么?这个误差可接受的理由是什么?
5. 把 `LlmCallLogService.record` 的 `REQUIRES_NEW` 改成默认 `REQUIRED`,在 `draftReply`
   (无事务)和 `create`(前半段无事务)两个调用点分别会怎样?

---

## 10. 专题:输出不确定的依赖 vs 普通下游 HTTP 服务,测试策略的本质区别

> 这一节不讲代码,讲"为什么 LLM 依赖需要一套不同的测试思路"。

### 10.1 普通下游 HTTP 服务是什么样的

比如一个"查用户信息"的内部接口。它有三个性质:

1. **确定性**:同样的输入永远得到同样的输出。`GET /users/42` 今天返回张三,明天还是张三。
2. **契约是封闭的**:响应结构在接口文档里写死,字段、类型、枚举值都是有限集合。
3. **失败是二元的**:要么成功返回正确数据,要么失败(超时 / 5xx / 网络)。没有"成功返回了
   错误数据"这种状态——如果有,那是那个服务的 bug,不是你的问题。

因此测试策略是:

- **单测**:mock 它,断言你的代码在"成功 / 超时 / 5xx"三种情况下的行为。
- **集成测试**:挡板返回固定响应,断言你的系统端到端正确。
- **契约测试**:验证你解析的字段确实存在于对方的契约里。
- **不需要**测"它返回的数据对不对",那是对方的责任。

### 10.2 LLM 依赖哪里不一样

同样是 HTTP 调用,但四个性质全变了:

1. **非确定性**:同样的输入可能得到不同的输出。`temperature=0` 能压低但不能消除;供应商
   在背后换模型版本,输出分布就变了。你没法写 `assert category == "REFUND"` 这种断言——
   它今天过、下周可能不过,而且不过的时候你不知道是你的 bug 还是模型变了。
2. **契约是开放的**:你要求它返回 `BILLING|TECH|REFUND|OTHER`,它可能返回 `SPAM`、`billing`
   (小写)、`"REFUND."`(带句号)、`{"category": "REFUND", "reason": "..."}`(多字段)、
   或者一段解释性文字然后才是 JSON。**契约是你单方面声明的,对方不保证遵守**。
3. **失败是连续谱**:除了超时 / 5xx,还有"成功返回了越界值"、"成功返回了格式错的东西"、
   "成功返回了合法但明显错误的分类"。最后一种你的代码根本检测不出来。
4. **成本和延迟高一个量级**:每次调用几百毫秒到几秒、按 token 计费。测试不能像打普通接口
   那样随便打几千次。

### 10.3 由此推出的测试策略差异

| 维度 | 普通 HTTP 依赖 | LLM 依赖 |
|---|---|---|
| 断言什么 | 精确值(`== "张三"`) | **契约**(在枚举内、字段存在、类型正确)+ **韧性路径**(降级发生了、熔断打开了),不断言具体分类 |
| 挡板的角色 | 返回固定的正确响应 | **主动制造越界和畸形**:返回 `SPAM`、返回非 JSON、延迟 5 秒、返 500——测的是你的防御层 |
| 边界在哪 | 对方的接口边界 | **你自己的契约校验层**(`LlmService` 里的 `TicketCategory.parse` + 落 OTHER)。这一层才是被测对象,LLM 本身不是 |
| 降级路径 | 通常没有,失败就报错 | **必须有且必须是确定性的**(关键词规则),因为它是唯一能精确断言的路径 |
| 可观测性 | 请求日志 | 每次调用落盘:请求模型、**响应模型**、耗时、是否降级、原始返回值——不确定性意味着事后必须能回放"当时它到底返回了什么" |
| 质量指标 | 可用率、延迟 | 可用率、延迟 + **契约违反率**(`llm_contract_violation_total`)+ **降级率**(`llm_fallback_total`)——这两个是 LLM 特有的健康信号 |
| "对不对"谁负责 | 对方 | **分两层**:格式对不对是你的契约校验层负责;内容对不对是**模型评测**的事(离线、用标注集、算准确率),不进这个测试体系 |
| 回归的含义 | 你改了代码 | 你改了代码 **或** prompt 变了 **或** 供应商换了模型——后两者没有代码 diff,只能靠指标和落盘记录发现 |

### 10.4 落到这个项目里的具体设计

- **契约校验层是一等公民**:`LlmService` 里 `TicketCategory.parse(raw)` 返回 `Optional`,
  空就打点 + OTHER。这一段代码有自己的测试,而且是整个 LLM 路径里唯一能"精确断言"的代码。
- **挡板不是模拟供应商,是制造故障**:`[SLOW]`、`[ERROR]`、`[BAD_CATEGORY]`、`[BAD_JSON]`
  四个标记对应四种非正常返回;正常返回按关键词正则——它的"分类准确率"毫无意义,
  它存在的价值是**可控**。
- **降级路径是确定性的**:`KeywordRuleClassifier` 同样输入同样输出,接口测试可以断言
  `[SLOW]退款` → `REFUND / P1 / degraded=true / reason=TIMEOUT`,每个字段精确。
- **两个模型名都落盘**:请求的和响应的不一致,就是供应商在背后换了东西——这是普通 HTTP
  依赖不需要记录的字段。
- **指标区分"不可用"和"不可信"**:`llm_fallback_total` 涨是不可用(超时 / 熔断),
  `llm_contract_violation_total` 涨是不可信(能返回但越界)。两者的处置完全不同:前者等
  上游恢复,后者改 prompt 或换模型。熔断器只看前者(ADR-004)。
- **接口自动化默认走挡板**:因为真实 LLM 不确定、慢、要钱,CI 里跑它得到的是不稳定的
  红绿。真实调用只在人工验证 prompt 时手动切 `LLM_MODE=real`。

### 10.5 一句话版本

> 普通 HTTP 依赖的契约是对方保证的,我只测"对方失败时我怎么办";LLM 依赖的契约是我
> 单方面声明的,对方不保证遵守,所以我必须自己建一层契约校验,测试的重心从"对方的响应"
> 转移到"我的防御层":越界怎么归、超时怎么降、熔断怎么开、每次调用怎么留证据。
> 分类准不准是模型评测的事,不是接口测试的事——把这两件事分开,测试才能稳定。

### 10.6 补充(2026-09-20 联调之后):契约满足 ≠ LLM 路径在工作

10.3 的表里说 LLM 路径"断言契约,不断言具体分类"。联调时发现这句话少了半句
(docs/findings/20260920-联调发现-h2c升级导致LLM静默降级.md):所有 LLM 调用因为 h2c 问题全部失败、
全部走了关键词规则,而规则和挡板用同一套关键词——降级路径给出的分类和正常路径一模一样,
"分类在枚举内"这条断言全绿,整条 LLM 路径失效了三个小时没人知道。

所以 LLM 正常路径的用例有**三条固定断言**,缺一不可:

1. 响应里的分类 / 优先级在枚举内(契约);
2. `llm_call_log.degraded = 0` 且 `response_model` 非空(**这次是模型回答的,不是规则兜的**);
3. 挡板的请求日志里有这一次请求、请求体带标题(**请求真的发出去了、发对了**)。

降级路径反过来:`degraded = 1`、`degrade_reason` 精确到枚举值、`response_model` 为空、
指标按 reason 打点;超时用例还要看挡板确实收到了请求(等不到响应而已),熔断用例要看挡板收到 **0** 个请求。
`tests/api/test_llm_classify.py` 的 `_assert_not_degraded` 就是第 2、3 条的实现。

### 自检问题

1. 如果有人说"你用 `temperature=0`,输出就是确定的,为什么还要契约校验?"——怎么回答?
   至少给出两种 `temperature=0` 也会破坏契约的情况。
2. 挡板返回 `{"category": "refund"}`(小写),`TicketCategory.parse` 会怎么处理?这算契约
   违反吗?如果供应商某天开始返回 `"REFUND "`(尾随空格)呢?你的解析层对哪些"轻微越界"
   是宽容的,对哪些是严格的?这个宽容边界写在哪里?
3. "分类准确率"应该由谁、用什么方法、在什么时候测?为什么它不能进 CI?
4. 一个只有"成功 / 失败"两种状态的普通依赖,它的挡板需要几种桩?LLM 挡板需要几种?
   多出来的那些各自对应你代码里的哪一段防御?
5. `llm_call_log` 里 `request_model` 和 `response_model` 不一致了,但分类准确率没变,
   要不要告警?如果准确率变了但两个模型名一致呢?这两种情况分别说明什么?

---

## 11. 权限模型:认证拦截器 + Service 层授权

### 解决什么问题

AGENT 只能读写自己的单,LEADER 本组,ADMIN 全权;越权校验在 Service 层,是水平 / 垂直越权
安全用例的载体(ADR-007)。

### 代码怎么组织

```
auth/
  CurrentUser        record(id, username, displayName, role, groupId)
  UserContext        ThreadLocal<CurrentUser> 的静态封装:set / get / require / clear
  AuthInterceptor    preHandle:X-User-Id → AgentService → UserContext.set;afterCompletion:clear
  AccessChecker      checkRead / checkWrite / checkGrab / checkAssign / requireRole
agent/
  AgentCache         @Cacheable 查坐席快照(独立 Bean,原因见下)
  AgentService       findCurrentUser / getOrThrow
  AgentController    GET /api/agents/me
config/WebMvcConfig  注册拦截器到 /api/**
```

认证发生在拦截器,授权发生在每个 Service 方法开头:

```java
CurrentUser user = UserContext.require();   // 没登录 → 401
Ticket ticket = getOrThrow(id);             // 不存在 → 404
access.checkWrite(user, ticket);            // 不是你的 → 403/40301;角色不够 → 403/40302
```

### Java 语言层面

**`ThreadLocal<T>`**:

```java
private static final ThreadLocal<CurrentUser> HOLDER = new ThreadLocal<>();
HOLDER.set(user);  HOLDER.get();  HOLDER.remove();
```

每个线程一份独立的值,和 Python 的 `threading.local()` 一样。Tomcat 用线程池,线程处理完
一个请求会去处理下一个——不 `remove()` 的话下一个请求会看到上一个用户。`afterCompletion`
在响应写完后一定被调,包括 Controller 抛异常的情况。

**静态工具类**。`UserContext` 全是静态方法,私有构造器防止实例化,`final` 防止继承。
Python 里就是一个模块级函数集合。

**switch 表达式**(Java 14+,`AccessChecker.canAccess`):

```java
return switch (user.role()) {
    case ADMIN -> true;
    case LEADER -> Objects.equals(ticket.getGroupId(), user.groupId());
    case AGENT -> ticket.getAssigneeId() != null && Objects.equals(ticket.getAssigneeId(), user.id());
};
```

对枚举**穷举**:漏一个分支编译不过。加一种角色时编译器会指出所有需要处理的地方。
没有 `break`,不会贯穿。

**可变参数**。`requireRole(CurrentUser user, Role... allowed)`——`Role...` 是 `Role[]` 的语法糖,
调用时 `requireRole(user, LEADER, ADMIN)`。`Arrays.stream(allowed).noneMatch(user::is)`:
`user::is` 是**绑定了接收者的方法引用**,等价于 `r -> user.is(r)`。

### Spring 层面

**`HandlerInterceptor` 三个回调**:`preHandle`(进 Controller 前,返回 false 中断)、
`postHandle`(Controller 返回后、视图渲染前,REST 里几乎不用)、`afterCompletion`
(响应完成后,包括异常)。注册在 `WebMvcConfigurer.addInterceptors`,`addPathPatterns("/api/**")`
只拦业务接口,`/actuator/**` 不拦(Prometheus 抓取不带用户头)。

**拦截器里直接写响应**。`preHandle` 返回 false 时 Spring 不会再做任何事,401 的 JSON 体
要自己 `response.getWriter().write(...)`。这就是为什么它不经过 `GlobalExceptionHandler`——
advice 只处理 Controller 抛出的异常,拦截器在 Controller 之外。

**`@Cacheable` 的代理失效**(`AgentCache` 为什么单独一个类):

```java
// AgentService 里
AgentSnapshot s = agentCache.findSnapshot(id);   // agentCache 是代理 → 先查 Redis
// 如果写成同类内 this.findSnapshot(id)         // 走原对象 → 每次都查库,缓存形同虚设
```

和 `@Transactional` 是同一个机制、同一个坑。判断标准:**注解方法的调用者是不是从容器里
拿到的引用**。

**缓存的 key 和 unless**。`@Cacheable(cacheNames = "agents", key = "#id", unless = "#result == null")`
——`#id` 是 SpEL,取方法参数;`unless` 在方法执行后求值,结果为 null 时不缓存(否则新建
坐席后十分钟内都被当成不存在)。Redis 里的 key 是 `ticketqa:cache:agents::3`。

**缓存序列化**(`CacheConfig`)。默认 JDK 序列化在 redis-cli 里是乱码、改类就反序列化失败。
换成 `GenericJackson2JsonRedisSerializer` + 带类型信息(`@class` 字段),JSON 可读。
`activateDefaultTyping` 限定只信任 `com.ticketqa.` 下的类——反序列化任意类型是 RCE 漏洞的
经典入口。

### 自检问题

1. AGENT 用自己的 `X-User-Id` 请求 `GET /api/tickets/{别人的单}`,拦截发生在哪个类哪一行?
   错误码是什么?如果那张单根本不存在,错误码又是什么?这两个响应泄露了什么信息?
2. AGENT 调 `POST /api/tickets/{自己的单}/assign`,`checkWrite` 过了吗?最终被哪个检查拦下?
   错误码是 40301 还是 40302?为什么这叫垂直越权?
3. 把 `AuthInterceptor.afterCompletion` 里的 `UserContext.clear()` 去掉,用 ADMIN 发一个请求、
   再发一个没有 `X-User-Id` 头的请求,第二个请求会怎样?为什么"可能"而不是"一定"?
4. 把 `AgentCache.findSnapshot` 的逻辑搬回 `AgentService` 并保留 `@Cacheable`,
   `findCurrentUser` 调用它时缓存还有效吗?怎么在不看代码的情况下从 Redis 里验证?
5. LEADER 能改派本组工单给本组坐席。如果一个 LEADER 把 `assigneeId` 填成另一个组的坐席,
   哪一行拦住?错误码是什么?这是权限问题还是参数问题?

---

## 12. 附件上传

### 解决什么问题

白名单 `jpg/png/pdf/txt`、≤ 5MB、落本地目录、UUID 重命名、扩展名 + MIME 双校验(ADR-008)。

### 代码怎么组织

```
attachment/
  AttachmentController   POST /api/tickets/{id}/attachments (multipart, 字段名 file);GET 列表
  AttachmentService      四步校验 → 落盘 → 入库;@PostConstruct 建目录
  FileTypeSniffer        魔数表 + UTF-8 文本启发式
  AttachmentVO           响应
```

### Java 语言层面

**try-with-resources**:

```java
try (InputStream in = file.getInputStream()) {
    Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
} catch (IOException e) {
    throw new UncheckedIOException("附件写入失败", e);
}
```

括号里声明的资源在块结束时自动 `close()`,无论正常结束还是抛异常——Python 的 `with`。
多个资源用分号分隔,关闭顺序与声明相反。`InputStream` 实现了 `AutoCloseable`,所以能放
进去。`readHead` 里第二次 `getInputStream()` 是另一个流,也单独 try-with-resources。

**受检异常的转换**。`Files.copy` 抛 `IOException`(受检),Service 方法不想在签名上写
`throws IOException`(会传染到 Controller),所以包成 `UncheckedIOException`(非受检)。
`GlobalExceptionHandler` 的兜底处理器把它变成 500。

**`java.nio.file.Path` / `Files`**。`Paths.get(dir).toAbsolutePath().normalize()` 解析成绝对
路径并去掉 `..`;`baseDir.resolve(storedName)` 拼路径;`Files.createDirectories` 相当于
`mkdir -p`。不用 `java.io.File` 的字符串拼接。

**字节与字符**。`byte[] head = in.readNBytes(8192)` 读原始字节;魔数比较用 `Arrays.equals`
的区间重载;`(byte) 0xFF`——Java 的 `byte` 是有符号的(-128~127),`0xFF` 是 255,必须强转。
`head[i] & 0xC0` 按位与,判断 UTF-8 续字节(`10xxxxxx`)。

**`CharsetDecoder` 严格模式**:

```java
StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT)
        .decode(ByteBuffer.wrap(bytes));
```

`new String(bytes, UTF_8)` 遇到非法序列会静默替换成 `�`,判断不了"是不是文本";
`CharsetDecoder` 用 REPORT 模式遇到非法序列抛 `CharacterCodingException`。

**record 做私有数据结构**。`FileTypeSniffer` 里 `private record Magic(String ext, byte[] bytes)`
——record 可以是嵌套的、私有的,用来给"扩展名 + 魔数"这个二元组起个名字。

### Spring 层面

**`MultipartFile`**。Spring 把 multipart 请求解析后,`@RequestPart("file")` 拿到对应
part:`getOriginalFilename()`、`getContentType()`(客户端声明的)、`getSize()`、
`getInputStream()`。`spring.servlet.multipart.max-file-size=8MB` 是容器层上限,超过它
Spring 在进 Controller 前就抛 `MaxUploadSizeExceededException`——所以设得比业务上限 5MB 大,
让 5~8MB 的文件走业务校验拿到明确错误码。

**`@PostConstruct`**。依赖注入完成后、Bean 可用前调用一次。`ensureDir` 在这里建目录:
构造器里做的话 `props` 已经注入了其实也行,但 `@PostConstruct` 语义更清楚——"初始化动作",
而且允许抛受检异常(`throws IOException`)。

**`consumes = MULTIPART_FORM_DATA_VALUE`**。限定这个映射只接 multipart 请求,发 JSON 过来
返回 415 而不是进方法后 NPE。

**上传权限**。`upload` 调 `ticketService.getOrThrow` + `access.checkWrite`,复用工单的权限
规则——AGENT 只能给自己的单传附件。

### 自检问题

1. 用 `curl -F 'file=@shell.php;filename=shell.jpg;type=image/jpeg'` 上传一个 PHP 脚本,
   四步校验里哪一步拦下它?错误码和消息是什么?如果把文件开头加上 `FF D8 FF` 三个字节呢?
2. 上传一个恰好 5,242,880 字节的 png 会成功吗?5,242,881 呢?8,388,609 呢?三个响应的错误码
   分别是什么,由哪个类产生?
3. `readHead` 和 `Files.copy` 各自打开了一次 `getInputStream()`。如果 `MultipartFile` 的底层
   是一个只能读一次的流,会发生什么?Spring 默认的实现是怎么处理的?
4. 把 `UncheckedIOException` 改成直接 `throws IOException`,编译错误会出现在哪些方法上?
   为什么受检异常会"传染"?
5. 一个合法的 UTF-8 文本文件,内容以 `%PDF-1.4` 开头、扩展名 `.txt`,会被判成什么?
   这是 bug 还是可接受的边界?反过来一个真 PDF 改名 `.txt` 呢?

---

## 13. 可观测性:Actuator、Micrometer、Prometheus、日志

### 解决什么问题

把服务内部状态(健康、指标、LLM 降级次数、熔断状态、MQ 发送 / 消费计数)以 Prometheus
格式暴露出来;每条日志带 traceId。Grafana 看板不在仓库内。

### 代码怎么组织

```
application.yml   management.endpoints.web.exposure.include: health,info,prometheus,metrics
                  logging.pattern.console 含 %X{traceId};logging.file.name
llm/LlmMetrics                    llm_* 指标
mq/TicketEventPublisher           mq_event_published_total / mq_event_publish_failed_total
mq/IdempotentConsumerSupport      mq_event_consumed_total / mq_event_duplicate_total
sla/SlaScanner, SlaEscalationService   sla_scan_total / sla_escalated_total / sla_escalation_skipped_total / sla_scan_lock_unavailable_total
ops/prometheus/prometheus.yml     抓 host.docker.internal:8080/actuator/prometheus
```

### 自定义指标一览

| 指标(Prometheus 名) | 类型 | 标签 | 含义 |
|---|---|---|---|
| `llm_fallback_total` | Counter | scene, reason | 降级到规则的次数(规格点名) |
| `llm_circuit_open_total` | Counter | scene | 熔断器被打开的次数(规格点名) |
| `llm_contract_violation_total` | Counter | scene, field | 返回值越界次数 |
| `llm_call_duration_seconds` | Timer | scene, outcome | 调用耗时分布,含 P50/95/99 |
| `llm_circuit_state` | Gauge | — | 1 打开 0 闭合 |
| `mq_event_published_total` | Counter | — | 发到 MQ 的事件数 |
| `mq_event_publish_failed_total` | Counter | — | 提交后发送失败(消息丢失) |
| `mq_event_consumed_total` | Counter | — | 首次消费成功 |
| `mq_event_duplicate_total` | Counter | — | 去重表拦下的重复 |
| `sla_scan_total` | Counter | — | 扫描轮次 |
| `sla_escalated_total` | Counter | — | 自动升级的工单数 |
| `sla_escalation_skipped_total` | Counter | — | 条件更新影响 0 行 |
| `sla_scan_lock_unavailable_total` | Counter | — | Redis 不可用、未持锁扫描 |

加上 Spring Boot 自带的:`http_server_requests_seconds`(每个接口的耗时 / 状态码)、
`hikaricp_connections_*`(连接池)、`jvm_*`、`rabbitmq_*`、`lettuce_*`。

### Java / Spring 层面

**Actuator**。`spring-boot-starter-actuator` 提供 `/actuator/*` 端点;`exposure.include` 控制
哪些暴露到 HTTP(默认只有 health)。`/actuator/health` 带 `show-details: always`,会显示
db / redis / rabbit 各自的状态——故障注入时先看这里。

**Micrometer 是门面**。代码只依赖 `MeterRegistry` 接口,`micrometer-registry-prometheus`
提供实现。换成其他后端(Datadog、OTLP)只换依赖不改代码。命名约定:Micrometer 里用 `.`
分隔(`llm.fallback`),各后端按自己的规则转换;Prometheus 转成 `_`,Counter 加 `_total`,
Timer 加 `_seconds` 并拆成 `_count / _sum / _max` 三条。

**指标对象的生命周期**。`Counter.builder(...).register(registry)` 每次调用返回同一个对象
(按名字 + 标签查重),所以 `LlmMetrics` 里每次打点都 builder 一遍是可以的,只是比缓存
成字段稍慢。Publisher / Consumer 里把 Counter 存成 final 字段是另一种写法,两种都对。

**标签基数**。`reason` 只有 4 个值、`scene` 2 个,乘起来 8 个时间序列,没问题。
**永远不要**把 ticketId、userId 这种高基数值当标签——每个值一条时间序列,Prometheus 会爆。

**日志**。SLF4J 是门面,Logback 是实现(Spring Boot 默认)。`log.info("工单创建 id={} no={}", id, no)`
的 `{}` 占位符**延迟格式化**:日志级别不够时不拼字符串。`logging.pattern.console` 里
`%X{traceId:-}` 取 MDC 的 traceId,没有时打 `-`。`logging.file.name` 同时写文件,
`.gitignore` 排除了 `logs/`。`e.printStackTrace()` 一处都没有——它绕过日志框架、
没有 traceId、没有级别、不进文件。

**Prometheus 抓取**。`prometheus.yml` 里 `host.docker.internal:8080` 是容器访问宿主机的地址
(Docker Desktop 自带;Linux 靠 compose 里的 `extra_hosts` 映射)。服务跑在宿主机
`mvn spring-boot:run` 时用它;跑在 compose 的 `app` profile 里改成 `app:8080`。

### 自检问题

1. `llm.fallback` 在 Micrometer 里注册,到 `/actuator/prometheus` 里变成什么名字?为什么
   多了 `_total`?`llm.call.duration` 变成了几条时间序列?
2. `docker compose stop redis` 后 30 秒内,`/actuator/health` 会显示什么?SLA 扫描还会跑吗?
   哪个指标能证明它跑了?
3. 如果把 `ticketId` 加成 `llm_fallback_total` 的标签,压测创建 1 万张工单后 Prometheus
   会发生什么?
4. `http_server_requests_seconds_count{uri="/api/tickets/{id}/grab",status="409"}` 这条时间序列
   的 `uri` 为什么是模板 `{id}` 而不是实际的 `/api/tickets/17/grab`?
5. 一条 MQ 消费日志里的 traceId 和触发它的 HTTP 请求的 traceId 一样吗?它是怎么从请求线程
   到达消费者线程的?如果消息体里没有 traceId 会打出什么?

---

## 14. 测试体系:单测、切片、接口自动化、安全用例、CI

> 本节对应 v0.2-tests 阶段;14.7 是修复阶段的增补。读者定位不变:Python 熟、Java 弱。pytest 那半边只讲"为什么这么设计",
> 不讲语法;JUnit / Mockito / Spring 测试切片那半边讲到语言和框架层面。

### 14.1 解决什么问题

被测服务有五条关键链路(状态机、SLA、LLM 降级、MQ 幂等、权限 / 附件),每条都有"边界"——
闭区间的 `<=`、第 5 次失败、7 天整、5MB 整、25 格非法流转。测试体系要做到三件事:

1. **每个边界都被精确地打到**,精度到毫秒 / 字节 / 一次调用——这是单测的活。
2. **每条链路在真容器上真的通**,包括接口看不见的部分(库表、指标、挡板日志)——这是接口自动化的活。
3. **有人改坏了能自动响**——这是 CI 和覆盖率门禁的活。

一张分工表(哪一层测什么,是本节最重要的一张表):

| 被测点 | 单测(JUnit + Mockito) | 切片(H2 / WebMvc) | 接口自动化(pytest,真容器) |
|---|---|---|---|
| 状态机 36 格 | ✓ 全部,毫秒级 | | ✓ 全部,走真实接口链造状态 |
| 重开 7 天窗口 | ✓ ±1ms / ±1s | | 6.9 天 / 7 天零 1 分(改库) |
| SLA `sla_deadline <= now` | | ✓ H2 跑真 SQL,±1ms | now−1s / now+3s 两侧夹逼(真 MySQL) |
| SLA 升级 / 防重复 | ✓ 条件更新影响行数 | ✓ 条件更新真 SQL | ✓ 扫描接口、审计、指标、MQ |
| LLM 韧性外壳(超时 / 越界 / 熔断) | ✓ Mock 客户端 + 拨表 | | ✓ 挡板故障标记 + `llm_call_log` + 指标 + 挡板请求日志 |
| LlmClient 解析 | | ✓ MockRestServiceServer | (传输层:h2c、超时,在这层) |
| MQ 幂等 | ✓ 模拟唯一键冲突 | ✓ 真唯一键抛什么异常 | ✓ 管理 API 真实重投 |
| 权限判定表 | ✓ 26 行 | | ✓ 7 接口 × 3 入侵者 |
| 附件三层校验 | ✓ 每层无效类 + @TempDir 落盘 | | ✓ 真上传 + 落盘 + 绕过 |
| HTTP 边界(401 / 400 / 409 / 信封 / traceId) | | ✓ @WebMvcTest | ✓ |

原则一句话:**精度归单测,集成归接口;能在进程内用真实现测的(SQL、HTTP 解析)用切片,不 Mock 掉被测物。**

### 14.2 代码怎么组织

```
service/src/test/java/com/ticketqa/
├── support/            TestFixtures(造数)、MutableClock(拨表)、@H2SliceTest(组合注解)
├── statemachine/       TransitionTableTest(36 格)、TicketStateMachineTest(守卫 + 进入动作)
├── sla/                SlaDeadlineTest、SlaOverdueQueryH2Test(真 SQL)、SlaEscalationServiceTest、SlaScannerTest
├── llm/                LlmServiceTest、CircuitBreakerTest、KeywordRuleClassifierTest、WireMockLlmClientTest、LlmHttpSupportTest
├── mq/                 IdempotentConsumerSupportTest、MqMessageDedupH2Test、TicketEventPublisherTest
├── auth/ attachment/   AccessCheckerTest(判定表)、AttachmentServiceTest、FileTypeSnifferTest
├── ticket/             TicketServiceTest(编排)、TicketControllerWebTest(@WebMvcTest)
└── audit/              PersistenceHelpersTest
src/test/resources/h2/schema.sql   H2 用的精简 DDL

tests/
├── pytest.ini  conftest.py(三层 fixture + circuit 排序)  requirements.txt
├── api/framework/      config / client / response(断言 DSL)/ factory / db / wiremock / metrics / mq / waits
├── api/config/         local.env  ci.env
├── api/test_*.py       10 个文件,按链路分
├── security/test_*.py  5 个文件:水平 / 垂直越权、注入、附件绕过、脱敏
└── perf/               grab_race.jmx  ticket_create.jmx  run_ladder.sh  README
.github/workflows/ci.yml   unit → api 两个 job
```

### 14.3 Java 语言层面

**`@ParameterizedTest` + `@MethodSource`:一条方法跑 36 次。**
Python 里是 `@pytest.mark.parametrize`。Java 这边参数来源是一个返回 `Stream<Arguments>` 的静态方法:

```java
static Stream<Arguments> allCells() {
    return Arrays.stream(TicketStatus.values())
            .flatMap(from -> Arrays.stream(TicketStatus.values())
                    .map(to -> Arguments.of(from, to, SPEC.get(from).contains(to))));
}
```

`flatMap` 是把"每个 from 映射成一个 to 的流"再拍平成一个流——Python 的双层列表推导。
`Arguments.of(...)` 把三个值打包成一行参数。`@MethodSource("allCells")` 通过方法名字符串找到它(反射),
所以方法必须是 `static`。`legalCells()` 和 `illegalCells()` 是在 `allCells()` 上再 `filter` 一次——
36 格、11 合法、25 非法,三组用例共享同一个数据源,规格改一行三组一起变。

**`@CsvSource`:参数直接写在注解里。** `"申请退款, 订单重复扣款, REFUND, P1"` 一行四列,按逗号切,
JUnit 会把 `REFUND` 字符串转成枚举 `TicketCategory.REFUND`(隐式转换)。值里有逗号或空格要用单引号包。

**`@Nested`:内部类分组。** `LlmServiceTest.Circuit`、`TicketServiceTest.Grab` 是非静态内部类,
它们能访问外层的 `@Mock` 字段和 `@BeforeEach`,报告里按组显示。Python 里的对应是 `class TestGrab:` 嵌套——
但 Java 的内部类持有外层实例的引用(`this$0`),所以外层的 setUp 对内层每个测试都跑一遍。

**`@ExtendWith(MockitoExtension.class)` + `@Mock`:Mock 是怎么造出来的。**
`@Mock private TicketMapper ticketMapper;` 声明后,扩展在每个测试方法前用 Mockito 生成一个
`TicketMapper` 接口的动态实现(字节码生成,不是 Python 的 `MagicMock` 那种运行时属性拦截),
默认所有方法返回 null / 0 / 空集合。`when(mapper.selectById(7L)).thenReturn(t)` 打桩;
`verify(mapper, never()).updateById(any())` 验证调用。

**Mockito 的两个坑,都在本项目踩过:**

1. **重新打桩要用 `doReturn/doAnswer`。** `when(client.classify(...)).thenReturn(x)` 会真的调用一次
   `client.classify` 来"记录"要打桩的方法;如果上一个桩是"抛异常",这一次调用就在 `when` 里炸了。
   熔断恢复用例要在同一个测试里先失败后成功,必须写 `doReturn(x).when(client).classify(...)`——
   这种写法不触发真实调用。(`LlmServiceTest.clientReturns` 的注释。)
2. **严格桩(strict stubs)。** `MockitoExtension` 默认开启:一个测试里打了桩但没用到,测试结束会报
   `UnnecessaryStubbingException`。放在 `@BeforeEach` 里、只有部分测试用的桩要包成
   `lenient().when(...)`。Python 的 mock 没有这个检查,所以第一次遇到会以为是测试写错了。

**重载方法与 `any()`。** `ApplicationEventPublisher.publishEvent` 有 `(Object)` 和 `(ApplicationEvent)` 两个重载,
`verify(events).publishEvent(any())` 编译器会选更具体的 `ApplicationEvent` 版本,而代码调的是 `Object` 版本——
验证永远"没调过"。写成 `any(Object.class)` 才落到对的重载。Python 没有重载,不会有这个问题;
MyBatis-Plus 的 `BaseMapper.insert(T)` / `insert(Collection<T>)` 同理,要写 `any(Ticket.class)`。

**`ArgumentCaptor`:抓住传给 Mock 的参数。**

```java
ArgumentCaptor<LlmCallLog> captor = ArgumentCaptor.forClass(LlmCallLog.class);
verify(callLogService, atLeastOnce()).record(captor.capture());
LlmCallLog log = captor.getValue();      // 最后一次调用的参数
```

用来断言"落盘的记录里 degraded=true、reason=TIMEOUT"——被测方法不返回这个对象,只能从 Mock 的入参里抓。
Python 里是 `mock.call_args`。

**`Clock` 抽象类与 `MutableClock`。** `java.time.Clock` 是抽象类(不是接口),子类要实现
`instant()` / `getZone()` / `withZone()` 三个方法。`MutableClock.advance(Duration.ofSeconds(60))`
让熔断器"过了 60 秒",测试 10 毫秒跑完。这依赖第 7 节的决定:所有 `now` 都来自注入的 `Clock`。
`Clock.fixed(instant, zone)` 是 JDK 自带的"钉死"版本,`TestFixtures.fixedClock()` 用它。

**`@TempDir`。** JUnit 给每个测试一个临时目录(`Path` 字段自动注入),测试结束自动删。
`AttachmentServiceTest` 用它做真实落盘,断言 UUID 文件确实写在目录里、路径穿越的文件没有逃出去。
Python 的 `tmp_path` fixture。

**`assertThatThrownBy(...).isInstanceOf(...).extracting(e -> ...)`:AssertJ 的链式断言。**
`extracting` 接一个 lambda 把异常转成错误码再比较。`satisfies(e -> {...})` 在链里插一段自定义断言。
Python 里对应 `with pytest.raises(X) as ei: ...; assert ei.value.code == ...`。

**组合注解 `@H2SliceTest`。** `public @interface H2SliceTest` 定义一个注解,它自己被
`@MybatisPlusTest`、`@AutoConfigureTestDatabase`、`@Import`、`@TestPropertySource` 四个注解修饰;
Spring 的注解处理会递归找"元注解",所以打一个 `@H2SliceTest` 等于打了那四个。
Python 里把多个装饰器合成一个装饰器函数是同一个意思。注解里还能嵌一个 `@TestConfiguration` 静态类提供 `Clock` Bean。

### 14.4 Spring 层面

**测试切片 vs 整个容器。** `@SpringBootTest` 起完整应用上下文——要连 MySQL、Redis、RabbitMQ。
切片注解只装配一层:

| 注解 | 装配什么 | 不装配什么 | 本项目用在 |
|---|---|---|---|
| `@WebMvcTest(TicketController.class)` | DispatcherServlet、这个 Controller、所有 `@ControllerAdvice`、`Filter`、`HandlerInterceptor`、`WebMvcConfigurer`、Jackson | Service、Mapper、数据源、缓存、MQ | HTTP 边界:401 / 400 / 409 / 信封 / traceId |
| `@MybatisPlusTest` | DataSource、SqlSessionFactory、`@MapperScan` 到的 Mapper、事务管理器 | Web、Service、Redis、MQ | 两条手写 SQL、去重表唯一键 |

切片扫描组件时用 `TypeExcludeFilter` 把不相关的 `@Component` 排除掉,**`@Configuration` 类也被排除**——
所以 `@WebMvcTest` 里要 `@Import(JacksonConfig.class)` 才有 `yyyy-MM-dd HH:mm:ss` 的日期格式;
`@MybatisPlusTest` 里要 `@Import(MybatisPlusConfig.class)` 才有 `@MapperScan` 和自动填充的 `MetaObjectHandler`。
漏 import 的症状:前者日期变成数组 `[2026,9,20,10,0]`,后者 `TicketMapper` Bean 找不到。

**`@MockBean`。** 在切片里把 `TicketService` 换成 Mockito Mock 并注册进容器,Controller 注入到的就是它。
和 `@Mock` 的区别:`@Mock` 是纯 Mockito 对象,`@MockBean` 是容器里的 Bean(会触发上下文缓存失效——
每种不同的 `@MockBean` 组合都是一个新的上下文,测试类多了启动会变慢)。

**`@MybatisPlusTest` 自带 `@Transactional`。** 每个测试方法在事务里跑、结束回滚,所以 `SlaOverdueQueryH2Test`
的 30 个方法各自 insert 的数据互不可见。这和第 5 节讲的 `@Transactional` 是同一个代理机制,
只是测试框架把"回滚"当默认行为。想看数据真的提交要加 `@Commit`。

**H2 的 MySQL 兼容模式。** JDBC URL `jdbc:h2:mem:ticketqa;MODE=MySQL;DATABASE_TO_LOWER=TRUE`:
`MODE=MySQL` 让 `AUTO_INCREMENT`、反引号、`LIMIT` 等语法被接受;`DATABASE_TO_LOWER` 让列名大小写行为像 MySQL。
`spring.sql.init.schema-locations=classpath:h2/schema.sql` + `mode=always` 让 Spring 在数据源建好后执行建表脚本。
`@AutoConfigureTestDatabase(replace = NONE)` 很关键:默认的 `replace = ANY` 会把你配的数据源**替换成**
一个通用内存库,你的 URL 和 MODE 全部作废。

**`MockRestServiceServer.bindTo(RestClient.Builder)`。** Spring 自带的 HTTP 层挡板:它替换掉 `RestClient`
里的 `ClientHttpRequestFactory`,请求不走 socket,直接匹配你 `expect(...)` 的规则并返回 `andRespond(...)` 的内容。
测的是"我的代码怎么发请求、怎么解析响应",不是网络。所以它测不到超时和 h2c——那两个在接口自动化里对着真 WireMock 容器测。

**为什么 `TicketServiceTest` 用真的 `AccessChecker` / `TransitionTable`,而 Mock `TicketMapper`?**
按"有没有外部依赖"分:前两个是纯对象,Mock 它们等于测试里再实现一遍规则,还可能实现错;
`TicketMapper` 背后是数据库,Mock 它才让测试不依赖环境。Mock 的边界应该画在 I/O 上,不是画在"每个依赖"上。

### 14.5 pytest 那半边:只讲设计

**四层封装(ADR-012)。** `ApiClient` 只拼请求不断言;`ApiResponse.expect` 是链式断言 DSL;
`TicketFactory` 走真实接口造数、结束硬删五张表;`db / wiremock / metrics / mq` 是旁路取证。
所有 LLM 正常路径用例都断三件事:响应分类正确、`llm_call_log.degraded=0 且 response_model 非空`、
挡板收到了带该标题的请求——第一件事单独成立时,LLM 路径可能整个失效(第 10.6 节)。

**fixture 三层。** session:配置、各身份客户端、旁路客户端、就绪检查(服务 UP、6 个种子坐席、WireMock 健康,
任一不满足 `pytest.exit`);module:只读共享工单;function:`tickets` 工厂 + `metrics_before` 快照。
分层依据是"谁会改它"。

**熔断的隔离。** `circuit` 标记的用例被 `pytest_collection_modifyitems` 排到最后;模块前后各等 `llm_circuit_state` 回 0;
其他降级用例结束时做一次成功调用清零连续失败计数(`reset_streak`)。没有给服务加重置接口。

**已知问题挂法(ADR-014)。** 确认是缺陷的用 `xfail(strict=True, reason="KI-xxx")`,修好会 XPASS 变红;
旁边放一条通过的事实记录用例。观察项不挂 xfail。

**Allure。** `--alluredir` 收集结果,每个请求 / 响应作为附件、每个断言作为 step;
本地 `allure serve tests/allure-results`,CI 里生成 HTML 归档为 artifact(ADR-015)。

### 14.6 CI(ADR-011 / ADR-015)

`unit` job:`mvn verify`(编译 + 330 个单测 + JaCoCo 全量兜底 70/60)→ `diff-cover` 对 JaCoCo XML 算改动行覆盖率 ≥ 80%。
`api` job:复用 `ops/docker-compose.yml` 起四个中间件、等 healthy → `java -jar` 起服务、等 health UP → 连接池预热(ADR-021)→
`coverage run -m pytest`(api + security,coverage.py 量 framework 自身;含并发 / 容量 / 故障注入用例)→ diff-cover 同样 80% → Allure 生成并归档 →
服务日志归档(按 traceId 对账)。两个 job 串行,单测红了不起环境。

覆盖率的分母排除了实体 / DTO / 配置 / 启动类,排除理由逐条在 ADR-011——"排除是为了让数字有意义,不是为了让数字好看"。

### 14.7 修复阶段新增的用例层(2026-09-21)

压测和故障注入之后,测试体系补了四类以前没有的东西,pytest 侧的设计要点:

- **并发正确性**(`test_concurrency.py`,`framework/concurrency.py`):N 个线程各持独立 `requests.Session`,
  在 `threading.Barrier` 上等齐后同时发——同一个 Session 会复用连接把请求串行化,"同时"就是假的;线程池启动有先后,
  不等齐前两个请求的间隔可能已经大于一次抢单事务(~13 ms),竞态窗口就错过了。断言只写"恰好 1 个 200",
  不写 409 的分布(ADR-021),每条用例前 `warmed_pool` 把 HikariCP 撑满。
- **审计序列反向断言**(`framework/audit.py`):第 k 行 to == 第 k+1 行 from、首行 from 为空、末行 to == 当前状态、
  每条边在迁移表里。正向断言("有没有那一行")在修复前的脏数据上也能通过,反向断言才能发现 KI-009。
  压测工具 `reset_grabbed.py` 因此改成重置时补一条审计——**工具自己不能制造断裂**。
- **容量契约**(`test_capacity.py`):断言"不丢、不重复、预算内清完",不断言"消费速率 ≥ 190/s"——190 是本机的数字。
  后台采样线程的停止标志不能叫 `_stop`:`threading.Thread` 自己有 `_stop()` 方法,覆盖它会在 `join` 时炸。
- **故障注入**(`test_fault_injection.py`,`framework/faults.py`):`docker compose stop/start` 的命令模板来自配置
  (本机是 `wsl.exe … docker compose`,CI 是 `docker compose`),没配就 skip;`fault` 标记排在 `circuit` 之后、整个会话最末;
  每一步 `wait_until` 等条件,实测秒数挂进 Allure(ADR-020 的 SLO)。RabbitMQ 那条专门断言"恢复后**没有**补投"——
  把 ADR-018 的决定钉成契约。

JUnit 侧新增:`GrabLockTest`(判定表:拿到 / 被占 / Redis 挂)、`TicketNoGeneratorTest`(100 万个同毫秒单号无重复 +
32 bit 对照必碰撞)、`LlmMetricsTest`(标签组合预注册)、`SlaOverdueQueryH2Test` 新增条件更新与乐观锁的真 SQL 用例
(含 KI-009 的 SQL 级复现)。第 6 节讲了 H2 切片里 MyBatis 一级缓存的坑。

---

### 自检问题

1. `TransitionTableTest` 里的 `SPEC` 是规格的独立抄本,`TransitionTable.EDGES` 是实现。如果把测试改成直接引用
   `EDGES` 来生成 36 格,测试还会跑过,但它失去了什么?什么情况下这种"用实现测实现"会让缺陷永远发现不了?
2. `SlaOverdueQueryH2Test` 在 H2 上证明了 `sla_deadline <= now` 的闭区间;`test_sla.py` 在真 MySQL 上只能做到
   now−1s / now+3s 两侧。列出至少两种 H2 通过、MySQL 会不一样的情况——这些差异是否落在这两条 SQL 的语义里?
3. `LlmServiceTest.recoversAfterOpenWindow` 先让客户端连续失败 5 次,再改成成功。如果用 `when(...).thenReturn` 而不是
   `doReturn(...).when(...)` 重新打桩,异常会在哪一行抛出来?为什么 Mockito 的 `when` 要真的调用一次被 Mock 的方法?
4. `@WebMvcTest` 里 `GET /actuator/health` 返回 404 而不是 401,这个 404 能证明"拦截器只拦 /api/**"吗?
   要证明 actuator 端点真的不需要鉴权,还差什么?哪一层的用例补上了它?
5. 接口自动化的 `test_keyword_routes` 同时断言了响应分类、`llm_call_log.degraded=0`、挡板收到带标题的请求。
   把后两条去掉,再把 `LlmClientConfig` 里的 `HTTP_1_1` 那行删掉——用例还会绿吗?为什么?这说明"契约断言"和"路径断言"的区别是什么?

---

## 15. 压测、故障注入与回归验证的工具链

> 对应 v0.3-perf 和修复阶段。Python / JMeter / Docker 部分不讲语法,只讲"为什么这样组织"和"哪些坑值得知道"。

### 解决什么问题

压测的结论必须可复现、可归因、可回归。三个工具回答三个问题:

| 问题 | 工具 | 一句话 |
|---|---|---|
| 这轮数字是在什么环境下测的 | `tests/perf/tools/env_state.py` + `run_load.sh` | 每轮压测前后自动落盘池 / 堆 / GC / 后台任务 / 数据量 / MySQL 配置 / MQ 积压,报告头部就是两份快照 |
| 竞态到底发生了没有 | `grab_race.jmx` + `grab_round.sh` + `grab_evidence.py` | 集合点同时抢一张单 → 四条取证 SQL(重复 ASSIGNED 行数、终值、时间线、**序列连续性**) |
| 修复之后是否回归 | `regress_grab.sh`、`ladder_full.sh` | 用定位时**完全相同**的档位和取证重跑,并记三层防线各自的计数差值 |

### 代码怎么组织

```
tests/perf/
├── grab_race.jmx / grab_throughput.jmx / ticket_create.jmx / ticket_read.jmx   四条链路的 JMeter 模板,参数全部 -J
├── tools/
│   ├── run_load.sh          一轮 = env_before → 指标采样 + docker stats → JMeter → env_after → report.md
│   ├── env_state.py         环境快照(markdown / json 两种输出)
│   ├── grab_round.sh        竞态一轮:jmeter → 取 ticket_id → jtl 分布 → grab_evidence.py
│   ├── grab_evidence.py     Q1 重复 ASSIGNED 行数 / Q2 终值 / Q3 时间线 / Q4 序列连续性
│   ├── regress_grab.sh      2×5 / 20 / 100 线程回归 + 指标差值汇总表
│   ├── ladder_full.sh       清库 → 创建梯度 → 抢单梯度(和修复前同顺序)
│   ├── reset_grabbed.py     重置 ASSIGNED→PENDING(补审计行)/ export_ids.py 导 id 池
│   ├── jtl_stats.py         jtl → qps / 分位数(最近秩法,与 JMeter Aggregate Report 一致)
│   ├── to_platform.py       一轮产物 → 平台导入 JSON(可直接 POST)
│   ├── fault_probe.py       故障注入探针(health + me + create + grab + 指标 + 库)
│   └── arthas.sh / parse_watch.py / race_timeline.py / mysql_probe.py   Arthas 批处理与时间线还原
└── results/                 本机产物,gitignore;关键证据复制到 docs/findings/evidence/<日期>/
```

### 值得知道的坑(都在 findings / arthas-cookbook 里有出处)

- **没有环境状态头的压测数字不可比较**(KI-010):池随 10 分钟空闲从 20 缩回 2,同一脚本得到 4~20 六种成功数。
  `run_load.sh` 因此强制落盘,平台层的比较器把"环境不同"判为不可信(ADR-022)。
- **SLA 调度器是压测背景里的隐藏写者**:创建链路造的 P0 单 15 分钟后到期,调度器每 30 s 升级 100 张,
  抢单梯度是不是跑在它背后,QPS / P99 会差几个百分点。回归记录 §1 专门标了这个差异。
- **压测工具自己不能污染被测数据的一致性**:`reset_grabbed.py` 直接改库不写审计的话,审计连续性断言会把工具制造的断裂当服务缺陷。
- **Arthas 批处理客户端 ~30% 起不来**、`watch -E` 合并观测点、压测中附加 `trace` 会截断——`arthas-cookbook.md`。
- **Windows 上 `MSYS_NO_PATHCONV=1` 只给 `wsl.exe` 那一行用**:export 出去 `java.exe` 会收到 `/d/...` 路径打不开 jar。
- **读链路的瓶颈和写链路不同**(KI-017):写链路是连接持有时间,读链路是列表接口 `COUNT(*)` 的单条 SQL CPU,
  10 万张单时单核 53 次/s 封顶,10 线程就到平台。

### 自检问题

1. `run_load.sh` 在 JMeter 结束后 `sleep 12` 再采 env_after,这 12 秒在等什么?去掉会漏掉哪类数据?
2. `grab_evidence.py` 的 Q1 在修复前后分别返回什么?为什么修复后还要保留 Q4——Q1 为 1 不就够了吗?
   哪种缺陷会让 Q1 = 1 而 Q4 失败?
3. `regress_grab.sh` 记录了 `Δlock_acquired + Δlock_rejected + Δlock_unavailable`,这三者之和恒等于什么?
   100 线程那轮 acquired = 2 而 db_conflict = 0,第二个进库的请求走到了哪一行?
4. 修复前抢单梯度轮前 SLA 积压 3907~25790,修复后是 0,这对两轮的 QPS 对比意味着什么?平台的比较器会怎么判?
5. (开放题)读链路 `COUNT(*)` 的三个候选修法——覆盖索引 `(status, deleted, id)`、不返回精确 total、缓存 total——
   分别改变了什么语义?哪一个需要改接口契约?用 `EXPLAIN` 验证第一个能不能不回表。

---

## 16. 质量数据平台(platform/)

### 解决什么问题

把测试和压测的结果变成可比较的数据:执行记录、通过率 / 覆盖率趋势、性能基线对比(ADR-022)。
它是一个独立的小 Spring Boot 应用,和被测服务共用 MySQL(`qa_` 前缀表),前端是一张 CDN 引 Vue 3 + Chart.js 的静态页。

### 代码怎么组织

```
platform/src/main/java/com/ticketqa/platform/
├── PlatformApplication         @SpringBootApplication + @MapperScan + @ConfigurationPropertiesScan
├── common/                     Result 信封、GlobalExceptionHandler、JacksonConfig(LocalDateTime 格式)
├── run/                        TestRun 实体 / Mapper / Service / Controller,ImportTestRunRequest,TrendPoint
└── perf/                       PerfRun 实体(env 是 JSON 列)、PerfComparator(纯函数)、CompareProperties、Service / Controller
platform/src/main/resources/
├── schema.sql                  两张表,CREATE TABLE IF NOT EXISTS,启动时执行
└── static/index.html           三个页签:执行记录 / 趋势 / 性能基线对比
```

### Java 语言层面

- **record 当 DTO 和配置**:`ImportPerfRunRequest`、`PerfComparator.Result`、`CompareProperties` 都是 record——不可变、
  自动 equals / hashCode / toString、构造即校验。Python 的 `@dataclass(frozen=True)`。Bean Validation 注解直接写在 record 组件上。
- **嵌套 record 与静态工厂**:`PerfComparator.EnvDiff` 定义在类里面,是"只在这个上下文有意义的值类型";
  `Result.ok(data)` 是静态工厂方法,Java 没有 Python 的 `classmethod` 关键字,`static` 方法起同样的作用。
- **模式匹配 `instanceof`**:`b instanceof Number nb && c instanceof Number nc ? nb.doubleValue() == nc.doubleValue() : …`——
  Java 16 起 `instanceof` 可以顺手绑定变量,不用再强转。Python 的 `isinstance` 后直接用变量,Java 以前要写两遍。
- **`Map<String, Object>` 装 JSON**:env 快照的结构不固定,用泛型 Map 而不是实体类;`nested(m, "mysql", "mysql_vars")`
  逐层取值时每层都要 `instanceof Map` 检查——这是"无 schema 的 JSON"在静态类型语言里的真实代价。
  `@SuppressWarnings("unchecked")` 是告诉编译器"我知道这个强转擦除了泛型,我负责"。
- **`BigDecimal` 算百分比**:`BigDecimal.valueOf(d).setScale(1, RoundingMode.HALF_UP)`——金额 / 比率类数字不用 double 直接比较,
  测试里用 `isEqualByComparingTo("-9.0")` 而不是 `isEqualTo`(BigDecimal 的 `equals` 区分 `-9.0` 和 `-9.00`)。

### Spring / MyBatis-Plus 层面

- **`spring.sql.init.mode=always` + `CREATE TABLE IF NOT EXISTS`**:建表交给应用启动而不是 docker 卷的初始化脚本,
  已有卷和新卷都能用,不需要迁移文件。代价是应用必须有 DDL 权限——测试系统可以,生产通常不行。
- **`@TableName(autoResultMap = true)` + `@TableField(typeHandler = JacksonTypeHandler.class)`**:JSON 列 ↔ `Map` 的转换。
  `autoResultMap` 是关键:MyBatis-Plus 默认的查询结果映射不走 typeHandler,不加它写进去是 JSON、读出来是 null。
- **`Jackson2ObjectMapperBuilderCustomizer`**:`spring.jackson.date-format` 只管 `java.util.Date`,`LocalDateTime` 要单独注册
  序列化 / 反序列化器——导入脚本发 `"2026-09-21 01:55:18"` 被默认 ISO 解析器拒掉就是这个原因。被测服务的 `JacksonConfig` 同理。
- **`@ConfigurationPropertiesScan` + record**:`platform.compare.*` 绑定到 `CompareProperties` record,`@Validated` 让非法阈值在启动时失败。
  比较器通过构造函数拿到两个阈值,自己不依赖 Spring——所以它的 7 条单测不需要起容器。
- **统一 `LIMIT` 用 `.last("LIMIT n")`**:MyBatis-Plus 的 `LambdaQueryWrapper` 没有 limit 方法,`last` 把字符串原样拼到 SQL 末尾;
  n 来自服务端 clamp 过的参数,不是用户原文,否则就是注入点。

### 自检问题

1. 把 `autoResultMap = true` 去掉,`POST /api/perf-runs` 之后 `GET /api/perf-runs/{id}` 的 `env` 字段会是什么?为什么写没问题读有问题?
2. `PerfComparator.envDiffs` 对缺失的键记 `current=null, significant=false`。如果改成"缺键即显著",2026-09-20 的旧快照
   (没有 Tomcat 线程数)和新快照的对比会全部变成什么?哪种选择更诚实?
3. 通过率的分母为什么去掉 skipped 和 xfailed?一个 312 条、3 条 xfail、1 条 skip(某次在空库上跑出来的)、全部通过的批次,两种算法分别显示多少?
4. `TestRunService.importRun` 用"查一次再 insert / update"实现覆盖,两个 CI 同时导入同一 batchNo 会怎样?
   `uk_test_run_batch` 唯一键在这里起什么作用?异常会被谁翻译成什么码?
5. (开放题)六组"修复前 vs 修复后"对比都被判 UNRELIABLE。要拿到一组可信的 A/B,你会怎么安排环境和轮次?
   平台还缺哪个接口来支持"多轮取中位数"?

---

## 附:各节自检题的用法

- 每节 5 题,共 80 题(第 14 节是测试阶段加的,第 15、16 节是修复 / 平台阶段加的;第 6 节按修复后的实现重写)。**不要查答案**,先对着代码推,推不出来再跑起来验证——`README.md`
  里的 curl 清单和 `docker compose stop` 就是验证工具。
- 第 6 节全部、第 10 节全部、第 14 节第 5 题、第 15 节第 4 题,是最值得反复推敲的部分。
- 第 14 节的用例清单在 `docs/test-inventory.md`,设计方法在 `docs/test-design/`,读代码时对着看。
- 推完的结论写进 `docs/findings/`,那里要求的是你亲手跑出来的真实结果。
