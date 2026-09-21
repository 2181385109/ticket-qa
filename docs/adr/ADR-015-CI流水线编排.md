# ADR-015: CI 用仓库里的 docker-compose 起中间件、java -jar 起服务,而不是 GitHub services 或容器化服务

## 背景

CLAUDE.md 要求的流水线:编译 → 单测 → JaCoCo 增量覆盖率门禁 → 起服务和中间件 → 接口自动化 → Allure 报告归档。
接口自动化需要 MySQL(带 6 个种子坐席和 5 张表)、Redis、RabbitMQ、WireMock(带 `ops/wiremock/mappings` 里的桩)。
怎么在 GitHub Actions 的 runner 上把这四样起成和本地一样,是本 ADR 要定的。

## 选项

- **方案 A:GitHub Actions 的 `services:` 语法**
  做法:job 级声明四个 service 容器。
  代价:`services:` 不能挂载仓库里的文件——MySQL 的初始化 SQL(`ops/mysql/init/*.sql`)和 WireMock 的桩目录
  都进不去,得在 step 里再用 `mysql` 客户端灌表、用管理 API 一条条 POST 桩。等于把 compose 文件已经描述的东西
  用另一种语言再写一遍,两份配置会漂移。

- **方案 B:复用 `ops/docker-compose.yml`,服务用 `java -jar` 起在 runner 本机** ← 采用
  做法:`cp .env.example .env && docker compose up -d mysql redis rabbitmq wiremock`,轮询 `docker compose ps` 直到全部 healthy;
  `mvn package` 后 `nohup java -jar` 起服务,轮询 `/actuator/health`;pytest 用 `TICKETQA_ENV=ci`。
  代价:多一段"等 healthy"的 shell;runner 上跑 Java 进程要自己管 pid 和日志归档。

- **方案 C:compose 的 `--profile app` 把服务也容器化起**
  做法:`docker compose --profile app up -d --build`。
  代价:每次 CI 多一次镜像构建(多阶段构建约 2 分钟);服务日志要 `docker logs` 才能拿到;
  附件目录在容器卷里,`ATTACHMENT_DIR` 相关的落盘断言拿不到文件。

## 决定

方案 B。理由一句话:**CI 环境应该尽量等于本地联调环境,而本地联调就是 compose 起中间件 + 宿主起服务**。
同一份 compose 文件、同一份 `.env.example`、同一组默认口令,CI 和本地的差异只剩 `TICKETQA_ENV`。

编排细节:

- 两个 job:`unit`(编译 + 单测 + JaCoCo check + diff-cover)和 `api`(中间件 + 服务 + pytest + Allure),
  `api` `needs: unit`——单测红了不浪费 5 分钟起环境。
- `concurrency` 按分支取消旧的运行,连续 push 只跑最后一次。
- Allure 报告在 CI 里用 Allure CLI 生成 HTML 并 `upload-artifact`(30 天),原始 `allure-results` 也归档
  (可以和历史合并看趋势);不发布到 GitHub Pages——那是公开发布,不在本阶段范围。
- 服务日志归档 7 天:接口用例失败时按响应里的 traceId 到日志里 grep。
- 增量覆盖率的基线:PR 用 `origin/<base>`,push 用 `HEAD~1`,仓库首个提交没有 `HEAD~1` 时退到根提交。

## 后果

- 接受了:一次完整 CI 约 8~10 分钟(Maven 缓存命中后:unit ~3 分钟,api ~5 分钟,其中 60 秒是等熔断恢复)。
- 接受了:GitHub 私有仓库的 Actions 分钟数有配额(免费 2000 分钟/月),按 10 分钟一次算 200 次;公开仓库不限。
- 接受了:runner 上的 Docker 是 GitHub 提供的,镜像每次都要拉(MySQL 8 + RabbitMQ 管理版 + WireMock,约 1 分钟)。
- 什么场景下这个选择是错的:如果服务需要在容器网络里才能连到中间件(比如换成 Kubernetes 风格的 DNS 名),
  宿主起服务就连不上了,那时候换方案 C。

补记(2026-09-21):容量用例(`capacity` 标记)在 api job 里单独一步——用 `HIKARI_MAX_POOL_SIZE=3` 重启服务后只跑这三条,
两步的 Allure 结果合成一份报告;coverage.py 用 `--append` 合并。原因在 ADR-023。

## 常见质疑与回应

**"为什么不用 GitHub 自带的 services?"**
> 因为它挂不了文件。MySQL 的建表和种子数据、WireMock 的桩,都是仓库里的文件,`services:` 只能给镜像和环境变量。
> 用 services 就得在 step 里把这些再灌一遍,和本地的 compose 文件成了两套配置——两套配置一定会漂移,漂移的那天
> CI 通过本地失败,或者反过来。复用 compose 文件是让 CI 和本地只差一个环境变量。

**"服务为什么不也容器化?"**
> 本地联调就是宿主起服务(README §3),CI 照做。容器化多一次构建、日志要 docker logs、附件卷拿不到文件,
> 换来的只是"更像生产"——但这个项目没有生产,只有测试环境。`--profile app` 保留着,想容器化随时切。

**"Allure 为什么不发到 Pages?"**
> 发 Pages 等于公开发布测试报告,报告里有请求响应体,不是这个阶段该做的决定。artifact 归档 30 天,
> 点进 workflow run 就能下载解压看,够用。要趋势就把每次的 `allure-results` 合并后再 generate。

**"CI 上 Windows 才有的问题怎么办?"**
> 本地是 Windows 宿主,CI 是 Ubuntu。已知的差异有一条:Windows Defender 会隔离 Tomcat 的上传临时文件
> (known-issues KI-003),Ubuntu 上没有。所以套件里的载荷刻意写成无害的,两边一致;
> 真要测"服务读不到上传文件"的分支,得单独写一个用例,现在没有。

**替代方案**(以上是默认选择,可按需改)
> 如果想要报告可点链接:加一个 `actions/deploy-pages` 的 job 把 `tests/allure-report` 发出去,
> 前提是仓库设为公开或接受 Pages 的可见性。
