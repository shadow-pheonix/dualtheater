package dev.dualtheater.calibration;

import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

final class PhoneClient implements AutoCloseable {
    interface Listener {
        void message(JSONObject message, String action);
        void disconnected(String reason);
    }
    private final Listener listener;
    private final AtomicBoolean closed = new AtomicBoolean();
    private final AtomicLong sequence = new AtomicLong();
    private final BlockingQueue<String> outbound = new ArrayBlockingQueue<>(64);
    private final Map<Long, String> actions = new ConcurrentHashMap<>();
    private final ScheduledExecutorService polls = Executors.newSingleThreadScheduledExecutor();
    private volatile Socket socket;
    private Thread writerThread;

    PhoneClient(Listener listener) { this.listener = listener; }

    void connect(String host, int port, String code, String clientId) {
        new Thread(() -> {
            try {
                Socket value = new Socket(); socket = value;
                value.connect(new InetSocketAddress(host, port), 5000);
                value.setTcpNoDelay(true); value.setSoTimeout(4000);
                BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(value.getOutputStream(), StandardCharsets.UTF_8));
                JSONObject hello = new JSONObject().put("op", "hello").put("version", 1).put("role", "calibration")
                    .put("client_protocol", 1)
                    .put("client_id", clientId).put("token", code).put("device", "Calibration phone");
                writer.write(hello.toString()); writer.newLine(); writer.flush();
                writerThread = new Thread(() -> {
                    try {
                        while (!closed.get()) { writer.write(outbound.take()); writer.newLine(); writer.flush(); }
                    } catch (Exception error) { disconnect("Calibration connection closed"); }
                }, "calibration-writer");
                writerThread.start();
                BufferedReader reader = new BufferedReader(new InputStreamReader(value.getInputStream(), StandardCharsets.UTF_8));
                while (!closed.get()) {
                    StringBuilder line = new StringBuilder(); int c;
                    while ((c = reader.read()) != -1 && c != '\n') {
                        if (line.length() >= 65536) throw new IOException("Oversized host message");
                        line.append((char)c);
                    }
                    if (c == -1) throw new EOFException();
                    JSONObject message = new JSONObject(line.toString());
                    listener.message(message, actions.remove(message.optLong("reply", -1)));
                }
            } catch (Exception error) { disconnect("Disconnected. Reconnect before starting another test."); }
        }, "calibration-reader").start();
    }

    void startPolling() { polls.scheduleAtFixedRate(() -> send("status", null), 0, 500, TimeUnit.MILLISECONDS); }

    synchronized void send(String action, JSONObject values) {
        if (closed.get()) return;
        try {
            long id = sequence.incrementAndGet();
            JSONObject message = values == null ? new JSONObject() : new JSONObject(values.toString());
            message.put("op", "calibration").put("id", id).put("action", action);
            actions.put(id, action);
            if (!outbound.offer(message.toString()) || actions.size() > 64) disconnect("Host stopped responding; reconnect and retry");
        } catch (JSONException error) { disconnect("Invalid calibration message"); }
    }

    synchronized long request(String action, JSONObject values) {
        try {
            JSONObject message = values == null ? new JSONObject() : new JSONObject(values.toString());
            message.put("op", "client_request").put("action", action);
            return sendMessage(message, "client:" + action);
        } catch (JSONException error) { disconnect("Invalid player request"); return -1; }
    }

    synchronized long registerStorage(JSONObject registration) {
        return sendMessage(registration, "storage_register");
    }

    private long sendMessage(JSONObject values, String action) {
        if (closed.get()) return -1;
        try {
            long id = sequence.incrementAndGet();
            JSONObject message = new JSONObject(values.toString()).put("id", id);
            actions.put(id, action);
            if (!outbound.offer(message.toString()) || actions.size() > 64) disconnect("Host stopped responding; reconnect and retry");
            return id;
        } catch (JSONException error) { disconnect("Invalid player request"); return -1; }
    }

    private void disconnect(String reason) {
        if (closed.compareAndSet(false, true)) {
            polls.shutdownNow();
            try { if (socket != null) socket.close(); } catch (IOException ignored) {}
            if (writerThread != null) writerThread.interrupt();
            actions.clear(); listener.disconnected(reason);
        }
    }
    @Override public void close() { disconnect("Disconnected"); }
}
