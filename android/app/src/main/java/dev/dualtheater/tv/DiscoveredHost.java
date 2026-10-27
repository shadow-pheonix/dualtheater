package dev.dualtheater.tv;

import java.util.UUID;

final class DiscoveredHost {
    final String id, name, address;
    final int port;
    DiscoveredHost(String id, String name, String address, int port) {
        if (id == null || id.length() != 36 || !UUID.fromString(id).toString().equalsIgnoreCase(id))
            throw new IllegalArgumentException("Invalid laptop identity");
        if (!ipv4(address) || port < 1 || port > 65535)
            throw new IllegalArgumentException("Invalid laptop address");
        String label = name == null ? "Laptop" : name.replaceAll("[\\p{Cntrl}]", "").trim();
        this.id = id.toLowerCase(java.util.Locale.ROOT);
        this.name = label.isEmpty() ? "Laptop" : label.substring(0, Math.min(48, label.length()));
        this.address = address;
        this.port = port;
    }
    private static boolean ipv4(String address) {
        if (address == null) return false;
        String[] parts = address.split("\\.", -1);
        if (parts.length != 4) return false;
        for (String part : parts) {
            if (!part.matches("[0-9]{1,3}") || Integer.parseInt(part) > 255) return false;
        }
        return true;
    }
}
