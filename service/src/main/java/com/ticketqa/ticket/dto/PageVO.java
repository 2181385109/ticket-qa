package com.ticketqa.ticket.dto;

import java.util.List;

/** 分页结果。泛型 T 在编译期擦除,运行时只是 List<Object>,Jackson 靠实际元素类型序列化。 */
public record PageVO<T>(List<T> records, long total, long page, long size) {
}
