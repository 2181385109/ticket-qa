package com.ticketqa.domain.enums;

import java.util.Optional;

public enum TicketPriority {
    P0,
    P1,
    P2;

    public static Optional<TicketPriority> parse(String raw) {
        if (raw == null) {
            return Optional.empty();
        }
        String normalized = raw.trim().toUpperCase();
        for (TicketPriority p : values()) {
            if (p.name().equals(normalized)) {
                return Optional.of(p);
            }
        }
        return Optional.empty();
    }
}
