package com.ticketqa.support;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;

/**
 * 可以手动拨动的 Clock。Clock.fixed 只能钉死一个时刻,熔断器"60 秒后自动恢复"这种用例
 * 需要在同一个测试里让时间前进——不 sleep,直接 advance(Duration.ofSeconds(60))。
 *
 * Clock 是抽象类(不是接口),所以要覆写 getZone / withZone / instant 三个抽象方法。
 */
public class MutableClock extends Clock {

    private Instant now;
    private final ZoneId zone;

    public MutableClock(Instant start, ZoneId zone) {
        this.now = start;
        this.zone = zone;
    }

    public static MutableClock at(Instant start) {
        return new MutableClock(start, TestFixtures.SHANGHAI);
    }

    public void advance(Duration d) {
        now = now.plus(d);
    }

    public void set(Instant instant) {
        now = instant;
    }

    @Override
    public ZoneId getZone() {
        return zone;
    }

    @Override
    public Clock withZone(ZoneId zone) {
        return new MutableClock(now, zone);
    }

    @Override
    public Instant instant() {
        return now;
    }
}
