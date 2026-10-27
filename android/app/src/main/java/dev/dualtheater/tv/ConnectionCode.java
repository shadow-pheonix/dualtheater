package dev.dualtheater.tv;

final class ConnectionCode {
    static String normalize(String input) {
        String code = input == null ? "" : input.replace(" ", "").replace("-", "").trim();
        if (!code.matches("[0-9]{6}")) throw new IllegalArgumentException("Enter all six digits shown on the laptop");
        return code;
    }
}
